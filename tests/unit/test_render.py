"""Unit tests for `render.document`, `render.pdf`, `render.pdf_stream`.

The render namespace's two-hop flow:
1. POST `/v1/render` → DocumentDescriptor wire response.
2. GET `presignedPdfUrl` → PDF bytes (no auth, no retry; S3).

Mocked via respx; lives in tests/unit/.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from poli_page import (
    DocumentDescriptor,
    InternalServerError,
    PoliPage,
    PoliPageError,
)

TEST_BASE_URL = "https://test.example"
PRESIGNED_URL = "https://presigned.example/x.pdf"

# Canonical wire-shape document descriptor (camelCase). The SDK converts
# this to snake_case via from_wire at parse time.
SAMPLE_RAW_DESCRIPTOR: dict[str, object] = {
    "documentId": "doc_default",
    "organizationId": "org_x",
    "projectId": "proj_p",
    "projectSlug": "p",
    "templateId": "tpl_t",
    "templateSlug": "t",
    "version": "1.0.0",
    "environment": "sandbox",
    "apiKeyId": "key_x",
    "format": "A4",
    "orientation": "portrait",
    "locale": "en-US",
    "pageCount": 1,
    "sizeBytes": 100,
    "createdAt": "2026-01-01T00:00:00Z",
    "metadata": {},
    "presignedPdfUrl": PRESIGNED_URL,
    "expiresAt": "2026-01-01T00:15:00Z",
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("poli_page._client.time.sleep", lambda _s: None)


@pytest.fixture
def client() -> PoliPage:
    return PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)


def _descriptor_response(overrides: dict[str, object] | None = None) -> httpx.Response:
    body = dict(SAMPLE_RAW_DESCRIPTOR)
    if overrides:
        body.update(overrides)
    return httpx.Response(200, json=body)


def _pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.4 stub content here", headers={"Content-Type": "application/pdf"}
    )


PROJECT_MODE_INPUT: dict[str, object] = {
    "project": "billing",
    "template": "invoice",
    "version": "1.0.0",
    "data": {"name": "Test"},
}


class TestRenderDocument:
    @respx.mock
    def test_posts_to_v1_render(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert route.called
        assert isinstance(doc, DocumentDescriptor)

    @respx.mock
    def test_descriptor_has_snake_cased_fields(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert doc.document_id == "doc_default"
        assert doc.organization_id == "org_x"
        assert doc.project_id == "proj_p"
        assert doc.project_slug == "p"
        assert doc.template_id == "tpl_t"
        assert doc.template_slug == "t"
        assert doc.version == "1.0.0"
        assert doc.environment == "sandbox"
        assert doc.api_key_id == "key_x"
        assert doc.format == "A4"
        assert doc.orientation == "portrait"
        assert doc.locale == "en-US"
        assert doc.page_count == 1
        assert doc.size_bytes == 100
        assert doc.created_at == "2026-01-01T00:00:00Z"
        assert doc.metadata == {}
        assert doc.presigned_pdf_url == PRESIGNED_URL
        assert doc.expires_at == "2026-01-01T00:15:00Z"

    @respx.mock
    def test_descriptor_metadata_echoed_verbatim(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=_descriptor_response(
                {"metadata": {"customer_id": "cust_1", "is_paid": True}}
            )
        )
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        # User-set keys reach the caller verbatim — from_wire must not transform them.
        assert doc.metadata == {"customer_id": "cust_1", "is_paid": True}

    @respx.mock
    def test_descriptor_repr_excludes_client_field(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        repr_str = repr(doc)
        # Private transport reference must not leak into repr().
        assert "PoliPage" not in repr_str
        assert "_client" not in repr_str

    @respx.mock
    def test_download_pdf_returns_bytes(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        pdf = doc.download_pdf()
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")

    @respx.mock
    def test_download_pdf_does_not_send_authorization(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        pdf_route = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        doc.download_pdf()
        # S3 presigned URLs auth via query string — sending Bearer would be wrong.
        assert "Authorization" not in pdf_route.calls.last.request.headers

    @respx.mock
    def test_download_pdf_non_2xx_raises_download_failed(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(403, content=b"Forbidden"))
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        with pytest.raises(PoliPageError) as excinfo:
            doc.download_pdf()
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status == 403

    @respx.mock
    def test_download_pdf_network_error_raises_download_failed(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=httpx.ConnectError("refused"))
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        with pytest.raises(PoliPageError) as excinfo:
            doc.download_pdf()
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status is None

    @respx.mock
    def test_inline_mode_input_rejected_locally(self, client: PoliPage) -> None:
        # No HTTP call should be made — validation happens client-side.
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.document({"template": "<p>x</p>", "data": {}})  # type: ignore[arg-type]
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert excinfo.value.status is None
        assert not route.called


class TestRenderPdf:
    @respx.mock
    def test_returns_bytes_from_two_hop_flow(self, client: PoliPage) -> None:
        render_route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=_descriptor_response()
        )
        pdf_route = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        pdf = client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert render_route.called
        assert pdf_route.called
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")

    @respx.mock
    def test_inline_mode_input_rejected_locally(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf({"template": "<p>x</p>", "data": {}})  # type: ignore[arg-type]
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert not route.called

    @respx.mock
    def test_render_api_error_propagates(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        with pytest.raises(InternalServerError):
            client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]


class TestRenderPdfStream:
    @respx.mock
    def test_yields_chunks(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        chunks: list[bytes] = []
        with client.render.pdf_stream(PROJECT_MODE_INPUT) as stream:  # type: ignore[arg-type]
            for chunk in stream:
                chunks.append(chunk)
        joined = b"".join(chunks)
        assert joined.startswith(b"%PDF")

    @respx.mock
    def test_inline_mode_input_rejected_locally(self, client: PoliPage) -> None:
        # Validation happens at pdf_stream() call time, before the CM is built.
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf_stream({"template": "<p>x</p>", "data": {}})  # type: ignore[arg-type]
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert not route.called

    @respx.mock
    def test_non_2xx_from_s3_raises_download_failed(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(404, content=b"missing"))
        with (
            pytest.raises(PoliPageError) as excinfo,
            client.render.pdf_stream(PROJECT_MODE_INPUT) as stream,  # type: ignore[arg-type]
        ):
            # Should fail on enter; this loop is unreachable.
            for _ in stream:
                pass
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status == 404

    @respx.mock
    def test_network_error_on_stream_raises_download_failed(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=httpx.ConnectError("refused"))
        with (
            pytest.raises(PoliPageError) as excinfo,
            client.render.pdf_stream(PROJECT_MODE_INPUT) as stream,  # type: ignore[arg-type]
        ):
            for _ in stream:
                pass
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status is None


class TestRequestBody:
    @respx.mock
    def test_render_document_sends_project_template_version_data(self, client: PoliPage) -> None:
        import json

        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        client.render.document(
            {
                "project": "billing",
                "template": "invoice",
                "version": "1.0.0",
                "data": {"amount": 100},
                "format": "A5",
                "orientation": "landscape",
            }  # type: ignore[arg-type]
        )
        body = json.loads(route.calls.last.request.read())
        assert body["project"] == "billing"
        assert body["template"] == "invoice"
        assert body["version"] == "1.0.0"
        assert body["data"] == {"amount": 100}
        assert body["format"] == "A5"
        assert body["orientation"] == "landscape"

    @respx.mock
    def test_idempotency_key_stripped_from_body_and_in_header(self, client: PoliPage) -> None:
        import json

        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        client.render.document(
            {**PROJECT_MODE_INPUT, "idempotency_key": "caller-key"}  # type: ignore[arg-type]
        )
        body = json.loads(route.calls.last.request.read())
        assert "idempotency_key" not in body
        assert "idempotencyKey" not in body
        assert route.calls.last.request.headers["Idempotency-Key"] == "caller-key"

    @respx.mock
    def test_render_document_forwards_metadata(self, client: PoliPage) -> None:
        import json

        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        client.render.document(
            {**PROJECT_MODE_INPUT, "metadata": {"order_id": "ord_42", "tier": "pro"}}  # type: ignore[arg-type]
        )
        body = json.loads(route.calls.last.request.read())
        assert body["metadata"] == {"order_id": "ord_42", "tier": "pro"}


class TestIdempotencyKeyAcrossRetries:
    """Spec §5.1: a single logical request keeps one idempotency-key for the
    entire retry lifecycle. Regenerating it would defeat server-side dedup.
    """

    @respx.mock
    def test_same_idempotency_key_reused_on_retry(self, client: PoliPage) -> None:
        responses = [
            httpx.Response(503, json={"code": "boom"}),
            _descriptor_response(),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert route.call_count == 2
        first = route.calls[0].request.headers["Idempotency-Key"]
        second = route.calls[1].request.headers["Idempotency-Key"]
        assert first == second
        assert first  # not empty

    @respx.mock
    def test_caller_supplied_key_reused_on_retry(self, client: PoliPage) -> None:
        responses = [
            httpx.Response(503, json={"code": "boom"}),
            _descriptor_response(),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        client.render.document(
            {**PROJECT_MODE_INPUT, "idempotency_key": "caller-key-7"}  # type: ignore[arg-type]
        )
        assert route.call_count == 2
        assert route.calls[0].request.headers["Idempotency-Key"] == "caller-key-7"
        assert route.calls[1].request.headers["Idempotency-Key"] == "caller-key-7"
