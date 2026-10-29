"""Conformance with the Poli Page API contract (https://github.com/poli-page/api-contract).

CI copies the pinned `contract.json` with the `poli-page/api-contract` action and sets
`POLI_CONTRACT` to its path. Every `kind: "sdk"` case runs against a local HTTP server that
answers the case's `responses` in order and records each request; the test then compares the
recorded requests, the `on_request` / `on_retry` events and the normalized result with the
case's `expect`. Timing is checked as lower bounds, measured on the server. Each case runs
against both clients, `PoliPage` and `AsyncPoliPage`.

`contract-skip.json` maps the case ids allowed to fail to the reason. A listed case that
passes, or a listed id that is not a case this test runs, fails the run.

Locally: `POLI_CONTRACT=/path/to/contract.json pytest`. Without it the module is skipped,
except in CI, where a missing contract is an error.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import email.utils
import hashlib
import json
import os
import re
import socket
import threading
import time
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

from poli_page import AsyncPoliPage, PoliPage, PoliPageError
from poli_page._constants import (
    MESSAGE_DOWNLOAD_FAILED,
    MESSAGE_DOWNLOAD_FAILED_NETWORK,
    MESSAGE_INVALID_OPTIONS,
    MESSAGE_NETWORK_ERROR,
    MESSAGE_PROJECT_REQUIRED,
    MESSAGE_TIMEOUT,
    NON_RETRYABLE_CODES,
    RETRY_AFTER_CAP_SECONDS,
)
from poli_page.types import (
    AsyncDocumentDescriptor,
    DocumentDescriptor,
    DocumentPreviewResult,
    RenderInput,
    RequestEvent,
    RetryEvent,
    Thumbnail,
    ThumbnailOptions,
)

# ---------------------------------------------------------------------------
# Contract format 1 (README of poli-page/api-contract)
# ---------------------------------------------------------------------------

KNOWN_FORMAT_VERSION = 1

#: This SDK's name in `policy.cancellationSdks`.
SDK_NAME = "python"

#: The client's key when a case sets no `apiKey`.
TEST_API_KEY = "pp_sandbox_00000000000000000000000000000000"

SKIP_LIST_PATH = Path(__file__).with_name("contract-skip.json")


class ContractError(Exception):
    """The contract file, or the skip list, is not something this test can run."""


def _load_contract(path: str) -> dict[str, Any]:
    try:
        parsed: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"POLI_CONTRACT={path} cannot be read as JSON: {exc}") from exc
    if not isinstance(parsed, dict) or "formatVersion" not in parsed:
        raise ContractError(f"{path} is not a contract.json: it has no formatVersion")
    contract = cast(dict[str, Any], parsed)
    if contract["formatVersion"] != KNOWN_FORMAT_VERSION:
        raise ContractError(
            f"contract.json formatVersion {contract['formatVersion']!r} is not supported "
            f"(this test reads format {KNOWN_FORMAT_VERSION}): update tests/test_contract.py"
        )
    return contract


def _load_skip_list() -> dict[str, str]:
    parsed: object = json.loads(SKIP_LIST_PATH.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ContractError("tests/contract-skip.json must be an object of case id to reason")
    skip: dict[str, str] = {}
    for case_id, reason in cast(dict[str, object], parsed).items():
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError(f'tests/contract-skip.json: "{case_id}" needs a reason')
        skip[case_id] = reason
    return skip


# ---------------------------------------------------------------------------
# Normalizations (policy.normalizations): the only rewrites applied to a native result
# ---------------------------------------------------------------------------

#: The normalization ids this file applies; each must be listed in the contract's policy.
NORMALIZATIONS_USED = (
    "N-STATUS-NULL",
    "N-REQID-NULL",
    "N-BYTES",
    "N-DELETE-NULL",
    "N-THUMBS-ARRAY",
    "N-PREVIEW",
    "N-DESCRIPTOR",
    "N-DURATION-MS",
)

#: sdk-specification.md §7.1, the descriptor fields (N-DESCRIPTOR): wire name to attribute.
DESCRIPTOR_FIELDS = {
    "documentId": "document_id",
    "organizationId": "organization_id",
    "projectId": "project_id",
    "projectSlug": "project_slug",
    "templateId": "template_id",
    "templateSlug": "template_slug",
    "environment": "environment",
    "apiKeyId": "api_key_id",
    "format": "format",
    "orientation": "orientation",
    "locale": "locale",
    "pageCount": "page_count",
    "sizeBytes": "size_bytes",
    "createdAt": "created_at",
    "metadata": "metadata",
    "presignedPdfUrl": "presigned_pdf_url",
    "expiresAt": "expires_at",
}


def _descriptor(value: DocumentDescriptor | AsyncDocumentDescriptor) -> dict[str, Any]:
    """N-DESCRIPTOR, with the attributes under their wire names (§2 naming)."""
    return {wire: getattr(value, attr) for wire, attr in DESCRIPTOR_FIELDS.items()}


def _bytes(data: bytes) -> dict[str, Any]:
    """N-BYTES."""
    return {"sha256": hashlib.sha256(data).hexdigest(), "length": len(data)}


def _preview(value: DocumentPreviewResult) -> dict[str, Any]:
    """N-PREVIEW."""
    return {"html": value.html, "pageCount": value.page_count}


def _thumbnails(value: list[Thumbnail]) -> list[dict[str, Any]]:
    """N-THUMBS-ARRAY: the SDK already returns the unwrapped list."""
    return [
        {
            "page": t.page,
            "width": t.width,
            "height": t.height,
            "contentType": t.content_type,
            "data": t.data,
        }
        for t in value
    ]


def _normalize_error(err: BaseException) -> dict[str, Any]:
    """N-STATUS-NULL, N-REQID-NULL; anything that is not a PoliPageError shows in the diff."""
    if isinstance(err, PoliPageError):
        return {
            "code": err.code,
            "status": err.status,
            "message": err.message,
            "requestId": err.request_id,
            "retryable": err.is_retryable(),
            "isAuthError": err.is_auth_error(),
            "isRateLimitError": err.is_rate_limit_error(),
            "isValidationError": err.is_validation_error(),
            "isNetworkError": err.is_network_error(),
        }
    return {
        "code": "not a PoliPageError",
        "status": None,
        "message": f"{type(err).__name__}: {err}",
        "requestId": None,
        "retryable": False,
        "isAuthError": False,
        "isRateLimitError": False,
        "isValidationError": False,
        "isNetworkError": False,
    }


# ---------------------------------------------------------------------------
# Placeholders: {{mock}}, {{httpDate+N}}
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{([^}]*)\}\}")
_HTTP_DATE = re.compile(r"^httpDate\+(\d+)$")


def _substitute(value: Any, mock: str) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name == "mock":
                return mock
            date = _HTTP_DATE.match(name)
            if date:
                # An HTTP-date has whole seconds: round to the nearest one.
                return email.utils.formatdate(round(time.time() + int(date.group(1))), usegmt=True)
            raise ContractError(f"Unknown contract placeholder {{{{{name}}}}}")

        return _PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [_substitute(item, mock) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        return {key: _substitute(item, mock) for key, item in cast(dict[str, Any], value).items()}
    return value


# ---------------------------------------------------------------------------
# Mock server
# ---------------------------------------------------------------------------


class RecordedRequest:
    __slots__ = ("at", "body", "headers", "method", "path")

    def __init__(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes, at: float
    ) -> None:
        self.method = method
        self.path = path
        #: Lowercased header names.
        self.headers = headers
        self.body = body
        #: `time.perf_counter()` when the request reached the server, in seconds.
        self.at = at


class MockServer:
    """Answers the case's `responses` in order on 127.0.0.1 and records every request."""

    def __init__(self, steps: Sequence[Mapping[str, Any]]) -> None:
        self.steps = steps
        self.requests: list[RecordedRequest] = []
        #: Errors raised while answering (a bad case step); `_run_case` re-raises the first.
        self.errors: list[Exception] = []
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._httpd.daemon_threads = True
        port = self._httpd.server_address[1]
        self.origin = f"http://127.0.0.1:{port}"
        # A short poll interval keeps `shutdown()` quick: it waits for the next poll.
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._release.set()  # ends every `hang`
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def _record(self, request: RecordedRequest) -> Mapping[str, Any] | None:
        with self._lock:
            self.requests.append(request)
            index = len(self.requests) - 1
        return self.steps[index] if index < len(self.steps) else None

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _handle(self) -> None:
                try:
                    self._handle_step()
                except Exception as exc:
                    server.errors.append(exc)
                    self.close_connection = True

            def _handle_step(self) -> None:
                at = time.perf_counter()
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                headers = {name.lower(): value for name, value in self.headers.items()}
                step = server._record(RecordedRequest(self.command, self.path, headers, body, at))
                if step is None:
                    # More requests than the case has answers: make it visible in the diff.
                    self._answer({"status": 599, "json": {"error": "MOCK_EXHAUSTED"}})
                elif step.get("fault") == "drop":
                    self.close_connection = True
                    with contextlib.suppress(OSError):
                        self.connection.shutdown(socket.SHUT_RDWR)
                elif step.get("fault") == "hang":
                    server._release.wait()
                    self.close_connection = True
                elif "fault" in step:
                    raise ContractError(f"Unknown fault {step['fault']!r}")
                else:
                    self._answer(step)

            def _answer(self, step: Mapping[str, Any]) -> None:
                headers = cast(dict[str, str], _substitute(step.get("headers", {}), server.origin))
                has_type = any(name.lower() == "content-type" for name in headers)
                body: bytes | None = None
                if "json" in step:
                    body = json.dumps(_substitute(step["json"], server.origin)).encode()
                    if not has_type:
                        headers["Content-Type"] = "application/json"
                elif "text" in step:
                    body = cast(str, step["text"]).encode()
                elif "base64" in step:
                    body = base64.b64decode(cast(str, step["base64"]))
                self.send_response(cast(int, step["status"]))
                for name, value in headers.items():
                    self.send_header(name, value)
                if body is not None:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body is not None:
                    self.wfile.write(body)

            do_GET = _handle
            do_POST = _handle
            do_DELETE = _handle

        return Handler


