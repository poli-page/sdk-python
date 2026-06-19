"""`render.*` namespaces — sync and async (plan §3.1, §5).

Two parallel classes: `RenderSync` consumes `PoliPage._request_json` and
`_fetch_bytes`; `RenderAsync` does the same with `await`. The four spec
methods (`pdf`, `pdf_stream`, `preview`, `document`) appear on both with
identical signatures modulo `async def` / `await`.

Inline mode is rejected locally on the project-mode-only methods (`pdf`,
`pdf_stream`, `document`); `preview` accepts either mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, cast

from poli_page._constants import PATH_RENDER, PATH_RENDER_PREVIEW
from poli_page._errors import PoliPageError
from poli_page._transport import from_wire, to_wire
from poli_page.types import (
    AsyncDocumentDescriptor,
    DocumentDescriptor,
    Environment,
    Orientation,
    PageFormat,
    PreviewResult,
    ProjectModeInput,
    RenderInput,
    RenderMetadata,
)

if TYPE_CHECKING:
    from poli_page._async_client import AsyncPoliPage
    from poli_page._client import PoliPage


# ---------------------------------------------------------------------------
# Sync namespace
# ---------------------------------------------------------------------------


class RenderSync:
    """Implements `client.render` for the sync client."""

    def __init__(self, client: PoliPage) -> None:
        self._client = client

    def preview(self, input: RenderInput) -> PreviewResult:
        """Generate paginated HTML preview output (spec §5.3)."""
        idempotency_key = input.get("idempotency_key")
        timeout = input.get("timeout")
        body = to_wire(input)
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER_PREVIEW, body=body, idempotency_key=idempotency_key, timeout=timeout
        )
        return _make_preview_result(raw)

    def document(self, input: ProjectModeInput) -> DocumentDescriptor:
        """Render a PDF, store it server-side, return the descriptor (spec §5.2)."""
        _require_project_mode(input)
        idempotency_key = input.get("idempotency_key")
        timeout = input.get("timeout")
        body = to_wire(input)
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER, body=body, idempotency_key=idempotency_key, timeout=timeout
        )
        return _build_descriptor(self._client, raw)

    def pdf(self, input: ProjectModeInput) -> bytes:
        """Render a PDF and return its raw bytes (two HTTP calls: render + S3)."""
        descriptor = self.document(input)
        return descriptor.download_pdf()

    def pdf_stream(self, input: ProjectModeInput) -> _PdfStreamContext:
        """Render a PDF and return a streaming context manager (plan §5.6)."""
        descriptor = self.document(input)
        return _PdfStreamContext(self._client, descriptor.presigned_pdf_url)


# ---------------------------------------------------------------------------
# Async namespace
# ---------------------------------------------------------------------------


class RenderAsync:
    """Implements `client.render` for the async client."""

    def __init__(self, client: AsyncPoliPage) -> None:
        self._client = client

    async def preview(self, input: RenderInput) -> PreviewResult:
        idempotency_key = input.get("idempotency_key")
        timeout = input.get("timeout")
        body = to_wire(input)
        raw = await self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER_PREVIEW, body=body, idempotency_key=idempotency_key, timeout=timeout
        )
        return _make_preview_result(raw)

    async def document(self, input: ProjectModeInput) -> AsyncDocumentDescriptor:
        _require_project_mode(input)
        idempotency_key = input.get("idempotency_key")
        timeout = input.get("timeout")
        body = to_wire(input)
        raw = await self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER, body=body, idempotency_key=idempotency_key, timeout=timeout
        )
        return _build_async_descriptor(self._client, raw)

    async def pdf(self, input: ProjectModeInput) -> bytes:
        descriptor = await self.document(input)
        return await descriptor.download_pdf()

    def pdf_stream(self, input: ProjectModeInput) -> _AsyncPdfStreamCoroutineCM:
        """Return an async-with-able object that fetches the descriptor lazily.

        `async with client.render.pdf_stream(input) as chunks:` — the
        `POST /v1/render` happens on entry, followed by the streaming GET
        against `presigned_pdf_url`. Inline-mode validation also runs at
        `__aenter__` time (await is needed to surface PoliPageError).
        """
        return _AsyncPdfStreamCoroutineCM(self._client, input)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_project_mode(input: ProjectModeInput) -> None:
    """Reject inline-shaped input on document/pdf/pdf_stream methods.

    Mirrors the API's `PROJECT_REQUIRED_FOR_DOCUMENT` error locally so the
    SDK fails fast without an HTTP round trip.
    """
    if not input.get("project"):
        raise PoliPageError(
            "project is required for render.pdf / render.pdf_stream / render.document. "
            "Use render.preview for inline HTML rendering.",
            code="PROJECT_REQUIRED_FOR_DOCUMENT",
        )


def _make_preview_result(raw: dict[str, Any]) -> PreviewResult:
    result = from_wire(raw)
    return PreviewResult(
        html=cast(str, result["html"]),
        total_pages=cast(int, result["total_pages"]),
        environment=cast(Environment, result["environment"]),
    )


def _descriptor_init_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract the wire-shape kwargs both descriptor flavours expect."""
    snake = from_wire(raw)
    return {
        "document_id": cast(str, snake["document_id"]),
        "organization_id": cast(str, snake["organization_id"]),
        "project_id": cast("str | None", snake.get("project_id")),
        "project_slug": cast("str | None", snake.get("project_slug")),
        "template_id": cast("str | None", snake.get("template_id")),
        "template_slug": cast("str | None", snake.get("template_slug")),
        "version": cast("str | None", snake.get("version")),
        "environment": cast(Environment, snake["environment"]),
        "api_key_id": cast("str | None", snake.get("api_key_id")),
        "format": cast(PageFormat, snake["format"]),
        "orientation": cast("Orientation | None", snake.get("orientation")),
        "locale": cast("str | None", snake.get("locale")),
        "page_count": cast(int, snake["page_count"]),
        "size_bytes": cast(int, snake["size_bytes"]),
        "created_at": cast(str, snake["created_at"]),
        "metadata": cast(RenderMetadata, snake.get("metadata") or {}),
        "presigned_pdf_url": cast(str, snake["presigned_pdf_url"]),
        "expires_at": cast(str, snake["expires_at"]),
    }


