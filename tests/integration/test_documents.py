"""Live-API integration test: documents.* round-trip.

Port of sdk-node/tests/integration/documents.integration.test.ts.

Renders a document, fetches its descriptor, downloads the PDF, generates
thumbnails (tolerating tier-gated `THUMBNAILS_NOT_AVAILABLE` on Free),
reads the stored HTML preview, deletes, then verifies a subsequent get
raises 410 GONE.
"""

from __future__ import annotations

import pytest

from poli_page import PoliPage, PoliPageError

pytestmark = pytest.mark.integration


def test_documents_round_trip(
    client: PoliPage, test_project: str, test_template: str, test_version: str
) -> None:
    # 1. Render and store a document.
    created = client.render.document(
        {
            "project": test_project,
            "template": test_template,
            "version": test_version,
            "data": {"id": "round-trip"},
            "metadata": {"source": "sdk-python integration test"},
        }
    )
    assert isinstance(created.document_id, str)
    assert len(created.document_id) > 0

    # 2. Fetch a fresh descriptor.
    fetched = client.documents.get(created.document_id)
    assert fetched.document_id == created.document_id
    assert fetched.metadata.get("source") == "sdk-python integration test"

    # 3. Download the PDF via the fluent helper.
    pdf = fetched.download_pdf()
    assert pdf[:4] == b"%PDF"

    # 4. Thumbnails — tier-gated on the API side. Don't fail the round-trip
    # on Free; just skip the per-thumbnail assertion if the API says no.
    try:
        thumbs = client.documents.thumbnails(created.document_id, {"width": 320, "format": "png"})
    except PoliPageError as err:
        if err.code != "THUMBNAILS_NOT_AVAILABLE":
            raise
    else:
        assert len(thumbs) > 0
        assert thumbs[0].content_type == "image/png"

    # 5. documents.preview returns html + page_count.
    preview = client.documents.preview(created.document_id)
    assert preview.page_count > 0
    assert isinstance(preview.html, str)

    # 6. Soft-delete.
    client.documents.delete(created.document_id)

    # 7. Subsequent get returns 410 GONE.
    with pytest.raises(PoliPageError) as excinfo:
        client.documents.get(created.document_id)
    assert excinfo.value.status == 410
    # The deployed API may emit 'GONE' or 'DOCUMENT_GONE' depending on
    # API version — accept either.
    assert excinfo.value.code in ("GONE", "DOCUMENT_GONE")
