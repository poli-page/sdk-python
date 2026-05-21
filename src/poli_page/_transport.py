"""Pure transport-layer helpers. No I/O, no httpx.

The sync and async clients orchestrate HTTP and call into these functions for
URL construction, header building, error-body parsing, retry math, and wire
(de)serialisation. Keeping I/O out lets retry/parsing logic be unit-tested
without HTTP — port of sdk-node/src/internal/http.ts.
"""

from __future__ import annotations

import json
import random
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
    RETRY_AFTER_CAP_SECONDS,
)

HttpMethod = Literal["GET", "POST", "DELETE"]

# Fields the SDK accepts at the top of an input dict but that must not reach
# the wire body. `idempotency_key` is promoted to the `Idempotency-Key` header;
# `timeout` is SDK-only (per-call deadline).
_NON_WIRE_FIELDS: frozenset[str] = frozenset({"idempotency_key", "timeout"})


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
# Retry math
# ---------------------------------------------------------------------------


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse a `Retry-After` header into seconds, capped at `RETRY_AFTER_CAP_SECONDS`.

    Accepts integer seconds or an HTTP-date. Returns `None` for missing or
    unparseable values. Past dates clamp to 0.
    """
    if not header_value:
        return None
    try:
        seconds = float(header_value)
    except ValueError:
        seconds = None
    if seconds is not None:
        return min(max(seconds, 0.0), RETRY_AFTER_CAP_SECONDS)
    try:
        dt = parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
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


# ---------------------------------------------------------------------------
# Error-body parsing
# ---------------------------------------------------------------------------


def parse_error_body(body: str, *, status: int) -> dict[str, str]:
    """Parse a non-2xx response body into `{code, message}`.

    Fallback chain: `code → message → error → 'unknown_error'`. Bodies that
    are not parseable JSON (or are valid JSON but not an object) surface as
    `INTERNAL_ERROR` with a status-bearing message.
    """
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return _internal_error(status)
    if not isinstance(raw, dict):
        return _internal_error(status)
    parsed = cast(dict[str, Any], raw)
    code: str = (
        parsed.get("code") or parsed.get("message") or parsed.get("error") or "unknown_error"
    )
    message: str = parsed.get("message") or f"API error ({status}): {code}"
    return {"code": code, "message": message}


def _internal_error(status: int) -> dict[str, str]:
    return {
        "code": "INTERNAL_ERROR",
        "message": f"API error {status}: response body was not valid JSON",
    }


# ---------------------------------------------------------------------------
# Wire (de)serialisation
# ---------------------------------------------------------------------------


def to_wire(input_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Translate an SDK input dict into a wire-shaped body.

    Top-level only: strips `idempotency_key` and `timeout`, converts remaining
    top-level snake_case keys to camelCase. Values pass through unchanged —
    `data` and `metadata` reach the wire with user-supplied keys intact.
    """
    out: dict[str, Any] = {}
    for key, value in input_dict.items():
        if key in _NON_WIRE_FIELDS:
            continue
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
