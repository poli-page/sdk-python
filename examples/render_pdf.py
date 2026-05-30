# Demonstrates: client.render.pdf(input) — project mode only.
from poli_page import PoliPage

client = PoliPage()  # picks up POLI_PAGE_API_KEY from the environment

pdf = client.render.pdf({
    "project": "billing",
    "template": "invoice",
    "data": {"invoiceNumber": "INV-001", "total": 1280},
})

# `pdf` is a `bytes` object containing the PDF.
print(f"Rendered {len(pdf)} bytes")
