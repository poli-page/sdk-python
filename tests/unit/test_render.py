"""Unit tests for `render.document`, `render.pdf`, `render.pdf_stream`.

The render namespace's two-hop flow:
1. POST `/v1/render` → DocumentDescriptor wire response.
2. GET `presignedPdfUrl` → PDF bytes (no auth, no retry; S3).

Mocked via respx; lives in tests/unit/.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import assert_type

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
    monkeypatch.setattr("poli_page._client.sleep_at_least", lambda _s: None)


@pytest.fixture
def client() -> PoliPage:
    return PoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL)


def _descriptor_response(overrides: dict[str, object] | None = None) -> httpx.Response:
    body = dict(SAMPLE_RAW_DESCRIPTOR)
    if overrides:
        body.update(overrides)
    return httpx.Response(200, json=body)


def _pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.4 stub content here", headers={"Content-Type": "application/pdf"}
    )


class _DroppedBody(httpx.SyncByteStream):
    """A PDF body whose connection drops after the first chunk."""

    def __iter__(self) -> Iterator[bytes]:
        yield b"%PDF-1.4 partial"
        raise httpx.RemoteProtocolError("peer closed connection without sending complete body")


def _dropped_pdf_response() -> httpx.Response:
    return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=_DroppedBody())


PROJECT_MODE_INPUT: dict[str, object] = {
    "project": "billing",
    "template": "invoice",
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
    def test_descriptor_environment_is_any_name_the_api_returns(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=_descriptor_response({"environment": "staging"})
        )
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert_type(doc.environment, str)
        assert doc.environment == "staging"

    def test_descriptor_has_no_version_field(self) -> None:
        from dataclasses import fields

        assert "version" not in {f.name for f in fields(DocumentDescriptor)}

    @respx.mock
    def test_descriptor_ignores_a_version_key_on_the_wire(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=_descriptor_response({"version": "1.0.0"})
        )
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        assert not hasattr(doc, "version")

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
        assert excinfo.value.message == "Failed to download PDF: HTTP 403"

    @respx.mock
    def test_download_pdf_network_error_raises_download_failed(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=httpx.ConnectError("refused"))
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        with pytest.raises(PoliPageError) as excinfo:
            doc.download_pdf()
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.status is None
        assert excinfo.value.message == "Failed to download PDF: network error"
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)

    @respx.mock
    def test_missing_project_rejected_locally(self, client: PoliPage) -> None:
        # No HTTP call should be made — validation happens client-side.
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.document({"template": "invoice", "data": {}})  # type: ignore[arg-type]
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"
        assert excinfo.value.message == "project is required"
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
    def test_missing_project_rejected_locally(self, client: PoliPage) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf({"template": "invoice", "data": {}})  # type: ignore[arg-type]
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
    def test_missing_project_rejected_locally(self, client: PoliPage) -> None:
        # Validation happens at pdf_stream() call time, before the CM is built.
        route = respx.post(f"{TEST_BASE_URL}/v1/render")
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf_stream({"template": "invoice", "data": {}})  # type: ignore[arg-type]
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
        assert excinfo.value.message == "Failed to download PDF: HTTP 404"

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
        assert excinfo.value.message == "Failed to download PDF: network error"
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


class TestRequestBody:
    @respx.mock
    def test_render_document_sends_project_template_data(self, client: PoliPage) -> None:
        import json

        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        client.render.document(
            {
                "project": "billing",
                "template": "invoice",
                "data": {"amount": 100},
                "format": "A5",
                "orientation": "landscape",
            }  # type: ignore[arg-type]
        )
        body = json.loads(route.calls.last.request.read())
        assert body["project"] == "billing"
        assert body["template"] == "invoice"
        assert "version" not in body
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


class TestPublicSurface:
    """Versions, the authenticated preview and inline HTML are gone from the API."""

    def test_render_has_no_preview(self, client: PoliPage) -> None:
        assert not hasattr(client.render, "preview")

    def test_async_render_has_no_preview(self) -> None:
        from poli_page import AsyncPoliPage

        assert not hasattr(AsyncPoliPage(api_key="pp_sandbox_abc").render, "preview")

    def test_documents_preview_stays(self, client: PoliPage) -> None:
        assert callable(client.documents.preview)

    @pytest.mark.parametrize("name", ["PreviewResult", "InlineModeInput", "ProjectModeInput"])
    def test_removed_types_not_exported(self, name: str) -> None:
        import poli_page
        import poli_page.types

        assert not hasattr(poli_page, name)
        assert not hasattr(poli_page.types, name)
        assert name not in poli_page.__all__

    def test_render_input_is_exported(self) -> None:
        import poli_page

        assert "RenderInput" in poli_page.__all__
        keys = poli_page.RenderInput.__required_keys__ | poli_page.RenderInput.__optional_keys__
        assert keys == {
            "project",
            "template",
            "data",
            "metadata",
            "format",
            "orientation",
            "locale",
            "idempotency_key",
            "timeout",
        }

    def test_render_preview_path_removed(self) -> None:
        from poli_page import _constants

        assert not hasattr(_constants, "PATH_RENDER_PREVIEW")


class TestDownloadDroppedMidBody:
    """A connection dropped while the PDF body is read is DOWNLOAD_FAILED, never raw httpx."""

    def _assert_network_download_failed(self, err: PoliPageError) -> None:
        assert err.code == "DOWNLOAD_FAILED"
        assert err.status is None
        assert err.message == "Failed to download PDF: network error"
        assert isinstance(err.__cause__, httpx.RemoteProtocolError)

    @respx.mock
    def test_render_pdf(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        self._assert_network_download_failed(excinfo.value)

    @respx.mock
    def test_download_pdf(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        doc = client.render.document(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
        with pytest.raises(PoliPageError) as excinfo:
            doc.download_pdf()
        self._assert_network_download_failed(excinfo.value)

    @respx.mock
    def test_render_pdf_stream(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        chunks: list[bytes] = []
        with (
            pytest.raises(PoliPageError) as excinfo,
            client.render.pdf_stream(PROJECT_MODE_INPUT) as stream,  # type: ignore[arg-type]
        ):
            for chunk in stream:
                chunks.append(chunk)
        assert chunks == [b"%PDF-1.4 partial"]
        self._assert_network_download_failed(excinfo.value)


class TestDownloadTimeoutValue:
    """The download gets the API attempt's timeout value, handed to httpx as it is.

    A value of 0 or less adds no deadline of the SDK's own: httpx decides what it means, as
    for an API attempt (the mocked transport here applies none, so the download succeeds).
    """

    @staticmethod
    def _download_timeout(route: respx.Route) -> object:
        return route.calls[-1].request.extensions["timeout"]

    @pytest.mark.parametrize("timeout", [0, -1, 7])
    @respx.mock
    def test_sync(self, timeout: float) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        pdf = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, timeout=timeout)
        expected = {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}

        assert client.render.pdf(PROJECT_MODE_INPUT).startswith(b"%PDF")  # type: ignore[arg-type]
        assert self._download_timeout(pdf) == expected
        with client.render.pdf_stream(PROJECT_MODE_INPUT) as chunks:  # type: ignore[arg-type]
            assert b"".join(chunks).startswith(b"%PDF")
        assert self._download_timeout(pdf) == expected

    @pytest.mark.parametrize("timeout", [0, -1, 7])
    @respx.mock
    async def test_async(self, timeout: float) -> None:
        from poli_page import AsyncPoliPage

        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        pdf = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        expected = {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, timeout=timeout
        ) as client:
            assert (await client.render.pdf(PROJECT_MODE_INPUT)).startswith(b"%PDF")  # type: ignore[arg-type]
            assert self._download_timeout(pdf) == expected
            async with client.render.pdf_stream(PROJECT_MODE_INPUT) as chunks:  # type: ignore[arg-type]
                assert b"".join([c async for c in chunks]).startswith(b"%PDF")
            assert self._download_timeout(pdf) == expected

    @respx.mock
    def test_an_injected_http_client_gets_the_client_timeout(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        pdf = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            timeout=3,
            http_client=httpx.Client(timeout=None),
        )
        client.render.document(PROJECT_MODE_INPUT).download_pdf()  # type: ignore[arg-type]
        assert self._download_timeout(pdf) == {"connect": 3, "read": 3, "write": 3, "pool": 3}


class TestStreamEdges:
    """An empty body, a failure before any byte, and a TimeoutError the deadline did not raise."""

    @respx.mock
    def test_sync_empty_body_streams_nothing(self, client: PoliPage) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, content=b""))
        with client.render.pdf_stream(PROJECT_MODE_INPUT) as chunks:  # type: ignore[arg-type]
            assert list(chunks) == []

    @respx.mock
    async def test_async_empty_body_streams_nothing(self) -> None:
        from poli_page import AsyncPoliPage

        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, content=b""))
        async with (
            AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client,
            client.render.pdf_stream(PROJECT_MODE_INPUT) as chunks,  # type: ignore[arg-type]
        ):
            received = [chunk async for chunk in chunks]
        assert received == []

    @respx.mock
    async def test_async_stream_network_error_before_any_byte(self) -> None:
        from poli_page import AsyncPoliPage

        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=httpx.ConnectError("refused"))
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                async with client.render.pdf_stream(PROJECT_MODE_INPUT):  # type: ignore[arg-type]
                    pass
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert excinfo.value.message == "Failed to download PDF: network error"
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)

    @pytest.mark.parametrize("method", ["render.pdf", "render.pdf_stream"])
    @respx.mock
    async def test_async_timeout_error_not_from_the_deadline_is_not_labelled_timeout(
        self, method: str
    ) -> None:
        # Only the SDK's own deadline (or an httpx timeout) is `Failed to download PDF: timeout`:
        # a TimeoutError raised by the transport itself passes through unchanged.
        from poli_page import AsyncPoliPage

        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(side_effect=TimeoutError("from the transport"))
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(TimeoutError, match="from the transport"):
                if method == "render.pdf":
                    await client.render.pdf(PROJECT_MODE_INPUT)  # type: ignore[arg-type]
                else:
                    async with client.render.pdf_stream(PROJECT_MODE_INPUT):  # type: ignore[arg-type]
                        pass


class TestAbandonedSyncWorker:
    """A sync download whose caller gave up stops at its next step: before the request, after
    the headers, or after a chunk, so it releases its connection as early as httpx allows."""

    @staticmethod
    def _client(abandoned: threading.Event | None = None) -> httpx.Client:
        # The response hook runs once the headers are in, before any body read.
        hooks = {"response": [lambda _response: abandoned.set()]} if abandoned else {}
        return httpx.Client(event_hooks=hooks)

    @respx.mock
    def test_read_all_sends_nothing_once_abandoned(self) -> None:
        from poli_page._download import _read_all

        route = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        abandoned = threading.Event()
        abandoned.set()
        assert _read_all(self._client(), PRESIGNED_URL, 5, abandoned) == b""
        assert route.call_count == 0

    @respx.mock
    def test_read_all_reads_no_body_when_abandoned_during_the_headers(self) -> None:
        from poli_page._download import _read_all

        body = _CountingBody()
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, stream=body))
        abandoned = threading.Event()
        assert _read_all(self._client(abandoned), PRESIGNED_URL, 5, abandoned) == b""
        assert body.reads == 0
        assert body.closed

    @respx.mock
    def test_read_all_stops_after_the_chunk_during_which_it_was_abandoned(self) -> None:
        from poli_page._download import _read_all

        abandoned = threading.Event()

        class _AbandonedMidBody(httpx.SyncByteStream):
            def __init__(self) -> None:
                self.reads = 0

            def __iter__(self) -> Iterator[bytes]:
                for chunk in (b"first", b"second", b"third"):
                    self.reads += 1
                    yield chunk
                    abandoned.set()  # the caller gives up while this chunk is read

        body = _AbandonedMidBody()
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, stream=body))
        assert _read_all(self._client(), PRESIGNED_URL, 5, abandoned) == b"first"
        assert body.reads == 2  # the next chunk arrived, then the read stopped

    @respx.mock
    def test_start_stream_sends_nothing_once_abandoned(self) -> None:
        from poli_page._download import _DeadlineExpired, _start_stream

        route = respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        abandoned = threading.Event()
        abandoned.set()
        client = self._client()
        with pytest.raises(_DeadlineExpired):
            _start_stream(client, client.build_request("GET", PRESIGNED_URL), abandoned)
        assert route.call_count == 0

    @respx.mock
    def test_start_stream_closes_the_response_when_abandoned_during_the_headers(self) -> None:
        from poli_page._download import _DeadlineExpired, _start_stream

        body = _CountingBody()
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, stream=body))
        abandoned = threading.Event()
        client = self._client(abandoned)
        with pytest.raises(_DeadlineExpired):
            _start_stream(client, client.build_request("GET", PRESIGNED_URL), abandoned)
        assert body.reads == 0
        assert body.closed


class _CountingBody(httpx.SyncByteStream):
    """A PDF body that counts how many chunks were read and whether it was closed."""

    def __init__(self) -> None:
        self.reads = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        self.reads += 1
        yield b"%PDF-1.4 body"

    def close(self) -> None:
        self.closed = True
