# Demonstrates: client.documents.thumbnails(id, options) — page thumbnails for a stored document.
from poli_page import PoliPage

client = PoliPage()

thumbnails = client.documents.thumbnails(
    "doc_abc123",
    {"width": 840, "format": "png", "pages": [1, 2]},
)

# Each entry includes the image bytes base64-encoded.
for t in thumbnails:
    print(
        f"Page {t.page}: {t.width}x{t.height} {t.content_type} "
        f"({len(t.data)} base64 chars)"
    )
