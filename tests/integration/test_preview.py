"""Live-API integration tests for `render.preview` (port of sdk-node).

Gated on `POLI_PAGE_API_KEY`. Run explicitly with:
    POLI_PAGE_API_KEY=pp_test_... pytest tests/integration/ -m integration
"""

from __future__ import annotations

import pytest

from poli_page import PoliPage

pytestmark = pytest.mark.integration


def test_preview_returns_html_and_environment(client: PoliPage) -> None:
    """Inline mode preview against the live API.

    Inline mode keeps the test self-contained — no project/template setup
    needed. The deployed API returns `total_pages: 0` for short inline content
    (no explicit page breaks), so the assertion is just `>= 0`.
    """
    result = client.render.preview(
        {"template": "<p>{{ name }}</p>", "data": {"name": "Preview Test"}}
    )
    assert isinstance(result.html, str)
    assert len(result.html) > 0
    assert result.total_pages >= 0
    assert result.environment in ("sandbox", "live")


def test_preview_project_mode_against_welcome_template(
    client: PoliPage, test_project: str, test_template: str, test_version: str
) -> None:
    result = client.render.preview(
        {
            "project": test_project,
            "template": test_template,
            "version": test_version,
            "data": {"name": "Integration"},
        }
    )
    assert len(result.html) > 0
    assert result.environment in ("sandbox", "live")
