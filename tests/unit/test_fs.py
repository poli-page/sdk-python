"""Unit tests for the `render_to_file` helpers — sync + async.

Port of sdk-node/tests/node.test.ts.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import respx

from poli_page import AsyncPoliPage, PoliPage
from poli_page.fs import async_render_to_file, render_to_file

TEST_BASE_URL = "https://test.example"
PRESIGNED_URL = "https://presigned.example/x.pdf"

SAMPLE_RAW_DESCRIPTOR: dict[str, object] = {
    "documentId": "doc_fs",
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

PROJECT_MODE_INPUT: dict[str, object] = {
    "project": "p",
    "template": "t",
    "version": "1.0.0",
    "data": {},
}


def _descriptor_response() -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)


def _pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.4 stream test", headers={"Content-Type": "application/pdf"}
    )


class TestRenderToFileSync:
    @respx.mock
    def test_writes_pdf_with_magic_bytes(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL)
        out = tmp_path / "a.pdf"
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        content = out.read_bytes()
        assert content[:4] == b"%PDF"
        assert len(content) > 0

    @respx.mock
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL)
        out = tmp_path / "nested" / "deeply" / "b.pdf"
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.is_file()

    @respx.mock
    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL)
        out = tmp_path / "c.pdf"
        out.write_bytes(b"stale junk that should be replaced")
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.read_bytes().startswith(b"%PDF")

    @respx.mock
    def test_accepts_str_path(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL)
        out = str(tmp_path / "d.pdf")
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert os.path.isfile(out)

    @respx.mock
    def test_rejects_inline_mode(self, tmp_path: Path) -> None:
        # The underlying pdf_stream raises PROJECT_REQUIRED_FOR_DOCUMENT;
        # render_to_file lets it surface.
        from poli_page import PoliPageError

        client = PoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(
                client,
                {"template": "<p>x</p>", "data": {}},  # type: ignore[arg-type]
                tmp_path / "e.pdf",
            )
        assert excinfo.value.code == "PROJECT_REQUIRED_FOR_DOCUMENT"


class TestPackageRootReExport:
    """fs.py helpers must be importable from the package root for discoverability."""

    def test_render_to_file_importable_from_package_root(self) -> None:
        # Symbol must be the SAME function object as the one in poli_page.fs.
        import poli_page
        import poli_page.fs

        assert hasattr(poli_page, "render_to_file")
        assert poli_page.render_to_file is poli_page.fs.render_to_file

    def test_async_render_to_file_importable_from_package_root(self) -> None:
        import poli_page
        import poli_page.fs

        assert hasattr(poli_page, "async_render_to_file")
        assert poli_page.async_render_to_file is poli_page.fs.async_render_to_file

    def test_helpers_in_dunder_all(self) -> None:
        import poli_page

        assert "render_to_file" in poli_page.__all__
        assert "async_render_to_file" in poli_page.__all__


class TestAsyncRenderToFile:
    @respx.mock
    async def test_writes_pdf_with_magic_bytes(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "a.pdf"
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        content = out.read_bytes()
        assert content[:4] == b"%PDF"

    @respx.mock
    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "nested" / "deeply" / "b.pdf"
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.is_file()

    @respx.mock
    async def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_test_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "c.pdf"
            out.write_bytes(b"stale junk")
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.read_bytes().startswith(b"%PDF")
