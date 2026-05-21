"""Synchronous `render.*` namespace (plan §3.1, §13 Phase 2+).

Phase 2 ships `preview` only. `pdf`, `pdf_stream`, and `document` arrive in
Phase 3; they share this transport seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from poli_page._constants import PATH_RENDER_PREVIEW
from poli_page._transport import from_wire, to_wire
from poli_page.types import Environment, PreviewResult, RenderInput

if TYPE_CHECKING:
    from poli_page._client import PoliPage


class RenderSync:
    """Implements `client.render`. Constructed by `PoliPage`; not for direct use."""

    def __init__(self, client: PoliPage) -> None:
        self._client = client

    def preview(self, input: RenderInput) -> PreviewResult:
        """Generate paginated HTML preview output (spec §5.3).

        Accepts both project mode (`project + template + version?`) and inline
        mode (`template` as raw HTML). Returns the parsed `PreviewResult`.
        """
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
