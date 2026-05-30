# Demonstrates: render_to_file(client, input, path) from poli_page.fs.
from poli_page import PoliPage
from poli_page.fs import render_to_file

client = PoliPage()

render_to_file(
    client,
    {
        "project": "billing",
        "template": "invoice",
        "data": {"invoiceNumber": "INV-001", "total": 1280},
    },
    "./invoices/INV-001.pdf",
)

# Streams response bytes directly to disk with bounded memory.
# Parent directories are created automatically.
print("Wrote ./invoices/INV-001.pdf")
