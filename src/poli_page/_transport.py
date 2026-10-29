"""Pure transport-layer helpers. No I/O, no httpx.

The sync and async clients orchestrate HTTP and call into these functions for
URL construction, header building, error-body parsing, retry math, and wire
(de)serialisation. Keeping I/O out lets retry/parsing logic be unit-tested
without HTTP — port of sdk-node/src/internal/http.ts.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, cast

from poli_page._constants import (
    CONTENT_TYPE_JSON,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    HEADER_CONTENT_TYPE,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_USER_AGENT,
    MESSAGE_DOWNLOAD_FAILED,
    MESSAGE_DOWNLOAD_FAILED_NETWORK,
    MESSAGE_TIMEOUT,
    RETRY_AFTER_CAP_SECONDS,
)

HttpMethod = Literal["GET", "POST", "DELETE"]

# The only input keys that reach a request body. Anything else a caller puts in
# the dict (`idempotency_key`, `timeout`, or a stray `version` / `environment`
# the API would reject with 400 VALIDATION_ERROR) stays client-side.
RENDER_WIRE_FIELDS: tuple[str, ...] = (
    "project",
    "template",
    "data",
    "metadata",
    "format",
    "orientation",
    "locale",
)
THUMBNAIL_WIRE_FIELDS: tuple[str, ...] = ("width", "format", "quality", "pages")


# ---------------------------------------------------------------------------
# URL + headers
# ---------------------------------------------------------------------------


def build_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def build_headers(
    method: HttpMethod,
    *,
    api_key: str,
    idempotency_key: str | None,
    user_agent: str,
) -> dict[str, str]:
    headers: dict[str, str] = {
        HEADER_ACCEPT: CONTENT_TYPE_JSON,
        HEADER_AUTHORIZATION: f"Bearer {api_key}",
        HEADER_USER_AGENT: user_agent,
    }
    if method == "POST":
        headers[HEADER_CONTENT_TYPE] = CONTENT_TYPE_JSON
        if idempotency_key:
            headers[HEADER_IDEMPOTENCY_KEY] = idempotency_key
    return headers


# ---------------------------------------------------------------------------
# API key masking — only ever called for human-readable output (repr, logs).
# Preserves the `pp_{env}_` prefix so operators can tell which environment a
# client points at, then truncates the secret portion. Environment names never
# contain `_`, so the second segment is always the whole environment name.
# ---------------------------------------------------------------------------


def mask_api_key(api_key: str) -> str:
    """Return a non-reversible, human-recognisable rendering of `api_key`.

    Keeps the first two underscore-separated segments when present (so
    `pp_sandbox_secret` → `pp_sandbox_***`), or falls back to `***` for very
    short or non-prefixed keys.
    """
    parts = api_key.split("_", 2)
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}_{parts[1]}_***"
    return "***"


# ---------------------------------------------------------------------------
# Retry math
# ---------------------------------------------------------------------------


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse a `Retry-After` header into seconds, clamped to 0-`RETRY_AFTER_CAP_SECONDS`.

    Accepts integer seconds or an HTTP-date (RFC 9110 §10.2.3). Returns `None`
    for a missing or unparseable value, so the backoff applies. A date in the
    past gives 0.
    """
    if not header_value:
        return None
    value = header_value.strip()
    if value.isascii() and value.isdigit():
        # Clamp on the digit count first: `int()` refuses very long strings and
        # `float()` overflows on huge ints, and any such value is past the cap.
        digits = value.lstrip("0") or "0"
        if len(digits) > 9:
            return RETRY_AFTER_CAP_SECONDS
        return min(float(int(digits)), RETRY_AFTER_CAP_SECONDS)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = (dt - datetime.now(UTC)).total_seconds()
    return min(max(delta, 0.0), RETRY_AFTER_CAP_SECONDS)


