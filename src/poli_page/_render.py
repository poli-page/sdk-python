"""Synchronous `render.*` namespace (plan §3.1, §5).

Wires together the client's transport (`_request_json`, `_fetch_bytes`,
`_stream_bytes`) with the four spec methods: `pdf`, `pdf_stream`, `preview`,
`document`. Inline mode is rejected locally on the methods that require
project mode (`pdf`, `pdf_stream`, `document`) — `preview` accepts either.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

from poli_page._constants import PATH_RENDER, PATH_RENDER_PREVIEW
from poli_page._errors import PoliPageError
from poli_page._transport import from_wire, to_wire
from poli_page.types import (
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
    from poli_page._client import PoliPage


class RenderSync:
    """Implements `client.render`. Constructed by `PoliPage`; not for direct use."""

    def __init__(self, client: PoliPage) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # preview — accepts both project and inline mode (spec §5.3)
    # ------------------------------------------------------------------

    def preview(self, input: RenderInput) -> PreviewResult:
        """Generate paginated HTML preview output."""
        idempotency_key = input.get("idempotency_key")
        body = to_wire(input)
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER_PREVIEW, body=body, idempotency_key=idempotency_key
        )
        result = from_wire(raw)
        return PreviewResult(
            html=cast(str, result["html"]),
            total_pages=cast(int, result["total_pages"]),
            environment=cast(Environment, result["environment"]),
        )

    # ------------------------------------------------------------------
    # document / pdf / pdf_stream — project mode only (spec §5.1, §5.2)
    # ------------------------------------------------------------------

    def document(self, input: ProjectModeInput) -> DocumentDescriptor:
        """Render a PDF, store it server-side, return the descriptor."""
        _require_project_mode(input)
        idempotency_key = input.get("idempotency_key")
        body = to_wire(input)
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", PATH_RENDER, body=body, idempotency_key=idempotency_key
        )
        return _build_descriptor(self._client, raw)

    def pdf(self, input: ProjectModeInput) -> bytes:
        """Render a PDF and return its raw bytes (two HTTP calls: render + S3)."""
        descriptor = self.document(input)
        return descriptor.download_pdf()

    def pdf_stream(self, input: ProjectModeInput) -> _PdfStreamContext:
        """Render a PDF and return a streaming context manager.

        Two-step: first `POST /v1/render` (eager, before the CM is returned),
        then on `__enter__` open a streaming GET against `presigned_pdf_url`.
        Caller iterates chunks inside the `with` block; the response closes
        deterministically on exit.
        """
        descriptor = self.document(input)
        return _PdfStreamContext(self._client, descriptor.presigned_pdf_url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_project_mode(input: ProjectModeInput) -> None:
    """Raise locally when an inline-shaped dict is passed to a document method.

    The API would reject the request with PROJECT_REQUIRED_FOR_DOCUMENT
    anyway; failing fast saves an HTTP round trip and gives a clearer
    stack trace.
    """
    if not input.get("project"):
        raise PoliPageError(
            "project is required for render.pdf / render.pdf_stream / render.document. "
            "Use render.preview for inline HTML rendering.",
            code="PROJECT_REQUIRED_FOR_DOCUMENT",
        )


def _build_descriptor(client: PoliPage, raw: dict[str, object]) -> DocumentDescriptor:
    """Build a DocumentDescriptor from a wire response, wiring up the transport."""
    snake = from_wire(raw)
    return DocumentDescriptor(
        document_id=cast(str, snake["document_id"]),
        organization_id=cast(str, snake["organization_id"]),
        project_id=cast("str | None", snake.get("project_id")),
        project_slug=cast("str | None", snake.get("project_slug")),
        template_id=cast("str | None", snake.get("template_id")),
        template_slug=cast("str | None", snake.get("template_slug")),
        version=cast("str | None", snake.get("version")),
        environment=cast(Environment, snake["environment"]),
        api_key_id=cast("str | None", snake.get("api_key_id")),
        format=cast(PageFormat, snake["format"]),
        orientation=cast("Orientation | None", snake.get("orientation")),
        locale=cast("str | None", snake.get("locale")),
        page_count=cast(int, snake["page_count"]),
        size_bytes=cast(int, snake["size_bytes"]),
        created_at=cast(str, snake["created_at"]),
        metadata=cast(RenderMetadata, snake.get("metadata") or {}),
        presigned_pdf_url=cast(str, snake["presigned_pdf_url"]),
        expires_at=cast(str, snake["expires_at"]),
        _client=client,
    )


class _PdfStreamContext:
    """Context manager wrapping an httpx streaming response (plan §5.6).

    Yielded from `render.pdf_stream`. Connection or non-2xx errors at
    `__enter__` surface as `PoliPageError(code='DOWNLOAD_FAILED')`; the
    response is closed unconditionally on `__exit__`.
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

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        if self._stream_cm is not None:
            # The underlying contextmanager from @contextmanager handles re-raising.
            self._stream_cm.__exit__(exc_type, exc, tb)  # type: ignore[attr-defined]
            self._stream_cm = None