# ---------------------------------------------------------------------------
# Calling the SDK
# ---------------------------------------------------------------------------


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _object_arg(args: Sequence[Any], index: int) -> dict[str, Any] | None:
    """An input dict, its top-level keys in Python casing (§2); nested values unchanged."""
    if index >= len(args) or args[index] is None:
        return None
    value = args[index]
    if not isinstance(value, dict):
        raise ContractError(f"call.args[{index}] must be an object")
    return {_snake(key): item for key, item in cast(dict[str, Any], value).items()}


def _string_arg(args: Sequence[Any], index: int) -> str:
    value = args[index] if index < len(args) else None
    if not isinstance(value, str):
        raise ContractError(f"call.args[{index}] must be a string")
    return value


def _render_input(args: Sequence[Any]) -> RenderInput:
    value = _object_arg(args, 0)
    if value is None:
        raise ContractError("call.args[0] must be the render input")
    return cast(RenderInput, value)


def _invoke_sync(client: PoliPage, method: str, args: Sequence[Any]) -> Any:
    """Calls `call.method` and returns its normalized value."""
    if method == "render.pdf":
        return _bytes(client.render.pdf(_render_input(args)))
    if method == "render.pdfStream":
        with client.render.pdf_stream(_render_input(args)) as chunks:
            return _bytes(b"".join(chunks))
    if method == "render.document":
        return _descriptor(client.render.document(_render_input(args)))
    if method == "documents.get":
        return _descriptor(client.documents.get(_string_arg(args, 0)))
    if method == "documents.preview":
        return _preview(client.documents.preview(_string_arg(args, 0)))
    if method == "documents.thumbnails":
        options = cast("ThumbnailOptions | None", _object_arg(args, 1))
        return _thumbnails(client.documents.thumbnails(_string_arg(args, 0), options))
    if method == "documents.delete":
        client.documents.delete(_string_arg(args, 0))
        return None  # N-DELETE-NULL
    raise ContractError(f"Unknown SDK method in the contract: {method}")


