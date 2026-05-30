# Demonstrates: client.documents.preview(id) — get a stored document's HTML preview.
from poli_page import PoliPage

client = PoliPage()

preview = client.documents.preview("doc_abc123")

# `preview.html` is the server-rendered HTML with the stored document's data
# applied to its template — useful for in-browser previews without a PDF.
print(f"Preview: {preview.page_count} pages, HTML length {len(preview.html)}")
