"""Unit tests for the `render_to_file` helpers — sync + async.

Port of sdk-node/tests/node.test.ts.
"""

from __future__ import annotations

import os
import stat
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, cast

import httpx
import pytest
import respx

from poli_page import AsyncPoliPage, PoliPage, PoliPageError
from poli_page.fs import _open_part, async_render_to_file, render_to_file
from poli_page.types import RenderInput

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


def _assert_io_error(err: PoliPageError, target: Path) -> None:
    """`io_error` naming the target as given and the OS text, never the temporary file."""
    assert err.code == "io_error"
    assert err.status is None
    assert isinstance(err.__cause__, OSError)
    assert err.message == f"Failed to write PDF: {target}: {err.__cause__.strerror}"
    assert ".part" not in err.message
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
    def open_part(path: Path) -> object:
        part = _open_part(path)
        part.file = cast(BinaryIO, _FullDisk(part.file, error))
        return part

    monkeypatch.setattr("poli_page.fs._open_part", open_part)


def _assert_not_a_regular_file(err: PoliPageError, target: Path) -> None:
    assert err.code == "io_error"
    assert err.status is None
    assert err.message == f"Failed to write PDF: {target}: not a regular file"
    assert err.is_retryable() is False


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
        _assert_io_error(excinfo.value, tmp_path / "blocker" / "a.pdf")
        assert render.call_count == 0

    @respx.mock
    def test_target_that_is_a_directory_is_io_error_before_any_render(self, tmp_path: Path) -> None:
        render = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        target = tmp_path / "out.pdf"
        target.mkdir()
        (target / "keep").write_bytes(b"x")
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_not_a_regular_file(excinfo.value, target)
        assert render.call_count == 0
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
        _assert_io_error(excinfo.value, target)
        assert excinfo.value.__cause__ is disk_full
        assert excinfo.value.message == f"Failed to write PDF: {target}: No space left on device"
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @respx.mock
    def test_a_failed_rename_is_io_error_and_keeps_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        failures: list[OSError] = []

        def replace(src: object, dst: object) -> None:
            # As the OS reports it: both paths, the temporary file's first.
            failures.append(PermissionError(13, "Permission denied", str(src), None, str(dst)))
            raise failures[-1]

        monkeypatch.setattr(os, "replace", replace)
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_io_error(excinfo.value, target)
        assert excinfo.value.__cause__ is failures[0]
        assert ".part" in str(failures[0])  # the cause keeps the OS's full text
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @pytest.mark.skipif(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="needs POSIX directory permissions, as a user other than root",
    )
    @respx.mock
    def test_an_unwritable_directory_names_the_target_not_the_temp_file(
        self, tmp_path: Path
    ) -> None:
        # Creating the temporary file is the step that fails: the OS error names it.
        render = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        directory = tmp_path / "ro"
        directory.mkdir()
        directory.chmod(0o555)
        target = directory / "a.pdf"
        try:
            client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
            with pytest.raises(PoliPageError) as excinfo:
                render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        finally:
            directory.chmod(0o755)
        _assert_io_error(excinfo.value, target)
        assert isinstance(excinfo.value.__cause__, PermissionError)
        assert ".part" in str(excinfo.value.__cause__)
        assert render.call_count == 0
        assert not target.exists()

    @respx.mock
    def test_a_failed_mode_copy_names_the_target_not_the_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")

        def chmod(path: object, _mode: int) -> None:
            raise PermissionError(1, "Operation not permitted", str(path))

        monkeypatch.setattr(os, "chmod", chmod)
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, target)  # type: ignore[arg-type]
        _assert_io_error(excinfo.value, target)
        assert excinfo.value.message == f"Failed to write PDF: {target}: Operation not permitted"
        assert target.read_bytes() == b"previous PDF"
        assert _leftovers(tmp_path) == []

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need POSIX semantics")
    @respx.mock
    def test_a_message_names_the_path_as_given_not_its_resolved_form(self, tmp_path: Path) -> None:
        # The link is the caller's name for the target; the real path stays in the cause.
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
        (tmp_path / "real").mkdir()
        link = tmp_path / "link.pdf"
        link.symlink_to("real")
        client = PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL)
        with pytest.raises(PoliPageError) as excinfo:
            render_to_file(client, PROJECT_MODE_INPUT, link)  # type: ignore[arg-type]
        _assert_not_a_regular_file(excinfo.value, link)

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
        _assert_io_error(excinfo.value, tmp_path / "blocker" / "a.pdf")
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
        _assert_io_error(excinfo.value, target)
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


#: The test input, typed for the calls below.
_RENDER_INPUT = cast(RenderInput, PROJECT_MODE_INPUT)

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks and permission modes need POSIX semantics"
)


def _mock_render() -> respx.Route:
    route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(return_value=_descriptor_response())
    respx.get(PRESIGNED_URL).mock(return_value=_pdf_response())
    return route


