"""Async `documents.*` namespace tests — parallel to test_documents.py."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from poli_page import (
    AsyncDocumentDescriptor,
    AsyncPoliPage,
    DocumentPreviewResult,
    GoneError,
    NotFoundError,
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
    async def _noop(_s: float) -> None:
        return None

    monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _noop)


class TestDocumentsGet:
    @respx.mock
    async def test_gets_correct_path(self) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.documents.get("doc_abc123")
        assert route.called
        assert isinstance(doc, AsyncDocumentDescriptor)
        assert doc.document_id == "doc_abc123"

    @respx.mock
    async def test_url_encodes_special_chars(self) -> None:
        route = respx.get(f"{TEST_BASE_URL}/v1/documents/doc%2Fwith%2Fslashes").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            await client.documents.get("doc/with/slashes")
        assert route.called

    @respx.mock
    async def test_returned_descriptor_can_download_pdf(self) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)
        )
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 fresh"))
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.documents.get("doc_abc123")
            pdf = await doc.download_pdf()
        assert pdf.startswith(b"%PDF")

    @respx.mock
    async def test_404_raises_not_found(self) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/missing").mock(
            return_value=httpx.Response(404, json={"code": "DOCUMENT_NOT_FOUND"})
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(NotFoundError):
                await client.documents.get("missing")


class TestDocumentsPreview:
    @respx.mock
    async def test_returns_html_and_page_count(self) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>stored</p>",
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "X-Document-Page-Count": "4",
                },
            )
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            result = await client.documents.preview("doc_abc123")
        assert isinstance(result, DocumentPreviewResult)
        assert result.html == "<p>stored</p>"
        assert result.page_count == 4

    @respx.mock
    async def test_defaults_page_count_to_zero_when_missing(self) -> None:
        respx.get(f"{TEST_BASE_URL}/v1/documents/doc_abc123/preview").mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            result = await client.documents.preview("doc_abc123")
        assert result.page_count == 0


class TestDocumentsThumbnails:
    @respx.mock
    async def test_wraps_body_unwraps_response(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/documents/doc_abc123/thumbnails").mock(
            return_value=httpx.Response(200, json={"thumbnails": [SAMPLE_THUMBNAIL]})
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            thumbs = await client.documents.thumbnails(
                "doc_abc123", {"width": 840, "format": "png"}
            )
        body = json.loads(route.calls.last.request.read())
        assert body == {"thumbnails": {"width": 840, "format": "png"}}
        assert len(thumbs) == 1
        assert isinstance(thumbs[0], Thumbnail)
        assert thumbs[0].content_type == "image/png"


class TestDocumentsDelete:
    @respx.mock
    async def test_deletes_correct_path(self) -> None:
        route = respx.delete(f"{TEST_BASE_URL}/v1/documents/doc_abc123").mock(
            return_value=httpx.Response(204)
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            result = await client.documents.delete("doc_abc123")
        assert result is None
        assert route.called

    @respx.mock
    async def test_410_raises_gone_error(self) -> None:
        respx.delete(f"{TEST_BASE_URL}/v1/documents/already_gone").mock(
            return_value=httpx.Response(410, json={"code": "GONE"})
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(GoneError):
                await client.documents.delete("already_gone")
