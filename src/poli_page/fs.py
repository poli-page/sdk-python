"""Filesystem helpers: stream a PDF straight to disk (plan §11).

Both helpers build on `client.render.pdf_stream` to keep memory bounded
regardless of document size. Parent directories are created; existing
files are overwritten.

Sync path uses a plain `open(path, 'wb')`. The async path performs the
blocking file write inside `asyncio.to_thread` so we avoid pulling
`aiofiles` (or similar) into the dependency footprint.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from poli_page._async_client import AsyncPoliPage
    from poli_page._client import PoliPage
    from poli_page.types import ProjectModeInput


def render_to_file(
    client: PoliPage,
    input: ProjectModeInput,
    path: str | os.PathLike[str],
) -> None:
    """Render a PDF and write it to disk (sync).

    Streams response bytes directly to the file — memory-bounded
    regardless of document size. Creates parent directories and
    overwrites any existing file at `path`.

    Project mode only; inline-shaped input surfaces as
    `PoliPageError(code='PROJECT_REQUIRED_FOR_DOCUMENT')`.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with client.render.pdf_stream(input) as stream, out.open("wb") as file:
        for chunk in stream:
            file.write(chunk)


async def async_render_to_file(
    client: AsyncPoliPage,
    input: ProjectModeInput,
    path: str | os.PathLike[str],
) -> None:
    """Render a PDF and write it to disk (async).

    Streams response bytes directly to the file. The blocking file write
    runs in `asyncio.to_thread` to avoid an extra dependency (`aiofiles`).
    """
    out = Path(path)
    await asyncio.to_thread(out.parent.mkdir, parents=True, exist_ok=True)
    async with client.render.pdf_stream(input) as stream:
        with out.open("wb") as file:
            async for chunk in stream:
                await asyncio.to_thread(file.write, chunk)
