# Demonstrates: client.documents.delete(id) — soft-delete a stored document.
from poli_page import PoliPage

client = PoliPage()

client.documents.delete("doc_abc123")

# Returns None. The PDF is purged; metadata is retained for audit.
print("Deleted.")
