"""Sync client (`PoliPage`) tests — constructor, retry loop, transport.

Ported from sdk-node/tests/index.test.ts. Retry-loop scenarios mock httpx via
respx; sleep is monkeypatched to a no-op so retry tests run in milliseconds.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from poli_page import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    PoliPage,
    PoliPageError,
    RateLimitError,
    RetryEvent,
)
from poli_page._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)

TEST_BASE_URL = "https://test.example"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable `time.sleep` for retry tests — they assert delays via spies."""
    monkeypatch.setattr("poli_page._client.time.sleep", lambda _s: None)


class TestConstructor:
    def test_raises_invalid_options_when_no_api_key_and_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("POLI_PAGE_API_KEY", raising=False)
        with pytest.raises(PoliPageError) as excinfo:
            PoliPage()
        assert excinfo.value.code == "invalid_options"
        assert excinfo.value.status is None

    def test_raises_invalid_options_on_empty_string_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("POLI_PAGE_API_KEY", raising=False)
        with pytest.raises(PoliPageError) as excinfo:
            PoliPage(api_key="")
        assert excinfo.value.code == "invalid_options"

    def test_accepts_explicit_api_key(self) -> None:
        client = PoliPage(api_key="pp_test_abc")
        assert isinstance(client, PoliPage)
        client.close()

    def test_picks_up_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_API_KEY", "pp_test_from_env")
        client = PoliPage()
        assert isinstance(client, PoliPage)
        client.close()

    def test_picks_up_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_BASE_URL", "https://custom.example")
        client = PoliPage(api_key="pp_test_abc")
        assert client.base_url == "https://custom.example"
        client.close()

    def test_default_base_url_when_no_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLI_PAGE_BASE_URL", raising=False)
        client = PoliPage(api_key="pp_test_abc")
        assert client.base_url == DEFAULT_BASE_URL
        client.close()

    def test_default_retry_options_match_constants(self) -> None:
        client = PoliPage(api_key="pp_test_abc")
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.retry_delay == DEFAULT_RETRY_DELAY_SECONDS
        assert client.timeout == DEFAULT_TIMEOUT_SECONDS
        client.close()

    def test_custom_retry_options_accepted(self) -> None:
        client = PoliPage(
            api_key="pp_test_abc",
            max_retries=5,
            retry_delay=1.0,
            timeout=10.0,
        )
        assert client.max_retries == 5
        assert client.retry_delay == 1.0
        assert client.timeout == 10.0
        client.close()

    def test_explicit_api_key_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_API_KEY", "from_env")
        client = PoliPage(api_key="explicit")
        assert client._api_key == "explicit"
        client.close()

    def test_context_manager_closes_owned_http_client(self) -> None:
        with PoliPage(api_key="pp_test_abc") as client:
            assert isinstance(client, PoliPage)
        # http_client is closed; further requests would fail. Don't try
        # making one — just trust httpx's close().

    def test_inject_custom_http_client_is_not_closed_by_sdk(self) -> None:
        external = httpx.Client()
        client = PoliPage(api_key="pp_test_abc", http_client=external)
        client.close()
        # External client survives client.close() — that's the contract.
        assert not external.is_closed
        external.close()


class TestRepr:
    """API key must never leak through repr() — protects logs, REPL output,
    framework debug pages (Django/Flask), and pytest assertion diffs.
    """

    def test_repr_does_not_leak_api_key(self) -> None:
        secret = "pp_test_super_secret_value_do_not_leak_42"
        client = PoliPage(api_key=secret, base_url=TEST_BASE_URL)
        rendered = repr(client)
        assert secret not in rendered
        # The full key suffix must not appear either.
        assert "super_secret" not in rendered
        client.close()

    def test_repr_shows_masked_prefix(self) -> None:
        client = PoliPage(api_key="pp_test_super_secret_value", base_url=TEST_BASE_URL)
        rendered = repr(client)
        assert "PoliPage" in rendered
        # Some recognizable prefix is fine; the bulk must be masked.
        assert "***" in rendered
        client.close()

    def test_repr_includes_base_url(self) -> None:
        client = PoliPage(api_key="pp_test_abc", base_url="https://api.example/v9")
        rendered = repr(client)
        assert "https://api.example/v9" in rendered
        client.close()

    def test_repr_handles_short_api_key(self) -> None:
        # Should not IndexError on keys shorter than the visible-prefix length.
        client = PoliPage(api_key="x", base_url=TEST_BASE_URL)
        rendered = repr(client)
        assert "x" not in rendered or "***" in rendered
        client.close()


