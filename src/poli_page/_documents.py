"""`documents.*` namespaces — sync and async (spec §6, plan §3.1).

Three endpoint shapes meet here:
- JSON in + JSON out: `get`, `thumbnails`
- Empty in + text/html out + `X-Document-Page-Count` header: `preview`
- Empty in + no body: `delete`

The thumbnails wire format wraps the set options under a `thumbnails` key on
the request body (`{}` when none is set) and unwraps `{thumbnails: [...]}` on
the response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from poli_page._constants import (
    HEADER_DOCUMENT_PAGE_COUNT,
    path_document,
    path_document_preview,
    path_document_thumbnails,
)
from poli_page._transport import THUMBNAIL_WIRE_FIELDS, to_wire
from poli_page.types import (
    AsyncDocumentDescriptor,
    DocumentDescriptor,
    DocumentPreviewResult,
    Thumbnail,
    ThumbnailOptions,
)

if TYPE_CHECKING:
    from poli_page._async_client import AsyncPoliPage
    from poli_page._client import PoliPage


# ---------------------------------------------------------------------------
# Sync namespace
# ---------------------------------------------------------------------------


class DocumentsSync:
    """Implements `client.documents` for the sync client."""

    def __init__(self, client: PoliPage) -> None:
        self._client = client

    def get(self, id: str) -> DocumentDescriptor:
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "GET", path_document(id), body=None, idempotency_key=None
        )
        from poli_page._render import (
            _build_descriptor,  # pyright: ignore[reportPrivateUsage]
        )

        return _build_descriptor(self._client, raw)

    def preview(self, id: str) -> DocumentPreviewResult:
        """Retrieve stored paginated HTML + page count (spec §6.2).

        Wire response is `text/html`; page count rides the
        `X-Document-Page-Count` header. Missing or unparseable header →
        `page_count=0` (port Node's `documents.ts` NaN-tolerant fix).
        """
        response = self._client._request(  # pyright: ignore[reportPrivateUsage]
            "GET", path_document_preview(id), body=None, idempotency_key=None
        )
        return DocumentPreviewResult(
            html=response.text,
            page_count=_parse_page_count(response.headers.get(HEADER_DOCUMENT_PAGE_COUNT)),
        )

    def thumbnails(self, id: str, options: ThumbnailOptions | None = None) -> list[Thumbnail]:
        """Generate per-page thumbnails (spec §6.3).

        Every option is optional: the request body wraps the set ones as
        `{thumbnails: <options>}`, or is `{}` when none is set. The response
        unwraps `{thumbnails: [...]}`.
        """
        timeout, body = _thumbnails_request(options)
        raw = self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", path_document_thumbnails(id), body=body, idempotency_key=None, timeout=timeout
        )
        items = cast(list[dict[str, object]], raw["thumbnails"])
        return [_make_thumbnail(item) for item in items]

    def delete(self, id: str) -> None:
        """Soft-delete a stored document.

        Idempotent: the API answers `204` for an already-deleted document too.
        """
        self._client._request(  # pyright: ignore[reportPrivateUsage]
            "DELETE", path_document(id), body=None, idempotency_key=None
        )


# ---------------------------------------------------------------------------
# Async namespace
# ---------------------------------------------------------------------------


class DocumentsAsync:
    """Implements `client.documents` for the async client."""

    def __init__(self, client: AsyncPoliPage) -> None:
        self._client = client

    async def get(self, id: str) -> AsyncDocumentDescriptor:
        raw = await self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "GET", path_document(id), body=None, idempotency_key=None
        )
        from poli_page._render import (
            _build_async_descriptor,  # pyright: ignore[reportPrivateUsage]
        )

        return _build_async_descriptor(self._client, raw)

    async def preview(self, id: str) -> DocumentPreviewResult:
        response = await self._client._request(  # pyright: ignore[reportPrivateUsage]
            "GET", path_document_preview(id), body=None, idempotency_key=None
        )
        return DocumentPreviewResult(
            html=response.text,
            page_count=_parse_page_count(response.headers.get(HEADER_DOCUMENT_PAGE_COUNT)),
        )

    async def thumbnails(self, id: str, options: ThumbnailOptions | None = None) -> list[Thumbnail]:
        timeout, body = _thumbnails_request(options)
        raw = await self._client._request_json(  # pyright: ignore[reportPrivateUsage]
            "POST", path_document_thumbnails(id), body=body, idempotency_key=None, timeout=timeout
        )
        items = cast(list[dict[str, object]], raw["thumbnails"])
        return [_make_thumbnail(item) for item in items]

    async def delete(self, id: str) -> None:
        await self._client._request(  # pyright: ignore[reportPrivateUsage]
            "DELETE", path_document(id), body=None, idempotency_key=None
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _thumbnails_request(options: ThumbnailOptions | None) -> tuple[float | None, dict[str, Any]]:
    """Return the per-call timeout and the request body for `thumbnails`."""
    opts_dict = cast(dict[str, object], options or {})
    timeout = cast("float | None", opts_dict.get("timeout"))
    wire = to_wire(opts_dict, THUMBNAIL_WIRE_FIELDS)
    return timeout, ({"thumbnails": wire} if wire else {})


def _parse_page_count(header: str | None) -> int:
    if header is None:
        return 0
    try:
        return int(header)
    except ValueError:
        return 0


def _make_thumbnail(raw: dict[str, Any]) -> Thumbnail:
    return Thumbnail(
        page=cast(int, raw["page"]),
        width=cast(int, raw["width"]),
        height=cast(int, raw["height"]),
        content_type=cast(str, raw["contentType"]),
        data=cast(str, raw["data"]),
    )