def compute_backoff(attempt: int, base_delay: float, retry_after: float | None) -> float:
    """Compute the delay before the next retry attempt in seconds.

    When `retry_after` is defined (including `0.0`), return it as-is — the
    server's instruction wins, no jitter. Otherwise apply exponential backoff
    `base_delay * 2^(attempt-1)` multiplied by a jitter factor in `[0.5, 1.5)`.
    `attempt` is 1-based: 1 means the first retry.
    """
    if retry_after is not None:
        return retry_after
    exp = base_delay * (2 ** (attempt - 1))
    jitter_factor = 0.5 + random.random()
    return exp * jitter_factor


def sleep_at_least(seconds: float) -> None:
    """Sleep `seconds`, sleeping again if the clock woke early, so a retry wait
    is never shorter than asked. `perf_counter`, not `monotonic`: on Windows
    before Python 3.13 `monotonic` ticks every 15.6 ms."""
    end = time.perf_counter() + seconds
    while (left := end - time.perf_counter()) > 0:
        time.sleep(left)


async def async_sleep_at_least(seconds: float) -> None:
    """The asyncio form of `sleep_at_least`."""
    end = time.perf_counter() + seconds
    while (left := end - time.perf_counter()) > 0:
        await asyncio.sleep(left)


# ---------------------------------------------------------------------------
# Error-body parsing
# ---------------------------------------------------------------------------


def parse_error_body(body: str, *, status: int) -> dict[str, str]:
    """Parse a non-2xx response body into `{code, message}` (SDK spec §8.2).

    Code: the body's `code`, else `error`, else `unknown_error`, copied
    verbatim; the SDK never infers one from the status or the message.
    Message: `detail`, else `title`, else `message`, else `HTTP <status>`.
    A body that is not a JSON object gives `INTERNAL_ERROR` and `HTTP <status>`;
    the caller keeps the real status.
    """
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return _internal_error(status)
    if not isinstance(raw, dict):
        return _internal_error(status)
    parsed = cast(dict[str, Any], raw)
    code: str = parsed.get("code") or parsed.get("error") or "unknown_error"
    message: str = (
        parsed.get("detail") or parsed.get("title") or parsed.get("message") or f"HTTP {status}"
    )
    return {"code": code, "message": message}


def _internal_error(status: int) -> dict[str, str]:
    return {"code": "INTERNAL_ERROR", "message": f"HTTP {status}"}


# ---------------------------------------------------------------------------
# SDK-side error messages (SDK spec §8.3)
# ---------------------------------------------------------------------------


def timeout_message(timeout_seconds: float) -> str:
    """`Request timed out after {timeoutMs}ms`, for the attempt's timeout."""
    return MESSAGE_TIMEOUT.format(timeoutMs=round(timeout_seconds * 1000))


def download_failed_message(status: int | None) -> str:
    """The `DOWNLOAD_FAILED` message: with the storage status, or the network one."""
    if status is None:
        return MESSAGE_DOWNLOAD_FAILED_NETWORK
    return MESSAGE_DOWNLOAD_FAILED.format(status=status)


# ---------------------------------------------------------------------------
# Wire (de)serialisation
# ---------------------------------------------------------------------------


def to_wire(input_dict: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Translate an SDK input dict into a wire-shaped body.

    Keeps only the top-level keys listed in `fields` and converts them from
    snake_case to camelCase. A key that is absent or `None` is omitted, never
    sent as `null`. Values pass through unchanged — `data` and `metadata`
    reach the wire with user-supplied keys intact.
    """
    out: dict[str, Any] = {}
    for key in fields:
        value = input_dict.get(key)
        if value is not None:
            out[_snake_to_camel(key)] = value
    return out


def from_wire(json_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a wire response into snake_cased keys for dataclass construction.

    Top-level only: `metadata` values reach the caller with the user-set keys
    intact (the server echoes them verbatim).
    """
    return {_camel_to_snake(key): value for key, value in json_dict.items()}


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
