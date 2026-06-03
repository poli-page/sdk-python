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

    # Predicate helpers (plan §7.1) — kept for spec parity. Idiomatic
    # Python uses `isinstance(err, RateLimitError)` etc.

    def is_auth_error(self) -> bool:
        return isinstance(self, (AuthenticationError, PermissionDeniedError))

    def is_rate_limit_error(self) -> bool:
        return isinstance(self, RateLimitError)

    def is_validation_error(self) -> bool:
        return isinstance(self, BadRequestError)

    def is_network_error(self) -> bool:
        return isinstance(self, APIConnectionError)

    def is_retryable(self) -> bool:
        return isinstance(self, (APIConnectionError, RateLimitError, InternalServerError))

    def to_payload(self) -> dict[str, Any]:
        """Canonical wire payload for framework integrations.

        Returns `{code, message, status, request_id}`. `status` is the HTTP
        status from the API for `APIStatusError`, 503 for `APIConnectionError`,
        504 for `APITimeoutError`, and `None` for the bare base class. The
        attribute `.status` stays unchanged for transport errors — only the
        payload surfaces 503/504, so existing callers inspecting `.status`
        are not affected.
        """
        return {
            "code": self.code,
            "message": self.message,
            "status": self._payload_status(),
            "request_id": self.request_id,
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
    """HTTP 429 — quota or overage cap exceeded."""


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
