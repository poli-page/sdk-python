# Demonstrates: client.documents.delete(id) — soft-delete a stored document.
from poli_page import PoliPage

client = PoliPage()

client.documents.delete("doc_abc123")

# Returns None, also for an already-deleted document (deletes are idempotent).
# The PDF is purged; metadata is retained for audit.
print("Deleted.")
