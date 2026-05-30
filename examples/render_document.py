# Demonstrates: client.render.document(input) — render and store a PDF server-side.
from poli_page import PoliPage

client = PoliPage()

document = client.render.document({
    "project": "billing",
    "template": "invoice",
    "data": {"invoiceNumber": "INV-001", "total": 1280},
    "metadata": {"customerId": "cust_42"},
})

# `document.document_id` identifies the stored document — use it with
# client.documents.* to fetch, preview, thumbnail, or delete later.
print(
    f"Stored as {document.document_id} "
    f"({document.page_count} pages, {document.size_bytes} bytes)"
)

# Fetch the PDF bytes on demand:
pdf = document.download_pdf()
print(f"Downloaded {len(pdf)} bytes")
