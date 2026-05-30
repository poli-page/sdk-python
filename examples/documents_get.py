# Demonstrates: client.documents.get(id) — fetch a stored document.
from poli_page import PoliPage

client = PoliPage()

document = client.documents.get("doc_abc123")

print(
    f"Document {document.document_id}: {document.page_count} pages, "
    f"created {document.created_at}"
)

# `presigned_pdf_url` has a 15-minute TTL. Call download_pdf() to fetch bytes
# before it expires, or call documents.get(id) again to refresh.
pdf = document.download_pdf()
print(f"Downloaded {len(pdf)} bytes")
