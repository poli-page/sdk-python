"""Error hierarchy for the Poli Page SDK (plan §7).

Modeled on anthropic-sdk-python / openai-python / stripe-python: a base
exception with the SDK-wide fields, two transport-level branches
(`APIConnectionError` and its `APITimeoutError` subclass), and one HTTP-status
branch (`APIStatusError`) with per-status subclasses.

The base `PoliPageError` is kept as the catch-all for spec parity — callers
that don't care about granularity can still write `except PoliPageError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from poli_page._constants import (
    HEADER_REQUEST_ID,
    MESSAGE_INVALID_RESPONSE,
    NON_RETRYABLE_CODES,
)

if TYPE_CHECKING:
    import httpx

# SDK codes, not API answer codes: kept out of `NON_RETRYABLE_CODES`, which mirrors the
# contract's `policy.nonRetryableCodes`. Waiting cannot fix any of them: a failed download
# needs a fresh presigned URL, a 2xx that is not JSON comes from something between the SDK
# and the API that answers the same way again, and a file that cannot be written stays so.
_NEVER_RETRYABLE_SDK_CODES = frozenset({"DOWNLOAD_FAILED", "invalid_response", "io_error"})


class PoliPageError(Exception):
    """Base class for every error raised by the SDK.

    Catches API errors, network failures, timeouts, caller cancellation, and
    constructor validation. Subclasses encode the kind of failure so callers
    can write `except RateLimitError` (idiomatic) or `except PoliPageError`
    (catch-all).
    """

    code: str
    status: int | None
    message: str
    request_id: str | None
    response: httpx.Response | None

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int | None = None,
        request_id: str | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id
        self.response = response

    # Predicate helpers (SDK spec §8.1), the same in every Poli Page SDK. They
    # read `status` and `code`, so they also hold for an error that is not one
    # of the HTTP-status subclasses (a `DOWNLOAD_FAILED` with the storage's 403
    # is an auth error). Idiomatic Python can use `isinstance(err, RateLimitError)`.

    def is_auth_error(self) -> bool:
        """`status` is 401 or 403."""
        return self.status in (401, 403)

    def is_rate_limit_error(self) -> bool:
        """`status` is 429."""
        return self.status == 429

    def is_validation_error(self) -> bool:
        """`status` is 400."""
        return self.status == 400

    def is_network_error(self) -> bool:
        """`code` is `network_error` or `timeout`."""
        return self.code in ("network_error", "timeout")

    def is_retryable(self) -> bool:
        """A network error, a timeout, a 5xx or a 429 the SDK retries.

        `QUOTA_EXCEEDED`, `OVERAGE_CAP_EXCEEDED` and `STORAGE_ACCESS_DENIED` are
        never retryable: waiting cannot fix them. Neither are `DOWNLOAD_FAILED`,
        whatever the storage status, `invalid_response` and `io_error`.
        """
        if self.code in NON_RETRYABLE_CODES or self.code in _NEVER_RETRYABLE_SDK_CODES:
            return False
        if self.is_network_error():
            return True
        return self.status is not None and (self.status >= 500 or self.status == 429)

    def to_payload(self) -> dict[str, Any]:
        """Canonical wire payload for framework integrations.

        Returns exactly the keys `code`, `message`, `status` and `requestId`, spelled
        so in every Poli Page SDK: the dict is the HTTP body an integration answers
        with. Python attributes (`request_id`) stay snake_case; only the payload
        uses `requestId`.

        `status` is the API status, 503 for `network_error` (`APIConnectionError`),
        504 for `timeout` (`APITimeoutError`) and 502 for `invalid_response`
        (`InvalidResponseError`), whose own `status` stays the real 2xx; `None` when
        unknown. It never changes the error's own `status` attribute.
        """
        return {
            "code": self.code,
            "message": self.message,
            "status": self._payload_status(),
            "requestId": self.request_id,
        }

    def _payload_status(self) -> int | None:
        return self.status


class APIConnectionError(PoliPageError):
    """Transport-layer failure: DNS, connection refused, TLS, etc.

    Carries no HTTP status (`status is None`).
    """

    def _payload_status(self) -> int | None:
        return 503


class APITimeoutError(APIConnectionError):
    """Per-request deadline exceeded."""

    def _payload_status(self) -> int | None:
        return 504


class InvalidResponseError(PoliPageError):
    """A 2xx answer whose body is not JSON, from a method that expects JSON.

    Code `invalid_response`, message `Invalid response: HTTP <status> body is not JSON`.
    `status` is the real 2xx and `request_id` the answer's `x-request-id`. Such a body
    usually comes from a proxy or a captive portal between the SDK and the API. Never
    retried; the JSON decoding error is the `__cause__`.
    """

    def _payload_status(self) -> int | None:
        # An integration must not answer an error with the 2xx it got.
        return 502


class APIStatusError(PoliPageError):
    """Base for any non-2xx response from the API. Always carries a `status`."""


class BadRequestError(APIStatusError):
    """HTTP 400 — request payload failed validation."""


class AuthenticationError(APIStatusError):
    """HTTP 401 — missing or invalid API key."""


class PermissionDeniedError(APIStatusError):
    """HTTP 403 — authenticated but not allowed."""


class NotFoundError(APIStatusError):
    """HTTP 404 — resource does not exist."""


class ConflictError(APIStatusError):
    """HTTP 409 — request conflicts with current state."""


class GoneError(APIStatusError):
    """HTTP 410 — resource permanently removed."""


class UnprocessableEntityError(APIStatusError):
    """HTTP 422 — request was understood but cannot be processed."""


class RateLimitError(APIStatusError):
    """HTTP 429 — rate limit, quota or overage cap exceeded.

    `RATE_LIMIT_EXCEEDED` is retried; `QUOTA_EXCEEDED` and `OVERAGE_CAP_EXCEEDED`
    are not (`is_retryable()` is `False` for them).
    """


class InternalServerError(APIStatusError):
    """HTTP 5xx — server-side failure."""


_STATUS_MAP: dict[int, type[APIStatusError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    410: GoneError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def classify(
    *,
    status: int,
    code: str,
    message: str,
    request_id: str | None,
    response: httpx.Response | None = None,
) -> APIStatusError:
    """Pick the most specific `APIStatusError` subclass for the given status.

    5xx → `InternalServerError`. Unmapped 4xx → bare `APIStatusError` (so the
    SDK does not silently swallow new status codes the API might introduce).
    """
    cls: type[APIStatusError] = (
        InternalServerError if status >= 500 else _STATUS_MAP.get(status, APIStatusError)
    )
    return cls(
        message,
        code=code,
        status=status,
        request_id=request_id,
        response=response,
    )


def invalid_response_error(response: httpx.Response) -> InvalidResponseError:
    """The `invalid_response` error for a 2xx `response` whose body is not JSON."""
    return InvalidResponseError(
        MESSAGE_INVALID_RESPONSE.format(status=response.status_code),
        code="invalid_response",
        status=response.status_code,
        request_id=response.headers.get(HEADER_REQUEST_ID),
        response=response,
    )
