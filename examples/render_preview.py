# Demonstrates: client.render.preview(input) — accepts project mode OR inline mode.
from poli_page import PoliPage

client = PoliPage()

# Project mode: render the stored template's HTML preview.
preview = client.render.preview({
    "project": "billing",
    "template": "invoice",
    "data": {"invoiceNumber": "INV-001", "total": 1280},
})

print(f"Preview: {preview.total_pages} pages, {preview.environment} env")
print(f"HTML length: {len(preview.html)}")
