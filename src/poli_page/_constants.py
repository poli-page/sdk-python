"""SDK-wide constants. Tests import from here rather than retyping literals.

The Node SDK inlines these values; the Python port centralises them so a
path change or default tweak is a one-line edit (plan §17).
"""

from __future__ import annotations

from urllib.parse import quote

# Defaults --------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.poli.page"
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 60.0
RETRY_AFTER_CAP_SECONDS = 30.0

# Retry policy (SDK spec §9.1) ----------------------------------------------

# Never retried, even on a 429 / 5xx with `Retry-After`: they last until the
# monthly reset or until the bucket access is restored, so waiting cannot help.
NON_RETRYABLE_CODES: frozenset[str] = frozenset(
    {"QUOTA_EXCEEDED", "OVERAGE_CAP_EXCEEDED", "STORAGE_ACCESS_DENIED"}
)

# SDK-side error messages (SDK spec §8.3) -----------------------------------
# Exact texts, the same in every Poli Page SDK. `{timeoutMs}` is the attempt's
# timeout in milliseconds, `{status}` the storage status of a failed download.

MESSAGE_INVALID_OPTIONS = "apiKey is required"
MESSAGE_NETWORK_ERROR = "Network request failed"
MESSAGE_TIMEOUT = "Request timed out after {timeoutMs}ms"
MESSAGE_DOWNLOAD_FAILED = "Failed to download PDF: HTTP {status}"
MESSAGE_DOWNLOAD_FAILED_NETWORK = "Failed to download PDF: network error"
MESSAGE_PROJECT_REQUIRED = "project is required"

# Headers ---------------------------------------------------------------

USER_AGENT_PREFIX = "poli-page-sdk-python"

HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_USER_AGENT = "User-Agent"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_REQUEST_ID = "x-request-id"
HEADER_RETRY_AFTER = "Retry-After"
HEADER_DOCUMENT_PAGE_COUNT = "X-Document-Page-Count"

CONTENT_TYPE_JSON = "application/json"

# API paths -------------------------------------------------------------

PATH_RENDER = "/v1/render"


def path_document(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}"


def path_document_preview(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}/preview"


def path_document_thumbnails(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}/thumbnails"
