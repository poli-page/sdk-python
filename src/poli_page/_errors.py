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

from poli_page._constants import NON_RETRYABLE_CODES

if TYPE_CHECKING:
    import httpx


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
        """A network error, a timeout, a 5xx or a 429 the SDK retries (SDK spec §9.1).

        `QUOTA_EXCEEDED`, `OVERAGE_CAP_EXCEEDED` and `STORAGE_ACCESS_DENIED` are
        never retryable: waiting cannot fix them.
        """
        if self.code in NON_RETRYABLE_CODES:
            return False
        if self.is_network_error():
            return True
        return self.status is not None and (self.status >= 500 or self.status == 429)

    def to_payload(self) -> dict[str, Any]:
        """Canonical wire payload for framework integrations.

        Returns `{code, message, status, requestId}`. Keys are camelCase by
        design — this dict is wire format meant to be serialised as JSON and
        forwarded to a client (D2 / Plan 0). Python attributes (`request_id`)
        stay snake_case; only the payload surfaces camelCase.

        `status` is the HTTP status from the API for `APIStatusError`, 503 for
        `APIConnectionError`, 504 for `APITimeoutError`, and `None` for the
        bare base class.
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
