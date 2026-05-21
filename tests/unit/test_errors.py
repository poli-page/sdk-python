"""Port of sdk-node/tests/error.test.ts, adapted to the Python error hierarchy.

The Node SDK ships a single `PoliPageError` and tests the predicates by
constructing it with varied `(code, status)` pairs. The Python SDK ships a
class hierarchy (plan §7), so the predicates are tested by instantiating each
subclass directly.
"""

from __future__ import annotations

import pytest

from poli_page import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    GoneError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    PoliPageError,
    RateLimitError,
    UnprocessableEntityError,
    error_codes,
)
from poli_page._errors import classify


class TestConstruction:
    def test_preserves_message_code_status_request_id(self) -> None:
        err = InternalServerError("boom", code="INTERNAL_ERROR", status=500, request_id="req_abc")
        assert err.message == "boom"
        assert str(err) == "boom"
        assert err.code == "INTERNAL_ERROR"
        assert err.status == 500
        assert err.request_id == "req_abc"
        assert err.response is None

    def test_is_exception_subclass(self) -> None:
        err = BadRequestError("bad", code="VALIDATION_ERROR", status=400)
        assert isinstance(err, Exception)
        assert isinstance(err, PoliPageError)
        assert isinstance(err, APIStatusError)

    def test_connection_error_has_no_status(self) -> None:
        err = APIConnectionError("net down", code="network_error")
        assert err.status is None
        assert err.request_id is None
        assert isinstance(err, PoliPageError)

    def test_timeout_is_connection_error_subclass(self) -> None:
        err = APITimeoutError("slow", code="timeout")
        assert isinstance(err, APIConnectionError)
        assert err.status is None


class TestIsAuthError:
    def test_true_for_401(self) -> None:
        assert AuthenticationError("m", code="INVALID_API_KEY", status=401).is_auth_error()

    def test_true_for_403(self) -> None:
        assert PermissionDeniedError("m", code="FORBIDDEN", status=403).is_auth_error()

    def test_false_for_404(self) -> None:
        assert NotFoundError("m", code="NOT_FOUND", status=404).is_auth_error() is False

    def test_false_for_network_error(self) -> None:
        assert APIConnectionError("m", code="network_error").is_auth_error() is False


class TestIsRateLimitError:
    def test_true_for_429(self) -> None:
        assert RateLimitError("m", code="QUOTA_EXCEEDED", status=429).is_rate_limit_error()

    def test_false_for_500(self) -> None:
        err = InternalServerError("m", code="INTERNAL_ERROR", status=500)
        assert err.is_rate_limit_error() is False


class TestIsValidationError:
    def test_true_for_400(self) -> None:
        assert BadRequestError("m", code="VALIDATION_ERROR", status=400).is_validation_error()

    def test_false_for_401(self) -> None:
        err = AuthenticationError("m", code="INVALID_API_KEY", status=401)
        assert err.is_validation_error() is False


class TestIsNetworkError:
    def test_true_for_network_error_code(self) -> None:
        assert APIConnectionError("m", code="network_error").is_network_error()

    def test_true_for_timeout(self) -> None:
        assert APITimeoutError("m", code="timeout").is_network_error()

    def test_false_for_internal_server_error(self) -> None:
        err = InternalServerError("m", code="INTERNAL_ERROR", status=500)
        assert err.is_network_error() is False


class TestIsRetryable:
    def test_true_for_5xx(self) -> None:
        assert InternalServerError("m", code="INTERNAL_ERROR", status=500).is_retryable()
        assert InternalServerError("m", code="INTERNAL_ERROR", status=502).is_retryable()

    def test_true_for_429(self) -> None:
        assert RateLimitError("m", code="QUOTA_EXCEEDED", status=429).is_retryable()

    def test_true_for_network_and_timeout(self) -> None:
        assert APIConnectionError("m", code="network_error").is_retryable()
        assert APITimeoutError("m", code="timeout").is_retryable()

    def test_false_for_validation_error(self) -> None:
        err = BadRequestError("m", code="VALIDATION_ERROR", status=400)
        assert err.is_retryable() is False

    def test_false_for_aborted_base_error(self) -> None:
        # `aborted` doesn't have its own subclass: it's a bare PoliPageError
        # raised from the async cancellation handler. Per spec, never retryable.
        err = PoliPageError("cancelled", code="aborted")
        assert err.is_retryable() is False


