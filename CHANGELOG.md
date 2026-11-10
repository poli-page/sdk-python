# Changelog

All notable changes to `poli-page` (Python SDK) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Breaking changes are summarized in [MIGRATION.md](MIGRATION.md). While the package is on 0.x,
a breaking change bumps the minor version.

## [Unreleased]

### Changed

- **README and docs site**: the "Error handling" section and the "Errors" page name
  `TEMPLATE_UNSAFE` (400): the template, a partial or an SVG asset holds script or another
  injection attempt, and the error's message names the first construct found. Not retried.

## [0.13.0] - 2026-11-02

Conformance with the Poli Page API contract v0.13.0
([poli-page/api-contract](https://github.com/poli-page/api-contract)). The SDK now shares its
major.minor with the Poli Page API, so it moves from 0.11 to 0.13 (see
[RELEASING.md](RELEASING.md#versions)). See [MIGRATION.md](MIGRATION.md#from-0110-to-0130).

### Added

- `invalid_response`: a 2xx answer whose body is not JSON, from a method that expects JSON
  (the render call of `render.document`, `render.pdf` and `render.pdf_stream`,
  `documents.get`, `documents.thumbnails`), raises `InvalidResponseError`, a new
  `PoliPageError` subclass exported from `poli_page`: code `invalid_response`, message
  `Invalid response: HTTP <status> body is not JSON`, the real 2xx as `status`, the answer's
  `x-request-id` as `request_id`, and the `json.JSONDecodeError` as `__cause__`. It is never
  retried, `is_retryable()` is `False`, and `on_error` fires with it. Such a body usually comes
  from a proxy or a captive portal between the SDK and the API. Same in both clients.
- `io_error`: `render_to_file()` and `async_render_to_file()` raise it when they cannot write
  the file (creating a parent directory, creating the temporary file, writing it or renaming it
  into place). No status, the message `Failed to write PDF: <target>: <reason>`, with the path
  as you gave it and the `OSError`'s own text (never the temporary file's name), that
  `OSError` as `__cause__`, never retried.
- `error_codes.INVALID_RESPONSE` and `error_codes.IO_ERROR`.
- `to_payload()` answers `status` 502 for `invalid_response`. The error's own `status` keeps
  the real 2xx. The payload has exactly the keys `code`, `message`, `status` and `requestId`, as
  before.
- `scripts/release.sh` and the Publish workflow check that the API contract pinned for the
  tests has the release's major.minor.

### Changed

- **Breaking:** a 2xx whose body is not JSON raised a raw `json.JSONDecodeError`, outside
  `PoliPageError`; it is now `InvalidResponseError` (above).
- **Breaking:** `render_to_file()` and `async_render_to_file()` raised the `OSError` itself
  when they could not write the file; they now raise `io_error` (above).
- `render_to_file()` and `async_render_to_file()` write to a temporary file in the target's
  directory and rename it over the target only once the PDF is complete. When anything fails
  (the render, the download or the write), the target is left as it was: an existing file keeps
  its content and a missing one is not created. The directory and the temporary file are
  prepared before the render, so a path that cannot be written costs no render, and input
  without a `project` is refused before anything is created on disk. An existing target that
  is not a regular file (a directory, a FIFO, a device, a socket) raises `io_error` with
  `Failed to write PDF: <target>: not a regular file`, and one you cannot write raises
  `io_error` with the `PermissionError`, both before the render and without replacing it.
- **Breaking:** `render_to_file()` and `async_render_to_file()` replace the target by a rename
  instead of rewriting it in place. The new file is owned by the user running the SDK, not the
  old file's owner, and any other hard link to the old file keeps the old content. The
  permission mode is kept.
- A symlinked target is resolved first, each link relative to its own real directory: the PDF
  replaces the file the link points to (created if missing) and the link stays a link.
- **Breaking:** the presigned-URL download is bounded by the client's `timeout`, or the render
  call's own `timeout` for `render.pdf` and `render.pdf_stream`. Before, httpx's per-operation
  timeouts applied (those of the `http_client` you passed, if any), so a download that kept
  receiving bytes slowly never timed out. For `render.pdf` and `download_pdf()`, the timeout
  bounds the whole download, so a download longer than `timeout` (60 s by default) that used
  to succeed now fails: raise `timeout` for large PDFs on slow links. For `render.pdf_stream`
  (and the file helpers), it is an idle
  timeout: the first byte comes at most `timeout` after the download request started (the
  answer's headers and the first chunk share that budget), and each later gap between two
  chunks is bounded by `timeout`, so a large PDF read at the caller's pace is not cut off.
- The sync client runs a whole download, and the start of a stream, on a worker thread, so that
  the call can stop waiting on time: httpx's sync transport cannot be interrupted. A sync
  download that timed out can keep one pooled connection busy after the call has failed,
  until its current httpx phase ends (each phase, such as the connection or a read, is bounded
  by httpx's own per-operation `timeout`). The worker then stops at its next step and releases
  the connection. The async client cancels the download at once.
- A download that outlasts its timeout raises `DOWNLOAD_FAILED` with the message
  `Failed to download PDF: timeout` (was `Failed to download PDF: network error`). No status,
  not retryable. A download whose connection closes before the announced `Content-Length` is
  still `Failed to download PDF: network error`.
- **Breaking:** `render.pdf_stream` raises `DOWNLOAD_FAILED` from the chunk iterator when the
  download fails mid-stream. It used to raise the httpx exception inside the `with` block and
  convert it only when the block exited, so an `except httpx.HTTPError` around the loop no
  longer sees it, and an httpx error raised by your own code inside the block is no longer
  turned into `DOWNLOAD_FAILED`.
- A `timeout` of 0 or less still goes to httpx as it is, for API calls and downloads alike;
  the SDK adds no deadline of its own for it.

## [0.11.0] - 2026-10-30

Conformance with the Poli Page API contract v1.3.0
([poli-page/api-contract](https://github.com/poli-page/api-contract)). See
[MIGRATION.md](MIGRATION.md#from-0100-to-0110).

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
  validation error and 429 a rate-limit error. It is never retryable, whatever the storage
  status: `is_retryable()` is `False` for it (contract v1.3.0).
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
  `Idempotency-Key`: it does not, so a render retried after a late 5xx, a `timeout` or a
  `network_error` can store a second document. The SDK sends one stable key across the
  retries of a call.
- A retry wait is never shorter than asked: a sleep that wakes early sleeps again for the
  rest of the delay (sync and async clients).
- A `Retry-After: nan` header no longer makes the sync client's retry sleep raise a raw
  `ValueError`: the value is unparseable and the backoff applies.

### Added

- Known error code `TEMPLATE_UNSAFE` (400): the template, a partial or an SVG asset holds an
  injection attempt; `detail` names it. Not retried.
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