async def _invoke_async(client: AsyncPoliPage, method: str, args: Sequence[Any]) -> Any:
    """Calls `call.method` and returns its normalized value."""
    if method == "render.pdf":
        return _bytes(await client.render.pdf(_render_input(args)))
    if method == "render.pdfStream":
        async with client.render.pdf_stream(_render_input(args)) as chunks:
            return _bytes(b"".join([chunk async for chunk in chunks]))
    if method == "render.document":
        return _descriptor(await client.render.document(_render_input(args)))
    if method == "documents.get":
        return _descriptor(await client.documents.get(_string_arg(args, 0)))
    if method == "documents.preview":
        return _preview(await client.documents.preview(_string_arg(args, 0)))
    if method == "documents.thumbnails":
        options = cast("ThumbnailOptions | None", _object_arg(args, 1))
        return _thumbnails(await client.documents.thumbnails(_string_arg(args, 0), options))
    if method == "documents.delete":
        await client.documents.delete(_string_arg(args, 0))
        return None  # N-DELETE-NULL
    raise ContractError(f"Unknown SDK method in the contract: {method}")


class _StopCall(BaseException):
    """Raised from `on_retry` at the `stopAfterRetryEvents`-th retry event (control flow).

    The Python SDK has no cancellation, so the test abandons the call this way. The SDK
    swallows an `Exception` raised by a hook; a `BaseException` passes through it.
    """


