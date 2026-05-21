"""Public type surface (plan §9).

Inputs use `TypedDict` with `Required[...]` / `NotRequired[...]` (PEP 655,
stdlib since Python 3.11). Outputs use frozen dataclasses with `slots=True`.
Enums use `Literal[...]` so callers can pass string literals; equivalent
`StrEnum` exports may be added later without breaking the literal form.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Required, TypedDict

from poli_page._errors import PoliPageError

if TYPE_CHECKING:
    from poli_page._async_client import AsyncPoliPage
    from poli_page._client import PoliPage

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

PageFormat = Literal[
    "A3",
    "A4",
    "A5",
    "A6",
    "B4",
    "B5",
    "Letter",
    "Legal",
    "Tabloid",
    "Executive",
    "Statement",
    "Folio",
]

Orientation = Literal["portrait", "landscape"]

Environment = Literal["sandbox", "live"]

# ---------------------------------------------------------------------------
# Render inputs (plan §9.1)
# ---------------------------------------------------------------------------

RenderMetadata = Mapping[str, str | int | float | bool]
"""Free-form caller metadata. Primitives only — no nested objects or arrays."""


class _BaseRenderInput(TypedDict, total=False):
    data: Required[Mapping[str, Any]]
    format: NotRequired[PageFormat]
    orientation: NotRequired[Orientation]
    locale: NotRequired[str]
    metadata: NotRequired[RenderMetadata]
    idempotency_key: NotRequired[str]
    timeout: NotRequired[float]


class ProjectModeInput(_BaseRenderInput, total=False):
    """Render against a stored project + template by slug."""

    project: Required[str]
    template: Required[str]
    version: NotRequired[str]


class InlineModeInput(_BaseRenderInput, total=False):
    """Render with raw HTML inline. No project resolution."""

    template: Required[str]


RenderInput = ProjectModeInput | InlineModeInput

# ---------------------------------------------------------------------------
# Render outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Result of `client.render.preview(input)` (spec §5.3)."""

    html: str
    total_pages: int
    environment: Environment


@dataclass(frozen=True, slots=True)
class DocumentPreviewResult:
    """Result of `client.documents.preview(id)` (spec §6.2).

    Note: the field is `page_count` (singular), not `total_pages` as in
    `render.preview`'s `PreviewResult`. The deployed API uses different
    field names for the two endpoints — the SDK does not paper over it.
    """

    html: str
    page_count: int


@dataclass(frozen=True, slots=True)
class Thumbnail:
    """A single page thumbnail returned by `documents.thumbnails` (spec §6.3)."""

    page: int
    width: int
    height: int
    content_type: str
    data: str
    """Base64-encoded image bytes."""


class ThumbnailOptions(TypedDict, total=False):
    """Options for `client.documents.thumbnails(id, options)` (spec §6.3)."""

    width: Required[int]
    format: NotRequired[Literal["png", "jpeg"]]
    quality: NotRequired[int]
    pages: NotRequired[list[int]]


@dataclass(slots=True, kw_only=True)
class _DocumentDescriptorBase:
    """Wire-shape fields shared by the sync and async descriptors.

    Internal — callers should type-hint with `DocumentDescriptor` (sync) or
    `AsyncDocumentDescriptor` (async).
    """

    document_id: str
    organization_id: str
    project_id: str | None
    project_slug: str | None
    template_id: str | None
    template_slug: str | None
    version: str | None
    environment: Environment
    api_key_id: str | None
    format: PageFormat
    orientation: Orientation | None
    locale: str | None
    page_count: int
    size_bytes: int
    created_at: str
    metadata: RenderMetadata
    presigned_pdf_url: str
    expires_at: str


_NO_CLIENT_MESSAGE = (
    "Descriptor was not constructed by a Poli Page client; cannot download. "
    "Use client.render.document(...) or client.documents.get(...)."
)


@dataclass(slots=True, kw_only=True)
class DocumentDescriptor(_DocumentDescriptorBase):
    """Stored document returned by sync `render.document` / `documents.get`.

    Wire fields snake-cased; `download_pdf()` fetches the bytes from
    `presigned_pdf_url`. The URL has a 15-minute TTL — if it expired,
    refresh via `documents.get(id)`.
    """

    # Private SDK transport reference. Excluded from `repr()` and equality so
    # descriptors with identical wire fields compare equal even when produced
    # by different client instances.
    _client: PoliPage | None = field(default=None, repr=False, compare=False)

    def download_pdf(self) -> bytes:
        """Fetch the PDF bytes (sync) from `presigned_pdf_url`.

        Raises `PoliPageError(code='DOWNLOAD_FAILED')` on non-2xx or network
        failure. The S3 status (when present) is exposed via `err.status`.
        """
        if self._client is None:
            raise PoliPageError(_NO_CLIENT_MESSAGE, code="invalid_options")
        return self._client._fetch_bytes(self.presigned_pdf_url)  # pyright: ignore[reportPrivateUsage]


@dataclass(slots=True, kw_only=True)
class AsyncDocumentDescriptor(_DocumentDescriptorBase):
    """Stored document returned by async `render.document` / `documents.get`.

    Identical wire fields to `DocumentDescriptor`; `download_pdf()` is async.
    """

    _client: AsyncPoliPage | None = field(default=None, repr=False, compare=False)

    async def download_pdf(self) -> bytes:
        """Fetch the PDF bytes (async) from `presigned_pdf_url`."""
        if self._client is None:
            raise PoliPageError(_NO_CLIENT_MESSAGE, code="invalid_options")
        return await self._client._fetch_bytes(self.presigned_pdf_url)  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Hooks (plan §10.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """Event passed to the `on_retry` hook before each retry sleep."""

    attempt: int
    """1-based; the attempt about to be made (2 = first retry)."""

    delay_seconds: float
    """The sleep duration before this attempt."""

    reason: PoliPageError
    """The error that triggered the retry."""


OnRetry = Callable[[RetryEvent], None]
OnError = Callable[[PoliPageError], None]
