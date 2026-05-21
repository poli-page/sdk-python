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

# Headers ---------------------------------------------------------------

USER_AGENT_PREFIX = "poli-page-sdk-python"

HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_USER_AGENT = "User-Agent"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_REQUEST_ID = "x-request-id"
HEADER_RETRY_AFTER = "Retry-After"
HEADER_RETRY_AFTER_MS = "Retry-After-Ms"
HEADER_DOCUMENT_PAGE_COUNT = "X-Document-Page-Count"

CONTENT_TYPE_JSON = "application/json"

# API paths -------------------------------------------------------------

PATH_RENDER = "/v1/render"
PATH_RENDER_PREVIEW = "/v1/render/preview"


def path_document(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}"


def path_document_preview(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}/preview"


def path_document_thumbnails(document_id: str) -> str:
    return f"/v1/documents/{quote(document_id, safe='')}/thumbnails"
