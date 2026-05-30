# Demonstrates: client.render.pdf_stream(input) — project mode only.
from poli_page import PoliPage

client = PoliPage()

# `pdf_stream` returns a context manager yielding chunks of bytes.
total = 0
with client.render.pdf_stream({
    "project": "billing",
    "template": "invoice",
    "data": {"invoiceNumber": "INV-001", "total": 1280},
}) as chunks:
    for chunk in chunks:
        total += len(chunk)

print(f"Streamed {total} bytes")