class TestRenderToFileTarget:
    """Symlinks stay links, an existing file keeps its mode, a read-only one is refused."""

    @posix_only
    @respx.mock
    def test_a_symlink_stays_a_link_to_the_new_pdf(self, tmp_path: Path) -> None:
        _mock_render()
        real = tmp_path / "real.pdf"
        real.write_bytes(b"previous PDF")
        link = tmp_path / "link.pdf"
        link.symlink_to("real.pdf")
        render_to_file(
            PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL), _RENDER_INPUT, link
        )
        assert link.is_symlink()
        assert os.readlink(link) == "real.pdf"
        assert real.read_bytes().startswith(b"%PDF")
        assert _leftovers(tmp_path) == []

    @posix_only
    @respx.mock
    def test_a_dangling_symlink_creates_the_file_it_names(self, tmp_path: Path) -> None:
        _mock_render()
        link = tmp_path / "link.pdf"
        link.symlink_to("out/new.pdf")
        render_to_file(
            PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL), _RENDER_INPUT, link
        )
        assert link.is_symlink()
        assert (tmp_path / "out" / "new.pdf").read_bytes().startswith(b"%PDF")

    @posix_only
    @pytest.mark.parametrize("exists", [True, False])
    @respx.mock
    def test_each_hop_resolves_from_the_real_directory_of_its_link(
        self, tmp_path: Path, exists: bool
    ) -> None:
        # sym -> real/dir and real/dir/link -> ../a.pdf: `sym/link` is `real/a.pdf`, not
        # `a.pdf` next to `sym` (the path as written).
        _mock_render()
        (tmp_path / "real" / "dir").mkdir(parents=True)
        (tmp_path / "sym").symlink_to("real/dir")
        (tmp_path / "real" / "dir" / "link").symlink_to("../a.pdf")
        if exists:
            (tmp_path / "real" / "a.pdf").write_bytes(b"previous PDF")
        render_to_file(
            PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL),
            _RENDER_INPUT,
            tmp_path / "sym" / "link",
        )
        assert (tmp_path / "real" / "a.pdf").read_bytes().startswith(b"%PDF")
        assert (tmp_path / "real" / "dir" / "link").is_symlink()
        assert not (tmp_path / "a.pdf").exists()

    @posix_only
    @respx.mock
    def test_an_existing_file_keeps_its_mode(self, tmp_path: Path) -> None:
        _mock_render()
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        target.chmod(0o640)
        render_to_file(
            PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL), _RENDER_INPUT, target
        )
        assert target.read_bytes().startswith(b"%PDF")
        assert stat.S_IMODE(target.stat().st_mode) == 0o640

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write a read-only file"
    )
    @respx.mock
    def test_a_read_only_target_is_io_error_before_any_render(self, tmp_path: Path) -> None:
        render = _mock_render()
        target = tmp_path / "c.pdf"
        target.write_bytes(b"previous PDF")
        target.chmod(0o444)
        try:
            with pytest.raises(PoliPageError) as excinfo:
                render_to_file(
                    PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL),
                    _RENDER_INPUT,
                    target,
                )
            _assert_io_error(excinfo.value, target)
            assert isinstance(excinfo.value.__cause__, PermissionError)
            assert render.call_count == 0
            assert target.read_bytes() == b"previous PDF"
            assert _leftovers(tmp_path) == []
        finally:
            target.chmod(0o644)

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs os.mkfifo (POSIX)")
    @respx.mock
    def test_a_fifo_target_is_io_error_before_any_render(self, tmp_path: Path) -> None:
        # Checked with os.stat: opening a FIFO would block until a reader comes. The call runs
        # on a thread so that a regression fails the test instead of hanging the suite.
        render = _mock_render()
        target = tmp_path / "out.pdf"
        os.mkfifo(target)
        raised: list[BaseException] = []

        def call() -> None:
            try:
                render_to_file(
                    PoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL),
                    _RENDER_INPUT,
                    target,
                )
            except BaseException as exc:
                raised.append(exc)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(5)
        if worker.is_alive():
            with open(target, "rb"):  # a reader unblocks the writer before the test fails
                pass
            pytest.fail("render_to_file blocked on the FIFO")
        assert len(raised) == 1
        assert isinstance(raised[0], PoliPageError)
        _assert_not_a_regular_file(raised[0], target)
        assert render.call_count == 0
        assert stat.S_ISFIFO(target.stat().st_mode)
        assert _leftovers(tmp_path) == []

    @posix_only
    @respx.mock
    async def test_async_follows_symlinks_and_keeps_the_mode(self, tmp_path: Path) -> None:
        _mock_render()
        real = tmp_path / "real.pdf"
        real.write_bytes(b"previous PDF")
        real.chmod(0o640)
        link = tmp_path / "link.pdf"
        link.symlink_to("real.pdf")
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=TEST_BASE_URL) as client:
            await async_render_to_file(client, _RENDER_INPUT, link)
        assert link.is_symlink()
        assert real.read_bytes().startswith(b"%PDF")
        assert stat.S_IMODE(real.stat().st_mode) == 0o640
