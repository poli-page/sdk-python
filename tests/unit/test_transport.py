"""Port of sdk-node/tests/internal/http.test.ts to Python.

The Node SDK works in milliseconds; the Python port works in seconds (plan
§6). Numeric expectations are scaled accordingly: '5' → 5.0 s, cap → 30.0 s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from poli_page._constants import (
    RETRY_AFTER_CAP_SECONDS,
)
from poli_page._transport import (
    build_headers,
    build_url,
    compute_backoff,
    from_wire,
    parse_error_body,
    parse_retry_after,
    to_wire,
)


def _http_date(dt: datetime) -> str:
    return format_datetime(dt, usegmt=True)


class TestParseRetryAfter:
    def test_none_returns_none(self) -> None:
        assert parse_retry_after(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_retry_after("") is None

    def test_zero_returns_zero(self) -> None:
        assert parse_retry_after("0") == 0.0

    def test_five_seconds(self) -> None:
        assert parse_retry_after("5") == 5.0

    def test_caps_large_second_values_at_30(self) -> None:
        assert parse_retry_after("999") == RETRY_AFTER_CAP_SECONDS
        assert parse_retry_after("100000") == RETRY_AFTER_CAP_SECONDS

    def test_non_numeric_non_date_returns_none(self) -> None:
        assert parse_retry_after("abc") is None
        assert parse_retry_after("not a date") is None

    def test_past_http_date_returns_zero(self) -> None:
        past = datetime.now(UTC) - timedelta(seconds=60)
        assert parse_retry_after(_http_date(past)) == 0.0

    def test_future_http_date_returns_delta_seconds(self) -> None:
        future = datetime.now(UTC) + timedelta(seconds=5)
        result = parse_retry_after(_http_date(future))
        assert result is not None
        # Allow a wide window: header date has 1s precision and the test
        # spent some time between datetime.now() inside parse_retry_after
        # and our outer comparison.
        assert 3.0 < result <= 5.0

    def test_far_future_http_date_is_capped(self) -> None:
        far_future = datetime.now(UTC) + timedelta(hours=1)
        assert parse_retry_after(_http_date(far_future)) == RETRY_AFTER_CAP_SECONDS


class TestComputeBackoff:
    def test_returns_retry_after_as_is_when_defined(self) -> None:
        assert compute_backoff(attempt=1, base_delay=0.5, retry_after=1.0) == 1.0
        assert compute_backoff(attempt=3, base_delay=0.5, retry_after=0.25) == 0.25

    def test_zero_retry_after_is_treated_as_defined(self) -> None:
        # Falsy zero must not trigger backoff math — server explicitly said 0.
        assert compute_backoff(attempt=1, base_delay=0.5, retry_after=0.0) == 0.0

    def test_exponential_backoff_with_min_jitter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # random.random() → 0.0 means jitterFactor = 0.5 (the floor).
        monkeypatch.setattr("poli_page._transport.random.random", lambda: 0.0)
        assert compute_backoff(attempt=1, base_delay=0.5, retry_after=None) == 0.25
        assert compute_backoff(attempt=2, base_delay=0.5, retry_after=None) == 0.5
        assert compute_backoff(attempt=3, base_delay=0.5, retry_after=None) == 1.0

    def test_exponential_backoff_with_near_max_jitter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # random.random() → 0.999 means jitterFactor ≈ 1.499.
        monkeypatch.setattr("poli_page._transport.random.random", lambda: 0.999)
        result = compute_backoff(attempt=1, base_delay=0.5, retry_after=None)
        # 0.5 * 1 * 1.499 = 0.7495
        assert 0.74 <= result <= 0.76

    def test_jitter_stays_within_half_to_one_and_a_half_x(self) -> None:
        # Port of http.test.ts:83-93 — 200 real samples, all within [0.5x, 1.5x).
        for _ in range(200):
            d = compute_backoff(attempt=1, base_delay=1.0, retry_after=None)
            assert 0.5 <= d < 1.5

    def test_random_not_called_when_retry_after_defined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[None] = []

        def fake_random() -> float:
            calls.append(None)
            return 0.0

        monkeypatch.setattr("poli_page._transport.random.random", fake_random)
        compute_backoff(attempt=2, base_delay=0.5, retry_after=1.0)
        assert calls == []


class TestParseErrorBody:
    def test_complete_body_with_code_and_message(self) -> None:
        result = parse_error_body(
            '{"code":"VALIDATION_ERROR","message":"data is required"}', status=400
        )
        assert result == {"code": "VALIDATION_ERROR", "message": "data is required"}

    def test_code_stays_unknown_when_only_message_present(self) -> None:
        result = parse_error_body('{"message":"something broke"}', status=400)
        assert result == {"code": "unknown_error", "message": "something broke"}

    def test_falls_back_to_error_field_as_code(self) -> None:
        result = parse_error_body('{"error":"oops"}', status=400)
        assert result == {"code": "oops", "message": "HTTP 400"}

    def test_unknown_error_when_json_has_no_recognised_fields(self) -> None:
        result = parse_error_body("{}", status=400)
        assert result == {"code": "unknown_error", "message": "HTTP 400"}

    def test_internal_error_when_body_not_valid_json(self) -> None:
        result = parse_error_body("not json", status=502)
        assert result == {
            "code": "INTERNAL_ERROR",
            "message": "HTTP 502: response body was not valid JSON",
        }

    def test_internal_error_for_html_error_pages(self) -> None:
        result = parse_error_body("<html>upstream gone</html>", status=502)
        assert result["code"] == "INTERNAL_ERROR"
        assert "502" in result["message"]

    def test_internal_error_for_empty_body(self) -> None:
        result = parse_error_body("", status=500)
        assert result["code"] == "INTERNAL_ERROR"

    def test_uses_rfc7807_detail_as_message(self) -> None:
        result = parse_error_body(
            '{"code":"authentication_failed","detail":"Forbidden","title":"Authentication failed"}',
            status=401,
        )
        assert result == {"code": "authentication_failed", "message": "Forbidden"}

    def test_falls_back_to_title_when_detail_absent(self) -> None:
        result = parse_error_body('{"code":"forbidden","title":"Access denied"}', status=403)
        assert result == {"code": "forbidden", "message": "Access denied"}

    def test_falls_back_to_legacy_message_field(self) -> None:
        result = parse_error_body('{"code":"X","message":"something broke"}', status=400)
        assert result == {"code": "X", "message": "something broke"}

    def test_no_synthesised_api_error_prefix(self) -> None:
        result = parse_error_body('{"code":"THUMBNAILS_NOT_AVAILABLE"}', status=403)
        assert result == {"code": "THUMBNAILS_NOT_AVAILABLE", "message": "HTTP 403"}
        assert "API error" not in result["message"]

    def test_code_never_inferred_from_message(self) -> None:
        result = parse_error_body('{"message":"something broke"}', status=400)
        assert result == {"code": "unknown_error", "message": "something broke"}


class TestBuildHeaders:
    UA = "poli-page-sdk-python/1.0.0"

    def test_post_sets_accept_json(self) -> None:
        h = build_headers("POST", api_key="pp_test_x", idempotency_key="i", user_agent=self.UA)
        assert h["Accept"] == "application/json"

    def test_post_sets_content_type_json(self) -> None:
        h = build_headers("POST", api_key="pp_test_x", idempotency_key="i", user_agent=self.UA)
        assert h["Content-Type"] == "application/json"

    def test_sets_authorization_with_bearer_prefix(self) -> None:
        h = build_headers("POST", api_key="pp_test_xyz", idempotency_key="i", user_agent=self.UA)
        assert h["Authorization"] == "Bearer pp_test_xyz"

    def test_sets_user_agent_verbatim(self) -> None:
        h = build_headers(
            "POST", api_key="pp_test_x", idempotency_key="i", user_agent="custom-ua/9.9.9"
        )
        assert h["User-Agent"] == "custom-ua/9.9.9"

    def test_sets_idempotency_key_header_from_arg(self) -> None:
        h = build_headers(
            "POST", api_key="pp_test_x", idempotency_key="idem-abc-123", user_agent=self.UA
        )
        assert h["Idempotency-Key"] == "idem-abc-123"

    def test_get_omits_content_type_and_idempotency_key(self) -> None:
        h = build_headers("GET", api_key="pp_test_x", idempotency_key=None, user_agent=self.UA)
        assert "Content-Type" not in h
        assert "Idempotency-Key" not in h
        assert h["Authorization"] == "Bearer pp_test_x"
        assert h["User-Agent"] == self.UA
        assert h["Accept"] == "application/json"

    def test_delete_omits_content_type_and_idempotency_key(self) -> None:
        h = build_headers("DELETE", api_key="pp_test_x", idempotency_key=None, user_agent=self.UA)
        assert "Content-Type" not in h
        assert "Idempotency-Key" not in h
        assert h["Authorization"] == "Bearer pp_test_x"

    def test_post_without_idempotency_key_omits_header(self) -> None:
        # The retry loop may omit the key for non-state-mutating POSTs (none today,
        # but the transport must support it). Mirrors Node's `if (idempotencyKey)` guard.
        h = build_headers("POST", api_key="pp_test_x", idempotency_key=None, user_agent=self.UA)
        assert "Idempotency-Key" not in h
        assert h["Content-Type"] == "application/json"


class TestBuildUrl:
    def test_joins_base_and_path(self) -> None:
        assert build_url("https://api.poli.page", "/v1/render") == "https://api.poli.page/v1/render"

    def test_trims_trailing_slash_on_base(self) -> None:
        assert (
            build_url("https://api.poli.page/", "/v1/render") == "https://api.poli.page/v1/render"
        )

    def test_adds_slash_when_path_lacks_leading_slash(self) -> None:
        assert build_url("https://api.poli.page", "v1/render") == "https://api.poli.page/v1/render"

    def test_preserves_base_url_path_prefix(self) -> None:
        # Proxy / mounting under a sub-path.
        assert (
            build_url("https://gateway.example/api", "/v1/render")
            == "https://gateway.example/api/v1/render"
        )

    def test_double_slash_is_collapsed(self) -> None:
        assert (
            build_url("https://api.poli.page/", "/v1/render") == "https://api.poli.page/v1/render"
        )


class TestToWire:
    def test_strips_idempotency_key(self) -> None:
        body = to_wire({"project": "p", "template": "t", "data": {}, "idempotency_key": "abc"})
        assert "idempotency_key" not in body
        assert "idempotencyKey" not in body
        assert body == {"project": "p", "template": "t", "data": {}}

    def test_strips_timeout(self) -> None:
        body = to_wire({"project": "p", "template": "t", "data": {}, "timeout": 30.0})
        assert "timeout" not in body
        assert body == {"project": "p", "template": "t", "data": {}}

    def test_converts_snake_case_to_camel_case_at_top_level(self) -> None:
        body = to_wire({"page_count": 3, "presigned_pdf_url": "https://x"})
        assert body == {"pageCount": 3, "presignedPdfUrl": "https://x"}

    def test_does_not_recurse_into_user_data_dict(self) -> None:
        # User template data is freeform — its keys must reach the renderer verbatim,
        # snake_case and all.
        body = to_wire({"project": "p", "template": "t", "data": {"first_name": "Ada"}})
        assert body == {"project": "p", "template": "t", "data": {"first_name": "Ada"}}

    def test_does_not_recurse_into_metadata(self) -> None:
        body = to_wire({"metadata": {"order_id": "o_1", "is_paid": True}})
        assert body == {"metadata": {"order_id": "o_1", "is_paid": True}}

    def test_input_dict_is_not_mutated(self) -> None:
        original = {"project": "p", "template": "t", "data": {}, "idempotency_key": "abc"}
        snapshot = dict(original)
        to_wire(original)
        assert original == snapshot

    def test_empty_dict_returns_empty(self) -> None:
        assert to_wire({}) == {}


class TestFromWire:
    def test_converts_camel_case_to_snake_case(self) -> None:
        result = from_wire({"documentId": "doc_1", "presignedPdfUrl": "https://x", "pageCount": 3})
        assert result == {
            "document_id": "doc_1",
            "presigned_pdf_url": "https://x",
            "page_count": 3,
        }

    def test_does_not_recurse_into_metadata(self) -> None:
        # Metadata keys are user-defined and reach us verbatim.
        result = from_wire({"metadata": {"OrderId": "o_1", "is_paid": True}})
        assert result == {"metadata": {"OrderId": "o_1", "is_paid": True}}

    def test_passes_through_already_snake_case_keys(self) -> None:
        result = from_wire({"project": "p", "version": "1.0.0"})
        assert result == {"project": "p", "version": "1.0.0"}

    def test_empty_dict_returns_empty(self) -> None:
        assert from_wire({}) == {}

    def test_handles_acronym_runs(self) -> None:
        # Defensive: today no wire field hits this, but if the API later returns
        # e.g. `apiKeyID`, the converter must not produce `api_key_i_d`.
        # We accept `api_key_id` as the canonical output for `apiKeyId`.
        assert from_wire({"apiKeyId": "ak_1"}) == {"api_key_id": "ak_1"}
