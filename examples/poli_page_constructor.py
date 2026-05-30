# Demonstrates: PoliPage(...) — the only entry point.
import os

from poli_page import PoliPage

client = PoliPage(
    api_key=os.environ["POLI_PAGE_API_KEY"],
    timeout=60.0,
    max_retries=2,
)

# The same `client` instance is reused for every render and document call.
_ = client