class _Recorder:
    """The client options and hooks of one case run, and the events they record."""

    def __init__(self, case: Mapping[str, Any], origin: str) -> None:
        options = cast(Mapping[str, Any], case["options"])
        self.api_key: str = case.get("apiKey", TEST_API_KEY)
        self.stop_after: int | None = case.get("stopAfterRetryEvents")
        self.events: list[dict[str, Any]] = []
        self._retries = 0
        self.kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": origin,
            "max_retries": options["maxRetries"],
            "retry_delay": options["retryDelayMs"] / 1000,
            "timeout": options["timeoutMs"] / 1000,
            "on_request": self.on_request,
            "on_retry": self.on_retry,
        }

    def on_request(self, event: RequestEvent) -> None:
        self.events.append({"type": "request", "attempt": event.attempt})

    def on_retry(self, event: RetryEvent) -> None:
        # N-DURATION-MS: `delay_ms` is a float.
        self.events.append(
            {"type": "retry", "attempt": event.attempt, "delayMs": round(event.delay_ms)}
        )
        self._retries += 1
        if self._retries == self.stop_after:
            raise _StopCall


def _run_sync(case: Mapping[str, Any], recorder: _Recorder) -> dict[str, Any] | None:
    call = cast(Mapping[str, Any], case["call"])
    try:
        with PoliPage(**recorder.kwargs) as client:
            value = _invoke_sync(client, call["method"], call["args"])
    except _StopCall:
        return None
    except ContractError:
        raise
    except Exception as err:
        return {"ok": False, "error": _normalize_error(err)}
    return {"ok": True, "value": value}


async def _run_async(case: Mapping[str, Any], recorder: _Recorder) -> dict[str, Any] | None:
    call = cast(Mapping[str, Any], case["call"])
    try:
        async with AsyncPoliPage(**recorder.kwargs) as client:
            value = await _invoke_async(client, call["method"], call["args"])
    except _StopCall:
        return None
    except ContractError:
        raise
    except Exception as err:
        return {"ok": False, "error": _normalize_error(err)}
    return {"ok": True, "value": value}


# ---------------------------------------------------------------------------
# Comparing one case
# ---------------------------------------------------------------------------

_UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _describe_requests(
    recorded: Sequence[RecordedRequest],
    expected: Sequence[Mapping[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    """The recorded requests in the shape of `expect.requests`.

    A field that breaks the expectation keeps the observed value, so the diff shows it.
    """
    first_key: str | None = None
    out: list[dict[str, Any]] = []
    for i, req in enumerate(recorded):
        want = expected[i] if i < len(expected) else {}
        authorization = req.headers.get("authorization")
        if authorization is None:
            auth = "none"
        elif authorization == f"Bearer {api_key}":
            auth = "bearer"
        else:
            auth = f"unexpected Authorization: {authorization}"
        key = req.headers.get("idempotency-key")
        if key is None:
            idempotency_key = "absent"
        elif not _UUID_V4.match(key):
            idempotency_key = f"not a lowercase UUID v4: {key}"
        else:
            first_key = first_key or key
            idempotency_key = "stable" if key == first_key else f"changed: {first_key} then {key}"
        item: dict[str, Any] = {
            "method": req.method,
            "path": req.path,
            "auth": auth,
            "idempotencyKey": idempotency_key,
        }
        if "json" in want:
            try:
                item["json"] = json.loads(req.body)
            except ValueError:
                item["json"] = f"body is not JSON: {req.body!r}"
        if "minGapMsBefore" in want:
            gap_ms = (req.at - recorded[i - 1].at) * 1000 if i > 0 else 0.0
            min_gap = want["minGapMsBefore"]
            item["minGapMsBefore"] = min_gap if gap_ms >= min_gap else f"only {gap_ms:.1f} ms"
        out.append(item)
    return out


def _describe_events(
    actual: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The observed events, with a delay inside an expected range shown as that range."""
    out: list[dict[str, Any]] = []
    for i, event in enumerate(actual):
        want = expected[i] if i < len(expected) else {}
        delay = want.get("delayMs")
        if (
            event["type"] == "retry"
            and want.get("type") == "retry"
            and isinstance(delay, dict)
            and cast(dict[str, int], delay)["min"] <= event["delayMs"]
            and event["delayMs"] < cast(dict[str, int], delay)["max"]
        ):
            out.append({**event, "delayMs": delay})
        else:
            out.append(dict(event))
    return out


def _expected_prefix(
    case: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], bool]:
    """(events, requests, check_result), cut at the `stopAfterRetryEvents`-th retry event."""
    expect = cast(Mapping[str, Any], case["expect"])
    events = cast(list[Mapping[str, Any]], expect["events"])
    requests = cast(list[Mapping[str, Any]], expect["requests"])
    stop: int | None = case.get("stopAfterRetryEvents")
    if stop is None:
        return events, requests, True
    retries = 0
    for end, event in enumerate(events):
        if event["type"] == "retry":
            retries += 1
            if retries == stop:
                cut = events[: end + 1]
                attempts = sum(1 for e in cut if e["type"] == "request")
                return cut, requests[:attempts], False
    raise ContractError(f"stopAfterRetryEvents {stop}: the case has fewer retries")


def _run_case(case: Mapping[str, Any], flavor: str) -> None:
    requires = case.get("requires")
    if requires is not None and requires != "cancellation":
        raise ContractError(f"Unknown case requirement: {requires!r}")
    if cast(Mapping[str, Any], case["call"]).get("cancelAfterMs") is not None:
        raise ContractError("The Python SDK has no cancellation: cancelAfterMs cannot run")
    _substitute(case, "http://127.0.0.1")  # an unknown placeholder fails before any request
    server = MockServer(cast(list[Mapping[str, Any]], case["responses"]))
    try:
        recorder = _Recorder(case, server.origin)
        if flavor == "sync":
            result = _run_sync(case, recorder)
        else:
            result = asyncio.run(_run_async(case, recorder))
    finally:
        server.close()
    if server.errors:
        raise server.errors[0]

    events, requests, check_result = _expected_prefix(case)
    mock = server.origin
    actual_requests = _describe_requests(server.requests, requests, recorder.api_key)
    assert actual_requests == _substitute(requests, mock), "requests"
    assert _describe_events(recorder.events, events) == events, "on_request / on_retry events"
    if check_result:
        expected_result = _substitute(cast(Mapping[str, Any], case["expect"])["result"], mock)
        assert result == expected_result, "result"


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------

_CONTRACT_PATH = os.environ.get("POLI_CONTRACT")

if not _CONTRACT_PATH:
    if os.environ.get("CI"):

        def test_poli_contract_is_set() -> None:
            pytest.fail(
                'POLI_CONTRACT is not set: in CI the "API contract" step must provide '
                "contract.json (poli-page/api-contract action, output `path`)"
            )

    else:
        pytest.skip(
            "API contract: set POLI_CONTRACT to a contract.json path to run it",
            allow_module_level=True,
        )

else:
    CONTRACT = _load_contract(_CONTRACT_PATH)
    POLICY = cast(dict[str, Any], CONTRACT["policy"])
    SKIP = _load_skip_list()
    ALL_CASES = cast(list[dict[str, Any]], CONTRACT["cases"])
    SDK_CASES = [c for c in ALL_CASES if c.get("kind") == "sdk"]
    RUNS_CANCELLATION = SDK_NAME in cast(list[str], POLICY["cancellationSdks"])

    def _runs(case: Mapping[str, Any]) -> bool:
        return case.get("requires") != "cancellation" or RUNS_CANCELLATION

    RUNNING_IDS = {c["id"] for c in SDK_CASES if _runs(c)}

    def test_contract_has_sdk_cases_and_known_kinds() -> None:
        assert SDK_CASES, 'the contract has no kind "sdk" case'
        unknown = [c.get("kind") for c in ALL_CASES if c.get("kind") not in ("sdk", "impl")]
        assert unknown == [], 'case kinds other than "sdk" and "impl"'

    def test_applies_only_the_normalizations_the_contract_allows() -> None:
        allowed = {n["id"] for n in cast(list[dict[str, str]], POLICY["normalizations"])}
        assert [n for n in NORMALIZATIONS_USED if n not in allowed] == []

    def test_skip_list_names_only_cases_that_run() -> None:
        unknown = sorted(set(SKIP) - RUNNING_IDS)
        assert unknown == [], "not cases this test runs: remove them from contract-skip.json"

    def test_sdk_messages_match_policy() -> None:
        errors = cast(dict[str, dict[str, str]], POLICY["sdkErrors"])
        download = errors["DOWNLOAD_FAILED"]
        messages = {
            "invalid_options": MESSAGE_INVALID_OPTIONS,
            "network_error": MESSAGE_NETWORK_ERROR,
            "timeout": MESSAGE_TIMEOUT,
            "DOWNLOAD_FAILED": MESSAGE_DOWNLOAD_FAILED,
            "PROJECT_REQUIRED_FOR_DOCUMENT": MESSAGE_PROJECT_REQUIRED,
        }
        assert messages == {code: errors[code]["message"] for code in messages}
        assert download["networkMessage"] == MESSAGE_DOWNLOAD_FAILED_NETWORK
        sdk_codes = set(errors) - ({"aborted"} if not RUNS_CANCELLATION else set())
        assert sdk_codes == set(messages), "SDK codes of the policy this SDK raises"

    def test_retry_policy_matches() -> None:
        assert set(NON_RETRYABLE_CODES) == set(cast(list[str], POLICY["nonRetryableCodes"]))
        assert POLICY["retryAfterClampMs"] == RETRY_AFTER_CAP_SECONDS * 1000

    def _params() -> list[Any]:
        params: list[Any] = []
        for case in SDK_CASES:
            for flavor in ("sync", "async"):
                marks: list[pytest.MarkDecorator] = []
                if not _runs(case):
                    marks.append(
                        pytest.mark.skip(reason=f"policy.cancellationSdks does not list {SDK_NAME}")
                    )
                params.append(pytest.param(case, flavor, id=f"{case['id']}-{flavor}", marks=marks))
        return params

    @pytest.mark.parametrize(("case", "flavor"), _params())
    def test_case(case: dict[str, Any], flavor: str, monkeypatch: pytest.MonkeyPatch) -> None:
        # The client reads these only for an omitted option, and a case sets every option:
        # an environment that defines them must not change the outcome.
        monkeypatch.setenv("POLI_PAGE_API_KEY", "pp_sandbox_ffffffffffffffffffffffffffffffff")
        monkeypatch.setenv("POLI_PAGE_BASE_URL", "http://127.0.0.1:9")
        reason = SKIP.get(case["id"])
        if reason is None:
            _run_case(case, flavor)
            return
        try:
            _run_case(case, flavor)
        except AssertionError:
            pytest.xfail(f"listed in tests/contract-skip.json: {reason}")
        pytest.fail(f"{case['id']} passes now: remove it from tests/contract-skip.json")
