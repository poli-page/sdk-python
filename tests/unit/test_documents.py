"""Unit tests for `client.documents.*` (port of sdk-node/tests/documents.test.ts).

Each method is exercised end-to-end through the PoliPage client (mocked via
respx). URL-encoding, body wrap/unwrap, and header parsing are the
points where the wire format and SDK shape diverge — these tests pin them.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from poli_page import (
    DocumentDescriptor,
    DocumentPreviewResult,
    GoneError,
    NotFoundError,
    PoliPage,
    Thumbnail,
)

TEST_BASE_URL = "https://test.example"
PRESIGNED_URL = "https://presigned.example/doc.pdf"

SAMPLE_RAW_DESCRIPTOR: dict[str, object] = {
    "documentId": "doc_abc123",
    "organizationId": "org_xyz",
    "projectId": "proj_42",
    "projectSlug": "billing",
    "templateId": "tpl_invoice_v1",
    "templateSlug": "invoice",
    "version": "1.0.0",
    "environment": "live",
    "apiKeyId": "key_live_abc",
    "format": "A4",
    "orientation": "portrait",
    "locale": "en-US",
    "pageCount": 2,
    "sizeBytes": 38421,
    "createdAt": "2026-04-30T19:45:22Z",
    "metadata": {},
    "presignedPdfUrl": PRESIGNED_URL,
    "expiresAt": "2026-04-30T20:00:22Z",
}

SAMPLE_THUMBNAIL: dict[str, object] = {
    "page": 1,
    "width": 840,
    "height": 1188,
    "contentType": "image/png",
    "data": "iVBORw0KGgoAAAANSU=",
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("poli_page._client.time.sleep", lambda _s: None)


@pytest.fixture
def client() -> PoliPage:
    return PoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL)


class TestDocumentsGet:
    @respx.mock
    def test_gets_correct_path(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        doc = client.documents.get("doc_abc123")
        assert route.called
        assert route.calls.last.request.method == "GET"
        assert isinstance(doc, DocumentDescriptor)
        assert doc.document_id == "doc_abc123"
        assert doc.template_slug == "invoice"

    @respx.mock
    def test_url_encodes_special_chars(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc%2Fwith%2Fslashes").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        client.documents.get("doc/with/slashes")
        assert route.called

    @respx.mock
    def test_sends_no_body(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        client.documents.get("doc_abc123")
        assert route.calls.last.request.content == b""

    @respx.mock
    def test_sends_no_idempotency_key(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        client.documents.get("doc_abc123")
        # GETs are idempotent by HTTP semantics — no Idempotency-Key needed.
        assert "Idempotency-Key" not in route.calls.last.request.headers

    @respx.mock
    def test_returned_descriptor_can_download_pdf(self, client: PoliPage) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 fresh"))
        doc = client.documents.get("doc_abc123")
        pdf = doc.download_pdf()
        assert pdf.startswith(b"%PDF")

    @respx.mock
    def test_404_raises_not_found_error(self, client: PoliPage) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/missing").mock(
            return_value=httpx.Response(404, json={"code": "DOCUMENT_NOT_FOUND"})
        )
        with pytest.raises(NotFoundError) as excinfo:
            client.documents.get("missing")
        assert excinfo.value.code == "DOCUMENT_NOT_FOUND"
        assert excinfo.value.status == 404

    @respx.mock
    def test_410_raises_gone_error(self, client: PoliPage) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/deleted").mock(
            return_value=httpx.Response(410, json={"code": "GONE"})
        )
        with pytest.raises(GoneError) as excinfo:
            client.documents.get("deleted")
        assert excinfo.value.status == 410


class TestDocumentsPreview:
    @respx.mock
    def test_returns_html_and_page_count(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>stored preview</p>",
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "X-Document-Page-Count": "4",
                },
            )
        )
        result = client.documents.preview("doc_abc123")
        assert route.called
        assert isinstance(result, DocumentPreviewResult)
        assert result.html == "<p>stored preview</p>"
        assert result.page_count == 4

    @respx.mock
    def test_defaults_page_count_to_zero_when_header_missing(self, client: PoliPage) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        )
        result = client.documents.preview("doc_abc123")
        assert result.page_count == 0

    @respx.mock
    def test_defaults_page_count_to_zero_when_header_unparseable(self, client: PoliPage) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "X-Document-Page-Count": "not a number",
                },
            )
        )
        result = client.documents.preview("doc_abc123")
        assert result.page_count == 0

    @respx.mock
    def test_url_encodes_special_chars(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc%2Fwith%2Fslashes/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "X-Document-Page-Count": "1",
                },
            )
        )
        client.documents.preview("doc/with/slashes")
        assert route.called

    @respx.mock
    def test_sends_no_body(self, client: PoliPage) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "X-Document-Page-Count": "1",
                },
            )
        )
        client.documents.preview("doc_abc123")
        assert route.calls.last.request.content == b""


class TestDocumentsThumbnails:
    @respx.mock
    def test_posts_with_options_wrapped(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/documents/doc_abc123/thumbnails").mock(
            return_value=httpx.Response(200, json={"thumbnails": [SAMPLE_THUMBNAIL]})
        )
        client.documents.thumbnails("doc_abc123", {"width": 840, "format": "png"})
        assert route.calls.last.request.method == "POST"
        body = json.loads(route.calls.last.request.read())
        assert body == {"thumbnails": {"width": 840, "format": "png"}}

    @respx.mock
    def test_forwards_all_options_inside_wrap(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/documents/doc_abc123/thumbnails").mock(
            return_value=httpx.Response(200, json={"thumbnails": []})
        )
        client.documents.thumbnails(
            "doc_abc123",
            {"width": 320, "format": "jpeg", "quality": 85, "pages": [1, 2, 3]},
        )
        body = json.loads(route.calls.last.request.read())
        assert body["thumbnails"] == {
            "width": 320,
            "format": "jpeg",
            "quality": 85,
            "pages": [1, 2, 3],
        }

    @respx.mock
    def test_unwraps_response_and_returns_list(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/documents/doc_abc123/thumbnails").mock(
            return_value=httpx.Response(
                200,
                json={"thumbnails": [SAMPLE_THUMBNAIL, {**SAMPLE_THUMBNAIL, "page": 2}]},
            )
        )
        thumbs = client.documents.thumbnails("doc_abc123", {"width": 840})
        assert len(thumbs) == 2
        assert isinstance(thumbs[0], Thumbnail)
        assert thumbs[0].page == 1
        assert thumbs[1].page == 2
        assert thumbs[0].content_type == "image/png"  # camelCase → snake_case
        assert thumbs[0].data == "iVBORw0KGgoAAAANSU="
        assert thumbs[0].width == 840
        assert thumbs[0].height == 1188

    @respx.mock
    def test_url_encodes_special_chars(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/documents/doc%2Fwith%2Fslashes/thumbnails").mock(
            return_value=httpx.Response(200, json={"thumbnails": []})
        )
        client.documents.thumbnails("doc/with/slashes", {"width": 100})
        assert route.called

    @respx.mock
    def test_sets_idempotency_key_header(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/documents/doc_abc123/thumbnails").mock(
            return_value=httpx.Response(200, json={"thumbnails": []})
        )
        client.documents.thumbnails("doc_abc123", {"width": 100})
        # POST is state-mutating: auto-generated UUID4 idempotency key.
        idem = route.calls.last.request.headers["Idempotency-Key"]
        assert len(idem) == 36


class TestDocumentsDelete:
    @respx.mock
    def test_deletes_correct_path(self, client: PoliPage) -> None:
        route = respx.delete(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(204)
        )
        client.documents.delete("doc_abc123")
        assert route.called
        assert route.calls.last.request.method == "DELETE"

    @respx.mock
    def test_returns_none(self, client: PoliPage) -> None:
        respx.delete(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(204)
        )
        result = client.documents.delete("doc_abc123")
        assert result is None

    @respx.mock
    def test_sends_no_body(self, client: PoliPage) -> None:
        route = respx.delete(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(204)
        )
        client.documents.delete("doc_abc123")
        assert route.calls.last.request.content == b""

    @respx.mock
    def test_url_encodes_special_chars(self, client: PoliPage) -> None:
        route = respx.delete(f"{TEST_BASE_URL}/v1/documents/doc%2Fwith%2Fslashes").mock(
            return_value=httpx.Response(204)
        )
        client.documents.delete("doc/with/slashes")
        assert route.called

    @respx.mock
    def test_410_on_redelete_raises_gone_error(self, client: PoliPage) -> None:
        respx.delete(f"{TEST_BASE_URL}/v1/documents/already_gone").mock(
            return_value=httpx.Response(410, json={"code": "GONE"})
        )
        with pytest.raises(GoneError):
            client.documents.delete("already_gone")
