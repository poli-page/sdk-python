"""Live-API integration tests for `render.pdf`, `render.pdf_stream`, `render.document`.

Gated on `POLI_PAGE_API_KEY`. Uses the `getting-started/welcome` template
provisioned for every Poli Page org.
"""

from __future__ import annotations

import pytest

from poli_page import PoliPage, PoliPageError

pytestmark = pytest.mark.integration


def test_pdf_returns_magic_bytes(
    client: PoliPage, test_project: str, test_template: str, test_version: str
) -> None:
    pdf = client.render.pdf(
        {
            "project": test_project,
            "template": test_template,
            "version": test_version,
            "data": {"name": "Integration Test"},
        }
    )
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"


def test_document_stores_and_downloads(
    client: PoliPage, test_project: str, test_template: str, test_version: str
) -> None:
    doc = client.render.document(
        {
            "project": test_project,
            "template": test_template,
            "version": test_version,
            "data": {"name": "render.document"},
            "metadata": {"source": "sdk-python integration test"},
        }
    )
    assert doc.document_id
    assert doc.page_count > 0
    assert doc.size_bytes > 0
    assert doc.metadata.get("source") == "sdk-python integration test"
    assert doc.presigned_pdf_url.startswith("https://")
    pdf = doc.download_pdf()
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"


def test_pdf_stream_yields_bytes(
    client: PoliPage, test_project: str, test_template: str, test_version: str
) -> None:
    chunks: list[bytes] = []
    with client.render.pdf_stream(
        {
            "project": test_project,
            "template": test_template,
            "version": test_version,
            "data": {"name": "pdf_stream"},
        }
    ) as stream:
        for chunk in stream:
            chunks.append(chunk)
    pdf = b"".join(chunks)
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"


def test_bad_api_key_raises_authentication_error(
    base_url: str, test_project: str, test_template: str, test_version: str
) -> None:
    client = PoliPage(
        api_key="pp_test_invalid_xxx_definitely_not_real",
        base_url=base_url,
        max_retries=0,
    )
    try:
        with pytest.raises(PoliPageError) as excinfo:
            client.render.pdf(
                {
                    "project": test_project,
                    "template": test_template,
                    "version": test_version,
                    "data": {},
                }
            )
        assert excinfo.value.status == 401
        assert excinfo.value.is_auth_error()
    finally:
        client.close()