def _build_descriptor(client: PoliPage, raw: dict[str, Any]) -> DocumentDescriptor:
    return DocumentDescriptor(**_descriptor_init_kwargs(raw), _client=client)


def _build_async_descriptor(client: AsyncPoliPage, raw: dict[str, Any]) -> AsyncDocumentDescriptor:
    return AsyncDocumentDescriptor(**_descriptor_init_kwargs(raw), _client=client)


# ---------------------------------------------------------------------------
# Streaming context managers
# ---------------------------------------------------------------------------


class _PdfStreamContext:
    """Sync streaming wrapper for `render.pdf_stream` (plan §5.6).

    Connection or non-2xx errors at `__enter__` surface as
    `PoliPageError(code='DOWNLOAD_FAILED')`; the underlying response is
    closed unconditionally on `__exit__`.
    """

    __slots__ = ("_client", "_stream_cm", "_url")

    def __init__(self, client: PoliPage, url: str) -> None:
        self._client = client
        self._url = url
        self._stream_cm: object | None = None

    def __enter__(self) -> Iterator[bytes]:
        cm = self._client._stream_bytes(self._url)  # pyright: ignore[reportPrivateUsage]
        self._stream_cm = cm
        return cm.__enter__()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._stream_cm is not None:
            self._stream_cm.__exit__(exc_type, exc, tb)  # type: ignore[attr-defined]
            self._stream_cm = None


class _AsyncPdfStreamCoroutineCM:
    """Async streaming wrapper for `render.pdf_stream`.

    Single class composes the `POST /v1/render` (to fetch the descriptor)
    with the streaming GET against `presigned_pdf_url`. Both happen on
    `__aenter__` so inline-mode validation also surfaces there.
    """

    __slots__ = ("_client", "_input", "_stream_cm")

    def __init__(self, client: AsyncPoliPage, input: ProjectModeInput) -> None:
        self._client = client
        self._input = input
        self._stream_cm: object | None = None

    async def __aenter__(self) -> AsyncIterator[bytes]:
        _require_project_mode(self._input)
        idempotency_key = self._input.get("idempotency_key")
        timeout = self._input.get("timeout")
        body = to_wire(self._input)
        raw = await self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER, body=body, idempotency_key=idempotency_key, timeout=timeout
        )
        descriptor = _build_async_descriptor(self._client, raw)
        cm = self._client._stream_bytes(descriptor.presigned_pdf_url)  # pyright: ignore[reportPrivateUsage]
        self._stream_cm = cm
        return await cm.__aenter__()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._stream_cm is not None:
            await self._stream_cm.__aexit__(exc_type, exc, tb)  # type: ignore[attr-defined]
            self._stream_cm = None