class TestWithOptions:
    """Anthropic-style branching: `client.with_options(timeout=...)` returns
    a NEW client with overrides applied and everything else inherited.
    """

    def test_returns_new_instance(self) -> None:
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        branched = client.with_options(timeout=99.0)
        assert branched is not client
        assert isinstance(branched, PoliPage)
        client.close()
        branched.close()

    def test_overrides_apply(self) -> None:
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            timeout=10.0,
            max_retries=2,
        )
        branched = client.with_options(timeout=99.0, max_retries=7)
        assert branched.timeout == 99.0
        assert branched.max_retries == 7
        client.close()
        branched.close()

    def test_unspecified_options_inherited(self) -> None:
        client = PoliPage(
            api_key="pp_test_inherited",
            base_url="https://api.example/v9",
            timeout=12.5,
            max_retries=4,
            retry_delay=2.5,
        )
        branched = client.with_options(timeout=99.0)
        assert branched.base_url == "https://api.example/v9"
        assert branched.max_retries == 4
        assert branched.retry_delay == 2.5
        client.close()
        branched.close()

    def test_does_not_mutate_original(self) -> None:
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            timeout=10.0,
            max_retries=2,
        )
        client.with_options(timeout=99.0, max_retries=7)
        assert client.timeout == 10.0
        assert client.max_retries == 2
        client.close()

    def test_owns_its_own_http_client(self) -> None:
        # Branched client must not share the parent's http_client — closing
        # one would otherwise close the other.
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        branched = client.with_options(timeout=99.0)
        assert branched._http_client is not client._http_client
        client.close()
        assert not branched._http_client.is_closed
        branched.close()


