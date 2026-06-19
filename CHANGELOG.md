# Changelog

All notable changes to `poli-page` (Python SDK) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Breaking changes between major versions are summarized in [MIGRATION.md](MIGRATION.md).

## [Unreleased]

## [0.9.0] - 2026-06-19

First public release (pre-1.0). Behavior parity with `@poli-page/sdk@1.0.0` (Node).

### Added

- **`PoliPage`** synchronous client + **`AsyncPoliPage`** asyncio-native client, parallel surfaces backed by `httpx.Client` / `httpx.AsyncClient`. Use either; the SDK does not auto-detect.
- **`render.*` namespace**: `pdf(input) → bytes`, `pdf_stream(input)` (sync / async context manager yielding chunks), `preview(input) → PreviewResult`, `document(input) → DocumentDescriptor`. `render.pdf` and `render.pdf_stream` make two HTTP calls (`POST /v1/render` + `GET presigned_pdf_url`) — the auto-download is an SDK convenience.
- **`documents.*` namespace**: `get(id)`, `preview(id)`, `thumbnails(id, options)`, `delete(id)`. All `{id}` segments URL-encoded.
- **`DocumentDescriptor.download_pdf()`** (sync) / **`AsyncDocumentDescriptor.download_pdf()`** (async) — fetch PDF bytes from the descriptor's `presigned_pdf_url`.
- **Project-mode enforcement**: `render.pdf` / `pdf_stream` / `document` reject inline-shaped input with `PoliPageError(code='PROJECT_REQUIRED_FOR_DOCUMENT')` before the HTTP call. `render.preview` accepts either mode. Type-level enforcement via `ProjectModeInput` / `InlineModeInput` TypedDicts.
- **`metadata`** pass-through on all render inputs; echoed verbatim on `DocumentDescriptor.metadata`.
- **`poli_page.fs.render_to_file`** + **`async_render_to_file`** — stream a PDF directly to disk; creates parent dirs, overwrites existing.
- **Auto-generated `Idempotency-Key`** (UUID4) on every POST; per-call override via `idempotency_key` in the input dict.
- **Retry policy**: 5xx, 429, network errors, timeouts. Exponential backoff with `[0.5, 1.5)` jitter; honors `Retry-After` and `Retry-After-Ms` (sub-second precision wins over seconds), capped at 30 s.
- **Typed error hierarchy** (`PoliPageError` base; `APIConnectionError` / `APITimeoutError` / `APIStatusError` with per-status subclasses for 400/401/403/404/409/410/422/429/5xx). Predicate helpers `is_auth_error` / `is_rate_limit_error` / `is_validation_error` / `is_network_error` / `is_retryable` kept for cross-language parity.
- **`error_codes`** module with named constants for every known API code (`MISSING_API_KEY`, `PAYMENT_REQUIRED`, `QUOTA_EXCEEDED`, …) and reserved SDK codes (`INVALID_OPTIONS`, `NETWORK_ERROR`, `TIMEOUT`, `ABORTED`, `UNKNOWN_ERROR`, `DOWNLOAD_FAILED`).
- **Observability**: silent-by-default `logging.getLogger('poli_page')` logger driven by `POLI_PAGE_LOG=debug|info|warning|error`. SDK-level hooks `on_retry` / `on_error` are sync callables; their exceptions never break the request. For request/response wiretapping, pass your own `httpx.Client` with `event_hooks={...}`.
- **Env-var fallbacks** mirroring `anthropic-sdk-python` / `openai-python`: `POLI_PAGE_API_KEY` (constructor falls back here when `api_key=` is omitted); `POLI_PAGE_BASE_URL` (default `https://api.poli.page`).
- **Context-manager lifecycle**: `with PoliPage(...) as client:` (sync) / `async with AsyncPoliPage(...) as client:` (async). Sockets close deterministically.
- **Injected `http_client`**: pass a pre-configured `httpx.Client` / `httpx.AsyncClient` for proxies, custom TLS, shared connection pools, or test transports. Caller-owned clients are not closed on `close()` / `aclose()`.
- **`py.typed`** marker — pyright `strict` and mypy `--strict` on `src/` are both green.
- **PyPI Trusted Publishing** workflow (tag-driven) for signed-attestation releases; pushing a `vX.Y.Z` tag publishes to PyPI, a manual run rehearses on TestPyPI. `scripts/release.sh` remains a local fallback.
- **Runnable demos** at `demo/sync_demo.py` and `demo/async_demo.py` — walk every public method end-to-end against the live API; outputs are byte-equivalent across sync / async.

### Contract

- **Wire format**: snake_case in Python, camelCase on the wire. The SDK translates at top level only — user-supplied `data` and `metadata` keys reach the wire and back verbatim.
- **Spec parity**: same retry policy, error codes, predicates, project-mode constraint, primitive-only `RenderMetadata`, thumbnails wire wrap/unwrap, and `documents.preview` text/html + `X-Document-Page-Count` parsing as `@poli-page/sdk@1.0.0`.

### Runtime requirements

- Python 3.11 or later.
- `httpx>=0.25,<1.0` — the only runtime dependency. No `pydantic`, no `typing-extensions`, no `requests`.
