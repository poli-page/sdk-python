"""Filesystem helpers: stream a PDF straight to disk.

Both helpers build on `client.render.pdf_stream` to keep memory bounded
regardless of document size. Parent directories are created.

The PDF is written to a temporary file next to the target, then renamed over
it once complete. On any failure (the render, the download or the write) the
target is left as it was: an existing file keeps its content and a missing one
is not created. The directory and the temporary file are prepared before the
render, so a path that cannot be written costs no render.

An existing target that is not a regular file (a directory, a FIFO, a device, a
socket) raises `io_error` with `Failed to write PDF: <target>: not a regular
file`, and one that is not writable raises `io_error` with
`Failed to write PDF: <target>: Permission denied`, both before any render.

A symlinked target is resolved first: the temporary file goes next to the file
the link points to and is renamed onto it, so the link stays a link. A replaced
file keeps its permission mode. Its owner and its hard links are not kept: the
rename puts a new file in place, owned by the user running the SDK, and other
hard links to the old file keep the old content.

A file that cannot be written raises `PoliPageError` with the code `io_error`,
no `status`, the message `Failed to write PDF: <target>: <reason>` (the path as
the caller gave it, then the OS error's own text; never the temporary file's
name) and the `OSError` as `__cause__`. It is never retried.

The async helper runs the blocking file calls in `asyncio.to_thread` so we
avoid pulling `aiofiles` (or similar) into the dependency footprint.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import secrets
import stat
from dataclasses import dataclass
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
    part = _open_part(path)
    try:
        with client.render.pdf_stream(input) as stream:
            for chunk in stream:
                _write_chunk(part, chunk)
        _finish(part)
    except BaseException:
        _discard(part)
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
    part = await asyncio.to_thread(_open_part, path)
    try:
        async with client.render.pdf_stream(input) as stream:
            async for chunk in stream:
                await asyncio.to_thread(_write_chunk, part, chunk)
        await asyncio.to_thread(_finish, part)
    except BaseException:
        _discard(part)
        raise


@dataclass(slots=True)
class _Part:
    """The temporary file of one write, and the target it will replace."""

    shown: str
    """The target as the caller named it: the only path an error message shows."""
    target: Path
    """The target with every symlink resolved: the file the rename replaces."""
    path: Path
    """The temporary file, next to `target`."""
    file: BinaryIO


def _io_error(shown: str, exc: OSError) -> PoliPageError:
    """`io_error` for the target `shown`: the reason never names the temporary file.

    The OS text (`strerror`) without the paths `str(exc)` adds, which may be the temporary
    file's; the `OSError` itself is chained as `__cause__` by the caller.
    """
    reason = f"{shown}: {exc.strerror or str(exc) or type(exc).__name__}"
    return PoliPageError(MESSAGE_IO_ERROR.format(reason=reason), code="io_error")


def _open_part(path: str | os.PathLike[str]) -> _Part:
    """Resolve `path`, create its parent directories and a new temporary file next to it.

    Symlinks are resolved, each hop relative to the real directory of its link
    (`os.path.realpath`), so that the rename replaces the file a link points to, not the link.
    """
    shown = os.fspath(path)
    try:
        target = Path(os.path.realpath(path))
        _check_existing(shown, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A new name each time ("x": never an existing file), hidden, in the target's
        # directory so the final rename stays on one filesystem.
        temp = target.parent / f".{target.name}.{secrets.token_hex(8)}.part"
        return _Part(shown=shown, target=target, path=temp, file=temp.open("xb"))
    except OSError as exc:
        raise _io_error(shown, exc) from exc


def _check_existing(shown: str, target: Path) -> None:
    """Refuse, before any render, an existing target the rename must not replace.

    A target that is not a regular file (a directory, a FIFO, a device, a socket), or one the
    user cannot write, fails now rather than being replaced. `os.stat` and `os.access` only:
    opening the target would block on a FIFO.
    """
    try:
        existing = os.stat(target)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(existing.st_mode):
        raise PoliPageError(
            MESSAGE_IO_ERROR.format(reason=f"{shown}: not a regular file"), code="io_error"
        )
    if not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(target))


def _write_chunk(part: _Part, chunk: bytes) -> None:
    try:
        part.file.write(chunk)
    except OSError as exc:
        raise _io_error(part.shown, exc) from exc


def _finish(part: _Part) -> None:
    """Close the temporary file (flushing it), give it the mode of an existing target, and
    rename it over the target."""
    try:
        part.file.close()
        _keep_mode(part.path, part.target)
        os.replace(part.path, part.target)
    except OSError as exc:
        raise _io_error(part.shown, exc) from exc


def _keep_mode(temp: Path, target: Path) -> None:
    """Copy the permission mode of an existing regular file `target` onto `temp`."""
    try:
        existing = os.stat(target)
    except FileNotFoundError:
        return
    if stat.S_ISREG(existing.st_mode):
        os.chmod(temp, stat.S_IMODE(existing.st_mode))


def _discard(part: _Part) -> None:
    """Best effort: the error being raised matters more than a leftover temporary file."""
    with contextlib.suppress(OSError):
        part.file.close()
    with contextlib.suppress(OSError):
        part.path.unlink(missing_ok=True)
