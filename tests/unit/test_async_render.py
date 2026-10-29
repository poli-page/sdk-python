"""Async `render.*` namespace tests — parallel to test_render.py."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from poli_page import (
    AsyncDocumentDescriptor,
    AsyncPoliPage,
    InternalServerError,
    PoliPageError,
)

TEST_BASE_URL = "https://test.example"
PRESIGNED_URL = "https://presigned.example/x.pdf"

SAMPLE_RAW_DESCRIPTOR: dict[str, object] = {
    "documentId": "doc_default",
    "organizationId": "org_x",
    "projectId": "proj_p",
    "projectSlug": "p",
    "templateId": "tpl_t",
    "templateSlug": "t",
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

PROJECT_MODE_INPUT: dict[str, object] = {
    "project": "billing",
    "template": "invoice",
    "data": {"name": "Test"},
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_s: float) -> None:
        return None

    monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _noop)


def _descriptor_response() -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)


def _pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.4 stub content", headers={"Content-Type": "application/pdf"}
    )


class _DroppedBody(httpx.AsyncByteStream):
    """A PDF body whose connection drops after the first chunk."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"%PDF-1.4 partial"
        raise httpx.RemoteProtocolError("peer closed connection without sending complete body")


def _dropped_pdf_response() -> httpx.Response:
    return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=_DroppedBody())


class TestRenderDocument:
    @respx.mock
    async def test_returns_async_descriptor(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert isinstance(doc, AsyncDocumentDescriptor)
        assert doc.document_id == "doc_default"

    @respx.mock
    async def test_download_pdf_returns_bytes(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
            pdf = await doc.download_pdf()
        assert pdf.startswith(b"%PDF")

    @respx.mock
    async def test_download_pdf_non_2xx_raises_download_failed(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(403, content=b"Forbidden"))
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
            with pytest.raises(PoliPageError) as excinfo:
                await doc.download_pdf()
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status == 403
        assert excinfo.value.message == "Failed to download PDF: HTTP 403"

    @respx.mock
    async def test_download_pdf_network_error_raises_download_failed(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=httpx.ConnectError("refused"))
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            doc = await client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
            with pytest.raises(PoliPageError) as excinfo:
                await doc.download_pdf()
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status is None
        assert excinfo.value.message == "Failed to download PDF: network error"
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)

    @respx.mock
    async def test_missing_project_rejected_locally(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await client.render.document(
                    {"template": "invoice", "data": {}}  # type: ignore[arg-type]
                )
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert not route.called


class TestRenderPdf:
    @respx.mock
    async def test_two_hop_flow(self) -> None:
        render_route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=_descriptor_response()
        )
        pdf_route = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            pdf = await client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert render_route.called
        assert pdf_route.called
        assert pdf.startswith(b"%PDF")

    @respx.mock
    async def test_missing_project_rejected_locally(self) -> None:
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await client.render.pdf(
                    {"template": "invoice", "data": {}}  # type: ignore[arg-type]
                )
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"

    @respx.mock
    async def test_propagates_render_api_error(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(InternalServerError):
                await client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]


class TestRenderPdfStream:
    @respx.mock
    async def test_yields_chunks(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        chunks: list[bytes] = []
        async with (
            AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client,
            client.render.pdf_stream(PROJECT_MODE_INPUT) as stream,  # type: ignore[arg-type]
        ):
            async for chunk in stream:
                chunks.append(chunk)
        joined = b"".join(chunks)
        assert joined.startswith(b"%PDF")

    @respx.mock
    async def test_missing_project_rejected_at_enter(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            cm = client.render.pdf_stream(
                {"template": "invoice", "data": {}}  # type: ignore[arg-type]
            )
            with pytest.raises(PoliPageError) as excinfo:
                async with cm:
                    pytest.fail("Should not reach the body")
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert not route.called

    @respx.mock
    async def test_non_2xx_from_s3_raises_download_failed(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(404, content=b"missing"))
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                async with client.render.pdf_stream(PROJECT_MODE_INPUT) as stream:  # type: ignore[arg-type]
                    async for _ in stream:
                        pass
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status == 404
        assert excinfo.value.message == "Failed to download PDF: HTTP 404"


class TestIdempotencyKeyAcrossRetries:
    """Spec §5.1: same idempotency-key reused across the retry lifecycle."""

    @respx.mock
    async def test_same_idempotency_key_reused_on_retry(self) -> None:
        responses = [
            httpx.Response(503, json={"code": "boom"}),
            _descriptor_response(),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            await client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert route.call_count == 2
        first = route.calls[0].request.headers["Idempotency-Key"]
        second = route.calls[1].request.headers["Idempotency-Key"]
        assert first == second
        assert first


class TestDownloadDroppedMidBody:
    """A connection dropped while the PDF body is read is DOWNLOAD_FAILED, never raw httpx."""

    def _assert_network_download_failed(self, err: PoliPageError) -> None:
        assert err.code == "DOWNLOAD_FAILED"
        assert err.status is None
        assert err.message == "Failed to download PDF: network error"
        assert isinstance(err.__cause__, httpx.RemoteProtocolError)

    @respx.mock
    async def test_render_pdf(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        self._assert_network_download_failed(excinfo.value)

    @respx.mock
    async def test_render_pdf_stream(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        chunks: list[bytes] = []
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                async with client.render.pdf_stream(PROJECT_MODE_INPUT) as stream:  # type: ignore[arg-type]
                    async for chunk in stream:
                        chunks.append(chunk)
        assert chunks == [b"%PDF-1.4 partial"]
        self._assert_network_download_failed(excinfo.value)
