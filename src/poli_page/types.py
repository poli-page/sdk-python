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


@dataclass(slots=True, kw_only=True)
class DocumentDescriptor:
    """Stored document returned by `render.document` and `documents.get` (spec §6).

    All wire fields are exposed as snake_cased attributes. `download_pdf()`
    fetches the bytes from `presigned_pdf_url` on demand — the URL has a
    15-minute TTL; if it expired, refresh via `documents.get(id)`.
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

    # Private SDK transport reference. Excluded from `repr()` and equality so
    # descriptors with identical wire fields compare equal even when produced
    # by different client instances.
    _client: PoliPage | None = field(default=None, repr=False, compare=False)

    def download_pdf(self) -> bytes:
        """Fetch the PDF bytes from `presigned_pdf_url`.

        Raises `PoliPageError(code='DOWNLOAD_FAILED')` on non-2xx or network
        failure. The S3 status (when present) is exposed via `err.status`.
        """
        if self._client is None:
            raise PoliPageError(
                "DocumentDescriptor was not constructed by a PoliPage client; "
                "cannot download. Use client.render.document(...) or "
                "client.documents.get(...).",
                code="invalid_options",
            )
        return self._client._fetch_bytes(self.presigned_pdf_url)  # pyright: ignore[reportPrivateUsage]


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
