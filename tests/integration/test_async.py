"""Live-API integration test: full async round-trip.

Hits api-develop.poli.page. Exercises the async surface end-to-end:
preview (inline), pdf (project), document.download_pdf, pdf_stream,
documents.get, documents.preview, documents.thumbnails (tier-aware),
documents.delete, and the 410-GONE re-get.
"""

from __future__ import annotations

import pytest

from poli_page import AsyncPoliPage, PoliPageError

pytestmark = pytest.mark.integration


async def test_async_preview_inline(api_key: str, base_url: str) -> None:
    async with AsyncPoliPage(api_key=api_key, base_url=base_url) as client:
        result = await client.render.preview(
            {"template": "<p>{{ name }}</p>", "data": {"name": "Async"}}
        )
    assert len(result.html) > 0
    assert result.environment in ("sandbox", "live")


async def test_async_pdf_magic_bytes(
    api_key: str,
    base_url: str,
    test_project: str,
    test_template: str,
    test_version: str,
) -> None:
    async with AsyncPoliPage(api_key=api_key, base_url=base_url) as client:
        pdf = await client.render.pdf(
            {
                "project": test_project,
                "template": test_template,
                "version": test_version,
                "data": {"name": "Async PDF"},
            }
        )
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"


async def test_async_pdf_stream(
    api_key: str,
    base_url: str,
    test_project: str,
    test_template: str,
    test_version: str,
) -> None:
    chunks: list[bytes] = []
    async with (
        AsyncPoliPage(api_key=api_key, base_url=base_url) as client,
        client.render.pdf_stream(
            {
                "project": test_project,
                "template": test_template,
                "version": test_version,
                "data": {"name": "Async Stream"},
            }
        ) as stream,
    ):
        async for chunk in stream:
            chunks.append(chunk)
    pdf = b"".join(chunks)
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"


async def test_async_documents_round_trip(
    api_key: str,
    base_url: str,
    test_project: str,
    test_template: str,
    test_version: str,
) -> None:
    async with AsyncPoliPage(api_key=api_key, base_url=base_url) as client:
        created = await client.render.document(
            {
                "project": test_project,
                "template": test_template,
                "version": test_version,
                "data": {"id": "async-round-trip"},
                "metadata": {"source": "sdk-python async integration"},
            }
        )
        assert created.document_id

        fetched = await client.documents.get(created.document_id)
        assert fetched.document_id == created.document_id
        assert fetched.metadata.get("source") == "sdk-python async integration"

        pdf = await fetched.download_pdf()
        assert pdf[:4] == b"%PDF"

        try:
            thumbs = await client.documents.thumbnails(
                created.document_id, {"width": 320, "format": "png"}
            )
        except PoliPageError as err:
            if err.code != "THUMBNAILS_NOT_AVAILABLE":
                raise
        else:
            assert len(thumbs) > 0
            assert thumbs[0].content_type == "image/png"

        preview = await client.documents.preview(created.document_id)
        assert preview.page_count > 0
        assert isinstance(preview.html, str)

        await client.documents.delete(created.document_id)

        with pytest.raises(PoliPageError) as excinfo:
            await client.documents.get(created.document_id)
        assert excinfo.value.status == 410
        assert excinfo.value.code in ("GONE", "DOCUMENT_GONE")
