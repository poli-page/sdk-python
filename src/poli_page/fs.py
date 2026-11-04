"""Filesystem helpers: stream a PDF straight to disk.

Both helpers build on `client.render.pdf_stream` to keep memory bounded
regardless of document size. Parent directories are created.

The PDF is written to a temporary file next to the target, then renamed over
it once complete. On any failure (the render, the download or the write) the
target is left as it was: an existing file keeps its content and a missing one
is not created. The directory and the temporary file are prepared before the
render, so a path that cannot be written costs no render.

A symlinked target is resolved first: the temporary file goes next to the file
the link points to and is renamed onto it, so the link stays a link. A replaced
file keeps its permission mode. Its owner and its hard links are not kept: the
rename puts a new file in place, owned by the user running the SDK, and other
hard links to the old file keep the old content.

A file that cannot be written raises `PoliPageError` with the code `io_error`,
no `status`, the message `Failed to write PDF: <reason>` (the OS error's own
text) and the `OSError` as `__cause__`. It is never retried.

The async helper runs the blocking file calls in `asyncio.to_thread` so we
avoid pulling `aiofiles` (or similar) into the dependency footprint.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import stat
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from poli_page._constants import MESSAGE_IO_ERROR
from poli_page._errors import PoliPageError
from poli_page._render import _require_project_mode  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from poli_page._async_client import AsyncPoliPage
    from poli_page._client import PoliPage
    from poli_page.types import RenderInput


def render_to_file(
    client: PoliPage,
    input: RenderInput,
    path: str | os.PathLike[str],
) -> None:
    """Render a PDF and write it to disk (sync).

    Streams response bytes to a temporary file in the target's directory —
    memory-bounded regardless of document size — and renames it over `path`
    once complete. Creates parent directories and replaces any existing file
    at `path`, keeping its permission mode (not its owner or hard links); a
    symlink at `path` stays a link to the replaced file. On failure, `path` is
    left untouched.

    Input without a `project` surfaces as
    `PoliPageError(code='PROJECT_REQUIRED_FOR_DOCUMENT')`. A file that cannot
    be written surfaces as `PoliPageError(code='io_error')`.
    """
    _require_project_mode(input)
    target, part, file = _open_part(path)
    try:
        with client.render.pdf_stream(input) as stream:
            for chunk in stream:
                _write_chunk(file, chunk)
        _finish(file, part, target)
    except BaseException:
        _discard(file, part)
        raise


async def async_render_to_file(
    client: AsyncPoliPage,
    input: RenderInput,
    path: str | os.PathLike[str],
) -> None:
    """Render a PDF and write it to disk (async).

    Same behaviour as `render_to_file`. The blocking file calls run in
    `asyncio.to_thread` to avoid an extra dependency (`aiofiles`).
    """
    _require_project_mode(input)
    target, part, file = await asyncio.to_thread(_open_part, path)
    try:
        async with client.render.pdf_stream(input) as stream:
            async for chunk in stream:
                await asyncio.to_thread(_write_chunk, file, chunk)
        await asyncio.to_thread(_finish, file, part, target)
    except BaseException:
        _discard(file, part)
        raise


def _io_error(exc: OSError) -> PoliPageError:
    return PoliPageError(MESSAGE_IO_ERROR.format(reason=exc), code="io_error")


def _open_part(path: str | os.PathLike[str]) -> tuple[Path, Path, BinaryIO]:
    """Resolve `path`, create its parent directories and a new temporary file next to it.

    Returns the resolved target, the temporary file's path and the open file. Symlinks are
    resolved, each hop relative to the real directory of its link (`os.path.realpath`), so
    that the rename replaces the file a link points to, not the link.
    """
    try:
        target = Path(os.path.realpath(path))
        # An existing target that cannot be opened for writing (read-only, a directory) fails
        # now, before any render, rather than being replaced by the rename.
        with contextlib.suppress(FileNotFoundError):
            target.open("r+b").close()
        target.parent.mkdir(parents=True, exist_ok=True)
        # A new name each time ("x": never an existing file), hidden, in the target's
        # directory so the final rename stays on one filesystem.
        part = target.parent / f".{target.name}.{secrets.token_hex(8)}.part"
        return target, part, part.open("xb")
    except OSError as exc:
        raise _io_error(exc) from exc


def _write_chunk(file: BinaryIO, chunk: bytes) -> None:
    try:
        file.write(chunk)
    except OSError as exc:
        raise _io_error(exc) from exc


def _finish(file: BinaryIO, part: Path, target: Path) -> None:
    """Close the temporary file (flushing it), give it the mode of an existing `target`, and
    rename it over `target`."""
    try:
        file.close()
        _keep_mode(part, target)
        os.replace(part, target)
    except OSError as exc:
        raise _io_error(exc) from exc


def _keep_mode(part: Path, target: Path) -> None:
    """Copy the permission mode of an existing regular file `target` onto `part`."""
    try:
        existing = os.stat(target)
    except FileNotFoundError:
        return
    if stat.S_ISREG(existing.st_mode):
        os.chmod(part, stat.S_IMODE(existing.st_mode))


def _discard(file: BinaryIO, part: Path) -> None:
    """Best effort: the error being raised matters more than a leftover temporary file."""
    with contextlib.suppress(OSError):
        file.close()
    with contextlib.suppress(OSError):
        part.unlink(missing_ok=True)
