"""Public type surface (plan §9).

Inputs use `TypedDict` with `Required[...]` / `NotRequired[...]` (PEP 655,
stdlib since Python 3.11). Outputs use frozen dataclasses with `slots=True`.
Enums use `Literal[...]` so callers can pass string literals; equivalent
`StrEnum` exports may be added later without breaking the literal form.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Required, TypedDict

from poli_page._errors import PoliPageError

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
