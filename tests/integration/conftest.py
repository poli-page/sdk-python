"""Shared fixtures for integration tests (hit the live API).

Env-var conventions shared across SDKs so the same CI secrets drive them all:
- POLI_PAGE_API_KEY (required; tests skip when unset)
- POLI_PAGE_TEST_BASE_URL (optional; SDK default applies when unset)
- POLI_PAGE_TEST_PROJECT / TEMPLATE / VERSION (overrides for the test template)
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from poli_page import PoliPage


@pytest.fixture(scope="module")
def api_key() -> str:
    key = os.environ.get("POLI_PAGE_API_KEY")
    if not key:
        pytest.skip("POLI_PAGE_API_KEY not set — integration tests skipped")
    return key


@pytest.fixture(scope="module")
def base_url() -> str | None:
    return os.environ.get("POLI_PAGE_TEST_BASE_URL")


@pytest.fixture(scope="module")
def test_project() -> str:
    return os.environ.get("POLI_PAGE_TEST_PROJECT", "getting-started")


@pytest.fixture(scope="module")
def test_template() -> str:
    return os.environ.get("POLI_PAGE_TEST_TEMPLATE", "welcome")


@pytest.fixture(scope="module")
def test_version() -> str:
    return os.environ.get("POLI_PAGE_TEST_VERSION", "1.0.0")


@pytest.fixture
def client(api_key: str, base_url: str | None) -> Iterator[PoliPage]:
    client = (
        PoliPage(api_key=api_key, base_url=base_url)
        if base_url is not None
        else PoliPage(api_key=api_key)
    )
    with client as c:
        yield c