class TestClassify:
    @pytest.mark.parametrize(
        ("status", "expected_cls"),
        [
            (400, BadRequestError),
            (401, AuthenticationError),
            (403, PermissionDeniedError),
            (404, NotFoundError),
            (409, ConflictError),
            (410, GoneError),
            (422, UnprocessableEntityError),
            (429, RateLimitError),
            (500, InternalServerError),
            (502, InternalServerError),
            (503, InternalServerError),
            (504, InternalServerError),
        ],
    )
    def test_returns_correct_subclass_for_status(
        self, status: int, expected_cls: type[PoliPageError]
    ) -> None:
        err = classify(status=status, code="SOMETHING", message="msg", request_id=None)
        assert isinstance(err, expected_cls)
        assert err.status == status
        assert err.code == "SOMETHING"
        assert err.message == "msg"

    def test_falls_back_to_api_status_error_for_unmapped_4xx(self) -> None:
        # 418 isn't in the explicit map; should still classify as a status error.
        err = classify(status=418, code="IM_A_TEAPOT", message="msg", request_id="r")
        assert isinstance(err, APIStatusError)
        assert err.status == 418
        assert err.request_id == "r"


class TestErrorCodes:
    def test_known_api_codes_exposed(self) -> None:
        # spec §7.2 / plan §7.4 — pass-through codes the SDK ships as constants.
        assert error_codes.MISSING_API_KEY == "MISSING_API_KEY"
        assert error_codes.INVALID_API_KEY == "INVALID_API_KEY"
        assert error_codes.PAYMENT_REQUIRED == "PAYMENT_REQUIRED"
        assert error_codes.FORBIDDEN == "FORBIDDEN"
        assert error_codes.ORGANIZATION_CANCELLED == "ORGANIZATION_CANCELLED"
        assert error_codes.ORGANIZATION_PURGED == "ORGANIZATION_PURGED"
        assert error_codes.NOT_FOUND == "NOT_FOUND"
        assert error_codes.VERSION_NOT_FOUND == "VERSION_NOT_FOUND"
        assert error_codes.DOCUMENT_NOT_FOUND == "DOCUMENT_NOT_FOUND"
        assert error_codes.GONE == "GONE"
        assert error_codes.VALIDATION_ERROR == "VALIDATION_ERROR"
        assert error_codes.MISSING_DATA == "MISSING_DATA"
        assert error_codes.MISSING_PROJECT_OR_TEMPLATE == "MISSING_PROJECT_OR_TEMPLATE"
        assert error_codes.MISSING_TEMPLATE_SLUG == "MISSING_TEMPLATE_SLUG"
        assert error_codes.PROJECT_REQUIRED_FOR_DOCUMENT == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert error_codes.INVALID_VERSION_FORMAT == "INVALID_VERSION_FORMAT"
        assert error_codes.VERSION_REQUIRED == "VERSION_REQUIRED"
        assert error_codes.INVALID_VERSION_FOR_KEY_ENV == "INVALID_VERSION_FOR_KEY_ENV"
        assert error_codes.QUOTA_EXCEEDED == "QUOTA_EXCEEDED"
        assert error_codes.OVERAGE_CAP_EXCEEDED == "OVERAGE_CAP_EXCEEDED"
        assert error_codes.INTERNAL_ERROR == "INTERNAL_ERROR"

    def test_reserved_sdk_codes_exposed(self) -> None:
        # plan §7.2 — SDK-internal codes also live as constants.
        assert error_codes.INVALID_OPTIONS == "invalid_options"
        assert error_codes.NETWORK_ERROR == "network_error"
        assert error_codes.TIMEOUT == "timeout"
        assert error_codes.ABORTED == "aborted"
        assert error_codes.UNKNOWN_ERROR == "unknown_error"
        assert error_codes.DOWNLOAD_FAILED == "DOWNLOAD_FAILED"

    def test_storage_required_not_exposed(self) -> None:
        # plan §7.4 — STORAGE_REQUIRED was retired; do NOT ship as a constant.
        assert not hasattr(error_codes, "STORAGE_REQUIRED")