class TestPreviewHappyPath:
    @respx.mock
    def test_posts_to_render_preview(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "<p>x</p>", "totalPages": 1, "environment": "sandbox"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        result = client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.called
        assert result.html == "<p>x</p>"
        assert result.total_pages == 1
        assert result.environment == "sandbox"

    @respx.mock
    def test_accepts_inline_mode(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "<h1>x</h1>", "totalPages": 1, "environment": "sandbox"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<h1>inline</h1>", "data": {}})
        sent = route.calls.last.request.read().decode()
        assert '"template":"<h1>inline</h1>"' in sent.replace(" ", "")

    @respx.mock
    def test_accepts_project_mode(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "", "totalPages": 1, "environment": "sandbox"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview(
            {
                "project": "billing",
                "template": "invoice",
                "version": "1.0.0",
                "data": {"amount": 100},
            }
        )
        import json

        body = json.loads(route.calls.last.request.read())
        assert body["project"] == "billing"
        assert body["template"] == "invoice"
        assert body["version"] == "1.0.0"
        assert body["data"] == {"amount": 100}

    @respx.mock
    def test_forwards_metadata(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "", "totalPages": 1, "environment": "sandbox"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview(
            {"template": "<p>x</p>", "data": {}, "metadata": {"customer_id": "cust_1"}}
        )
        import json

        body = json.loads(route.calls.last.request.read())
        assert body["metadata"] == {"customer_id": "cust_1"}

    @respx.mock
    def test_strips_idempotency_key_and_timeout_from_body(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "", "totalPages": 1, "environment": "sandbox"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview(
            {
                "template": "<p>x</p>",
                "data": {},
                "idempotency_key": "caller-set-key",
                "timeout": 5.0,
            }
        )
        import json

        body = json.loads(route.calls.last.request.read())
        assert "idempotencyKey" not in body
        assert "idempotency_key" not in body
        assert "timeout" not in body
        # The header carries the caller-set key.
        assert route.calls.last.request.headers["Idempotency-Key"] == "caller-set-key"


class TestRequestHeaders:
    @respx.mock
    def test_sends_bearer_authorization(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(api_key="pp_test_xyz", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.calls.last.request.headers["Authorization"] == "Bearer pp_test_xyz"

    @respx.mock
    def test_sends_user_agent_with_sdk_version(self) -> None:
        from poli_page._version import __version__

        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<p>x</p>", "data": {}})
        ua = route.calls.last.request.headers["User-Agent"]
        assert ua == f"poli-page-sdk-python/{__version__}"

    @respx.mock
    def test_sends_accept_application_json(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.calls.last.request.headers["Accept"] == "application/json"

    @respx.mock
    def test_sends_content_type_application_json(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.calls.last.request.headers["Content-Type"] == "application/json"

    @respx.mock
    def test_auto_generates_idempotency_key_when_not_set(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)
        client.render.preview({"template": "<p>x</p>", "data": {}})
        idem = route.calls.last.request.headers["Idempotency-Key"]
        # UUID4 is 36 chars with 4 dashes (8-4-4-4-12).
        assert len(idem) == 36
        assert idem.count("-") == 4


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected_cls"),
        [
            (400, BadRequestError),
            (401, AuthenticationError),
            (403, PermissionDeniedError),
            (429, RateLimitError),
            (500, InternalServerError),
        ],
    )
    @respx.mock
    def test_raises_classified_subclass_for_status(
        self, status: int, expected_cls: type[PoliPageError]
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                status,
                json={"code": "SOMETHING", "message": "boom"},
                headers={"x-request-id": "req_xyz"},
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0)
        with pytest.raises(expected_cls) as excinfo:
            client.render.preview({"template": "<p>x</p>", "data": {}})
        err = excinfo.value
        assert isinstance(err, PoliPageError)
        assert err.status == status
        assert err.code == "SOMETHING"
        assert err.request_id == "req_xyz"

    @respx.mock
    def test_html_error_body_yields_internal_error(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                502, content="<html>upstream gone</html>", headers={"Content-Type": "text/html"}
            )
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0)
        with pytest.raises(InternalServerError) as excinfo:
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert excinfo.value.code == "INTERNAL_ERROR"
        assert excinfo.value.status == 502

    @respx.mock
    def test_network_error_classified_as_apiconnectionerror(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0)
        with pytest.raises(APIConnectionError) as excinfo:
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert excinfo.value.code == "network_error"

    @respx.mock
    def test_timeout_raises_apitimeouterror(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            side_effect=httpx.ReadTimeout("read timed out")
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0)
        with pytest.raises(APITimeoutError) as excinfo:
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert excinfo.value.code == "timeout"


class TestRetryLoop:
    @respx.mock
    def test_retries_5xx_then_succeeds(self) -> None:
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json={"html": "ok", "totalPages": 1, "environment": "sandbox"}),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        )
        result = client.render.preview({"template": "<p>x</p>", "data": {}})
        assert result.html == "ok"
        assert route.call_count == 3

    @respx.mock
    def test_does_not_retry_4xx(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(400, json={"code": "bad_request"})
        )
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        )
        with pytest.raises(BadRequestError):
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 1

    @respx.mock
    def test_retries_429(self) -> None:
        responses = [
            httpx.Response(429, json={"code": "rate_limited"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 2

    @respx.mock
    def test_retries_network_errors(self) -> None:
        responses: list[Any] = [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 2

    @respx.mock
    def test_exhausted_retries_raises_last_error(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        )
        with pytest.raises(InternalServerError):
            client.render.preview({"template": "<p>x</p>", "data": {}})
        # 1 initial + 2 retries = 3 calls.
        assert route.call_count == 3

    @respx.mock
    def test_retry_after_seconds_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("poli_page._client.time.sleep", lambda s: sleeps.append(s))
        responses = [
            httpx.Response(503, json={"code": "down"}, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        # Retry-After: 0 → immediate retry (sleep with 0.0).
        assert sleeps == [0.0]

    @respx.mock
    def test_retry_after_capped_at_30(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("poli_page._client.time.sleep", lambda s: sleeps.append(s))
        responses = [
            httpx.Response(503, json={"code": "down"}, headers={"Retry-After": "999"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert sleeps == [30.0]

    @respx.mock
    def test_retry_after_ms_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("poli_page._client.time.sleep", lambda s: sleeps.append(s))
        responses = [
            httpx.Response(
                503,
                json={"code": "down"},
                headers={"Retry-After": "5", "Retry-After-Ms": "250"},
            ),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=2, retry_delay=10.0
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        # 250 ms → 0.25 s, takes precedence over Retry-After: 5.
        assert sleeps == [0.25]

    @respx.mock
    def test_max_retries_zero_disables_retries(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        client = PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0)
        with pytest.raises(InternalServerError):
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 1


class TestHooks:
    @respx.mock
    def test_on_retry_fires_before_each_retry(self) -> None:
        events: list[RetryEvent] = []
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
            on_retry=events.append,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        # Two retries → two events.
        assert len(events) == 2
        assert events[0].attempt == 2  # 1-based, the attempt about to be made
        assert events[1].attempt == 3
        assert isinstance(events[0].reason, InternalServerError)

    @respx.mock
    def test_on_error_fires_once_on_terminal_failure(self) -> None:
        errors: list[PoliPageError] = []
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(400, json={"code": "bad"})
        )
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=0,
            on_error=errors.append,
        )
        with pytest.raises(BadRequestError):
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert len(errors) == 1
        assert errors[0].status == 400

    @respx.mock
    def test_hook_exception_does_not_break_request(self) -> None:
        def hostile_hook(_e: object) -> None:
            raise RuntimeError("hook raised")

        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "ok", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            on_retry=hostile_hook,
            on_error=hostile_hook,
        )
        # Should succeed even though hooks would raise (they're only fired
        # on retry/error paths and must be swallowed).
        result = client.render.preview({"template": "<p>x</p>", "data": {}})
        assert result.html == "ok"


    @respx.mock
    def test_on_request_fires_before_each_attempt(self) -> None:
        from poli_page import RequestEvent

        events: list[RequestEvent] = []
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
            on_request=events.append,
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        # Two attempts (initial + 1 retry).
        assert len(events) == 2
        assert events[0].method == "POST"
        assert events[0].url == f"{TEST_BASE_URL}/v1/render/preview"
        assert events[0].attempt == 1
        assert events[1].attempt == 2

    @respx.mock
    def test_on_request_hook_exception_does_not_break_request(self) -> None:
        def hostile(_e: object) -> None:
            raise RuntimeError("boom")

        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "ok", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, on_request=hostile
        )
        result = client.render.preview({"template": "<p>x</p>", "data": {}})
        assert result.html == "ok"


    @respx.mock
    def test_on_response_fires_on_success(self) -> None:
        from poli_page import ResponseEvent

        events: list[ResponseEvent] = []
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "", "totalPages": 1, "environment": "sandbox"},
                headers={"x-request-id": "req_xyz"},
            )
        )
        client = PoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, on_response=events.append
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert len(events) == 1
        assert events[0].status == 200
        assert events[0].request_id == "req_xyz"
        assert events[0].duration_ms >= 0.0  # non-negative wall-clock

    @respx.mock
    def test_on_response_not_fired_on_error_responses(self) -> None:
        from poli_page import ResponseEvent

        events: list[ResponseEvent] = []
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        client = PoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=0,
            on_response=events.append,
        )
        with pytest.raises(InternalServerError):
            client.render.preview({"template": "<p>x</p>", "data": {}})
        assert events == []

    @respx.mock
    def test_on_response_request_id_none_when_header_missing(self) -> None:
        from poli_page import ResponseEvent

        events: list[ResponseEvent] = []
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        client = PoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, on_response=events.append
        )
        client.render.preview({"template": "<p>x</p>", "data": {}})
        assert events[0].request_id is None


class TestEventDataclasses:
    """Per-attempt + per-retry event payloads exposed via constructor hooks."""

    def test_request_event_fields(self) -> None:
        from poli_page import RequestEvent

        ev = RequestEvent(method="POST", url="https://x/y", attempt=2)
        assert ev.method == "POST"
        assert ev.url == "https://x/y"
        assert ev.attempt == 2

    def test_request_event_is_frozen(self) -> None:
        from poli_page import RequestEvent

        ev = RequestEvent(method="GET", url="https://x", attempt=1)
        with pytest.raises((AttributeError, Exception)):
            ev.attempt = 99  # type: ignore[misc]

    def test_response_event_fields(self) -> None:
        from poli_page import ResponseEvent

        ev = ResponseEvent(status=200, request_id="req_abc", duration_ms=12.5)
        assert ev.status == 200
        assert ev.request_id == "req_abc"
        assert ev.duration_ms == 12.5

    def test_response_event_request_id_optional(self) -> None:
        from poli_page import ResponseEvent

        ev = ResponseEvent(status=204, request_id=None, duration_ms=1.0)
        assert ev.request_id is None

    def test_retry_event_uses_delay_ms_not_delay_seconds(self) -> None:
        from poli_page import RetryEvent

        err = PoliPageError("boom", code="INTERNAL_ERROR", status=500)
        ev = RetryEvent(attempt=2, delay_ms=250.0, reason=err)
        assert ev.delay_ms == 250.0
        # The old field name must be gone — fail loud if anyone still reads it.
        assert not hasattr(ev, "delay_seconds")
