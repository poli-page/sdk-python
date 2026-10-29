# Changelog

All notable changes to `poli-page` (Python SDK) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Breaking changes are summarized in [MIGRATION.md](MIGRATION.md). While the package is on 0.x,
a breaking change bumps the minor version.

## [Unreleased]

Conformance with the Poli Page API contract v1.1.0
([poli-page/api-contract](https://github.com/poli-page/api-contract)). See
[MIGRATION.md](MIGRATION.md#from-0100-to-the-next-release-unreleased).

### Changed

- **Breaking:** `QUOTA_EXCEEDED` and `OVERAGE_CAP_EXCEEDED` (429) and `STORAGE_ACCESS_DENIED`
  (502) are no longer retried, even with a `Retry-After` header, and `is_retryable()` now
  returns `False` for them (it returned `True` for any 429 or 5xx). They last until the monthly
  reset or until the bucket access is restored, so the SDK used to wait up to 30 s per retry
  for nothing. `RATE_LIMIT_EXCEEDED` and every other 429 and 5xx are still retried. Code that
  requeues on `is_retryable()` stops requeueing these three.
- **Breaking:** the `Retry-After-Ms` response header is ignored; only `Retry-After` sets the
  delay before a retry (it used to win over `Retry-After`). Without `Retry-After` the
  exponential backoff applies.
- `Retry-After` is read as integer seconds or an HTTP-date only. Any other value (`1.5`, `-1`,
  `soon`) falls back to the backoff instead of being parsed as a float.
- **Breaking:** an explicit empty `api_key=""` raises `invalid_options`, on `PoliPage`,
  `AsyncPoliPage` and `with_options`. It used to fall back to `POLI_PAGE_API_KEY`; the
  environment variable now stands in only for an omitted key (`api_key=None`).
- **Breaking:** the error predicates read `status` and `code`, as the SDK specification
  defines them, instead of the exception class: `is_auth_error()` is `status` 401 or 403,
  `is_rate_limit_error()` 429, `is_validation_error()` 400, `is_network_error()` is `code`
  `network_error` or `timeout`, and `is_retryable()` is a network error, a timeout, a 5xx or a
  429 outside the never-retried codes. For API errors only the never-retried codes change.
  A `DOWNLOAD_FAILED` now follows the storage's status: 403 (and 401) is an auth error, 400 a
  validation error, 429 a rate-limit error, and a 5xx or 429 makes `is_retryable()` `True`
  (it was `False` for every `DOWNLOAD_FAILED`). The SDK still never retries the download
  itself, but code that requeues on `is_retryable()` now requeues a download that storage
  refused with a 5xx or 429. A download with no status (network error) stays non-retryable.
- SDK error messages are the exact texts of the SDK specification:
  - `invalid_options`: `apiKey is required` (was
    `api_key is required (pass api_key= or set POLI_PAGE_API_KEY)`).
  - `network_error`: `Network request failed` (was the httpx exception text); the httpx
    exception is still the error's `__cause__`.
  - `timeout`: `Request timed out after <ms>ms`, with the attempt's timeout in milliseconds,
    the per-call `timeout` when one is set (was `Request timed out after <s>s` with the
    client's timeout in seconds).
  - `DOWNLOAD_FAILED`: `Failed to download PDF: HTTP <status>` (was
    `Failed to download PDF: <status>`), and `Failed to download PDF: network error` when the
    download gets no answer (was the httpx exception text, now its `__cause__`).
  - A non-JSON error body: `HTTP <status>` (was
    `HTTP <status>: response body was not valid JSON`); the code is still `INTERNAL_ERROR`
    with the real status.
  - `PROJECT_REQUIRED_FOR_DOCUMENT` raised before any request: `project is required`.

### Fixed

- The "Retries and idempotency" docs page no longer says the API deduplicates on
  `Idempotency-Key`: it does not, so a render retried after a late 5xx can store a second
  document. The SDK sends one stable key across the retries of a call.
- A `Retry-After: nan` header no longer makes the sync client's retry sleep raise a raw
  `ValueError`: the value is unparseable and the backoff applies.

### Added

- `tests/test_contract.py` runs every SDK case of the API contract against a local mock server,
  with both `PoliPage` and `AsyncPoliPage`; CI pins the contract by commit
  (`poli-page/api-contract` action) and Dependabot proposes each new version. Run it locally
  with `POLI_CONTRACT=<path to contract.json> pytest`.

## [0.10.0] - 2026-10-27

Environments contract: a key carries its environment (`pp_{env}_…`), versions and the
authenticated preview are gone. Breaking, with no deprecation window. See
[MIGRATION.md](MIGRATION.md#from-09x-to-0100).

### Removed

- **`render.preview`** (sync and async) and its **`PreviewResult`** type: the API removed
  `POST /v1/render/preview` (it now answers `404`). `documents.preview(id)` stays.
- **Inline-HTML rendering** and the **`InlineModeInput`** type: the API answers an inline
  `template` with `400 VALIDATION_ERROR`.
- The **`version`** render input field and the **`version`** field of `DocumentDescriptor` /
  `AsyncDocumentDescriptor`: a render uses the project's copy published in the key's
  environment.
- Error-code constants `VERSION_NOT_FOUND`, `INVALID_VERSION_FORMAT`, `VERSION_REQUIRED`,
  `INVALID_VERSION_FOR_KEY_ENV`, `MISSING_PROJECT_OR_TEMPLATE`, `GONE` (the API answers
  `410 DOCUMENT_GONE`) and `PAYMENT_REQUIRED` (payment grace is
  `403 ORGANIZATION_PAYMENT_GRACE`).

### Changed

- **`ProjectModeInput` is renamed `RenderInput`** and is the only render input type.
- The render body is built from `project`, `template`, `data`, `metadata`, `format`,
  `orientation` and `locale` only: any other key in the input dict (such as `version` or
  `environment`) is no longer sent, and an unset or `None` field is omitted, not sent as `null`.
- **`Environment`** is now `str`: `DocumentDescriptor.environment` is any environment name the
  API returns (`sandbox`, `live`, `staging`, …), passed through unchanged.
- **`documents.thumbnails(id, options=None)`**: every `ThumbnailOptions` key is optional
  (`width` is no longer required), `format` accepts `"webp"` besides `"jpeg"` and `"png"`,
  and with no option set the request body is `{}` (the API defaults to 400 px `jpeg`).
  Only `width`, `format`, `quality` and `pages` are sent.
- `documents.delete` is documented as idempotent: the API answers `204` for an
  already-deleted document.
- Docstrings use `pp_sandbox_…` keys; `pp_test_…` keys no longer exist.
- **README and docs site**: the quick start renders `getting-started`/`welcome` with a
  `sandbox` key and no version. "Authentication & environments" carries the key table
  (`sandbox` / `live` / created environments), the sandbox properties (watermarked, not
  counted, 30-day expiry), the `poli-watermark` note and the full-key regex. The preview /
  inline-HTML sections are replaced by a link to the playground, https://play.poli.page.
  The "Render modes" docs page is now "Render input". The error tables list the current
  codes.
- **Demos** (`demo/sync_demo.py`, `demo/async_demo.py`): they ask for a `sandbox` key and
  check a pasted key against the full-key regex only, render `getting-started`/`welcome`
  with no version, drop the `render.preview` step and end with the `not-found` step
  (template `does-not-exist`, `404 TEMPLATE_NOT_FOUND`), which prints the error's `code`,
  `status`, `message` and `request_id`; any other error, or a render that succeeds, ends the
  demo with exit status 1. Nine steps instead of ten. An empty
  `POLI_PAGE_API_KEY` or `POLI_PAGE_BASE_URL` counts as unset.
- **Integration workflow**: `POLI_PAGE_TEST_VERSION` is gone. The key comes from the
  `POLI_PAGE_API_KEY` secret (a `pp_sandbox_` key) and the optional base URL from the
  `POLI_PAGE_TEST_BASE_URL` secret.

### Added

- Error-code constants `PUBLISH_IN_PROGRESS`, `ENVIRONMENT_MISMATCH`,
  `PROJECT_NOT_IN_ENVIRONMENT`, `TEMPLATE_NOT_FOUND`, `DOCUMENT_GONE`, `ENVIRONMENT_PROTECTED`,
  `ORGANIZATION_PAYMENT_GRACE`, `EMPTY_DOCUMENT`, `STORAGE_ACCESS_DENIED`,
  `ORGANIZATION_MIGRATING`, `PROJECT_NOT_FOUND`, `TEMPLATE_ERROR`, `THUMBNAILS_NOT_AVAILABLE`,
  `RATE_LIMIT_EXCEEDED`, `RENDER_BODY_TOO_LARGE`, `DOCUMENT_TOO_LARGE` and `RENDER_TIMEOUT`.
  An error code the SDK does not list still reaches `err.code` verbatim.
- A render that meets a publish in progress (`503 PUBLISH_IN_PROGRESS` with `Retry-After`) is
  retried by the existing policy, then surfaces with that code.

### Fixed

- The `on_retry` examples in the README, the docs site and the demos read `event.delay_ms`.
  They used `event.delay_seconds`, which `RetryEvent` does not have.

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
