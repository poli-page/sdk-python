"""Unit tests for the `render_to_file` helpers — sync + async.

Port of sdk-node/tests/node.test.ts.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import httpx
import pytest
import respx

import poli_page.fs
from poli_page import AsyncPoliPage, PoliPage, PoliPageError
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
    "data": {},
}


def _descriptor_response() -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_RAW_DESCRIPTOR)


def _pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.4 stream test", headers={"Content-Type": "application/pdf"}
    )


class _DroppedBody(httpx.SyncByteStream):
    """A PDF body whose connection drops after the first chunk."""

    def __iter__(self) -> Iterator[bytes]:
        yield b"%PDF-1.4 partial"
        raise httpx.RemoteProtocolError("peer closed connection without sending complete body")


def _dropped_pdf_response() -> httpx.Response:
    return httpx.Response(200, stream=_DroppedBody(), headers={"Content-Type": "application/pdf"})


class TestRenderToFileSync:
    @respx.mock
    def test_writes_pdf_with_magic_bytes(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        out = tmp_path / "a.pdf"
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        content = out.read_bytes()
        assert content[:4] == b"%PDF"
        assert len(content) > 0

    @respx.mock
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        out = tmp_path / "nested" / "deeply" / "b.pdf"
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.is_file()

    @respx.mock
    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        out = tmp_path / "c.pdf"
        out.write_bytes(b"stale junk that should be replaced")
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.read_bytes().startswith(b"%PDF")

    @respx.mock
    def test_accepts_str_path(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        out = str(tmp_path / "d.pdf")
        render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert os.path.isfile(out)

    @respx.mock
    def test_rejects_input_without_project(self, tmp_path: Path) -> None:
        # render_to_file raises PROJECT_REQUIRED_FOR_DOCUMENT before touching the disk.
        from poli_page import PoliPageError

        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(
                client,
                {"template": "invoice", "data": {}},  # type: ignore[arg-type]
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
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "a.pdf"
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        content = out.read_bytes()
        assert content[:4] == b"%PDF"

    @respx.mock
    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "nested" / "deeply" / "b.pdf"
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.is_file()

    @respx.mock
    async def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            out = tmp_path / "c.pdf"
            out.write_bytes(b"stale junk")
            await async_render_to_file(client, PROJECT_MODE_INPUT, out)  # type: ignore[arg-type]
        assert out.read_bytes().startswith(b"%PDF")


def _assert_io_error(err: PoliPageError) -> None:
    assert err.code == "io_error"
    assert err.status is None
    assert isinstance(err.__cause__, OSError)
    assert err.message == f"Failed to write PDF: {err.__cause__}"
    assert err.is_retryable() is False


class _FullDisk:
    """The temporary file, as a disk that is full: every write raises `error`."""

    def __init__(self, file: BinaryIO, error: OSError) -> None:
        self._file = file
        self._error = error

    def write(self, _chunk: bytes) -> int:
        raise self._error

    def close(self) -> None:
        self._file.close()


def _fail_writes(monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    real_open_part = poli_page.fs._open_part

    def open_part(target: Path) -> tuple[Path, object]:
        part, file = real_open_part(target)
        return part, _FullDisk(file, error)

    monkeypatch.setattr(poli_page.fs, "_open_part", open_part)


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".part"))


class TestRenderToFileFailures:
    """The target is replaced only by a complete PDF; a file that cannot be written is io_error."""

    @respx.mock
    def test_parent_that_is_a_file_is_io_error_before_any_render(self, tmp_path: Path) -> None:
        render = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        (tmp_path / "blocker").write_bytes(b"a file, not a directory")
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, tmp_path / "blocker" / "a.pdf")  # type: ignore[arg-type]
        _assert_io_error(excinfo.value)
        assert render.call_count == 0

    @respx.mock
    def test_target_that_is_a_directory_is_io_error_and_kept(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        target = tmp_path / "out.pdf"
        target.mkdir()
        (target / "keep").write_bytes(b"x")
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_io_error(excinfo.value)
        assert (target / "keep").read_bytes() == b"x"
        assert _leftovers(tmp_path) == []

    @respx.mock
    def test_write_failure_is_io_error_and_keeps_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        disk_full = OSError(28, "No space left on device")
        _fail_writes(monkeypatch, disk_full)
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_io_error(excinfo.value)
        assert excinfo.value.__cause__ is disk_full
        assert excinfo.value.message == "Failed to write PDF: [Errno 28] No space left on device"
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @respx.mock
    def test_failed_download_keeps_an_existing_target(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_dropped_pdf_response())
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @respx.mock
    def test_failed_render_creates_no_target(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(404, json={"error": "TEMPLATE_NOT_FOUND"})
        )
        target = tmp_path / "c.pdf"
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        assert excinfo.value.code == "TEMPLATE_NOT_FOUND"
        assert not target.exists()
        assert _leftovers(tmp_path) == []

    def test_missing_project_creates_nothing(self, tmp_path: Path) -> None:
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError):
            render_to_file(client, {"template": "t", "data": {}}, tmp_path / "new" / "a.pdf")  # type: ignore[arg-type]
        assert not (tmp_path / "new").exists()


class TestAsyncRenderToFileFailures:
    @respx.mock
    async def test_parent_that_is_a_file_is_io_error_before_any_render(
        self, tmp_path: Path
    ) -> None:
        render = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        (tmp_path / "blocker").write_bytes(b"a file, not a directory")
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await async_render_to_file(
                    client,
                    PROJECT_MODE_INPUT,  # type: ignore[arg-type]
                    tmp_path / "blocker" / "a.pdf",
                )
        _assert_io_error(excinfo.value)
        assert render.call_count == 0

    @respx.mock
    async def test_write_failure_is_io_error_and_keeps_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        _fail_writes(monkeypatch, OSError(28, "No space left on device"))
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await async_render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_io_error(excinfo.value)
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @respx.mock
    async def test_failed_download_creates_no_target(self, tmp_path: Path) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=httpx.Response(403))
        target = tmp_path / "c.pdf"
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await async_render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        assert excinfo.value.code == "DOWNLOAD_FAILED"
        assert not target.exists()
        assert _leftovers(tmp_path) == []
