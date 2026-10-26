# Poli Page SDK for Python

[![Pypi](https://img.shields.io/pypi/v/poli-page?style=flat&logo=python&logoColor=ffffff&label=Pypi&cacheSeconds=3600)](https://pypi.org/project/poli-page/)
[![Downloads](https://img.shields.io/pypi/dm/poli-page?style=flat&logo=python&logoColor=ffffff&label=Downloads&cacheSeconds=3600)](https://pypi.org/project/poli-page/)
[![Ci](https://img.shields.io/github/actions/workflow/status/poli-page/sdk-python/ci.yml?branch=main&style=flat&logo=githubactions&logoColor=ffffff&label=Ci)](https://github.com/poli-page/sdk-python/actions/workflows/ci.yml)
[![Codeql](https://img.shields.io/github/actions/workflow/status/poli-page/sdk-python/codeql.yml?branch=main&style=flat&logo=github&logoColor=ffffff&label=Codeql)](https://github.com/poli-page/sdk-python/actions/workflows/codeql.yml)
[![Coverage](https://img.shields.io/codecov/c/github/poli-page/sdk-python?style=flat&logo=codecov&logoColor=ffffff&label=Coverage)](https://codecov.io/gh/poli-page/sdk-python)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue?style=flat&logo=python&logoColor=ffffff)](https://github.com/poli-page/sdk-python)
[![Types](https://img.shields.io/badge/Types-py.typed-blue?style=flat&logo=python&logoColor=ffffff)](https://peps.python.org/pep-0561/)
[![Linter](https://img.shields.io/badge/Linter-Ruff-blue?style=flat&logo=python&logoColor=ffffff)](https://github.com/astral-sh/ruff)
[![Deps](https://img.shields.io/badge/Deps-up%20to%20date-brightgreen?style=flat&logo=python&logoColor=ffffff)](https://github.com/poli-page/sdk-python/network/dependencies)
[![Docs](https://img.shields.io/badge/Docs-online-brightgreen?style=flat&logo=readthedocs&logoColor=ffffff)](https://poli-page.github.io/sdk-python/)
[![License](https://img.shields.io/github/license/poli-page/sdk-python?style=flat&logo=gnu&logoColor=ffffff&label=License)](LICENSE)

Official Python SDK for [Poli Page](https://poli.page) — render polished PDFs from HTML templates via the Poli Page API.

→ API reference (auto-generated from source): **https://poli-page.github.io/sdk-python/**

## Install

```bash
pip install poli-page
```

Requires Python 3.11 or later.

## Quick start

### Render a template by slug

Set `POLI_PAGE_API_KEY` to a `sandbox` key of a fresh organization (`pp_sandbox_…`, see [Authentication & environments](#authentication--environments)), then:

```python
from poli_page import PoliPage

client = PoliPage()  # reads POLI_PAGE_API_KEY from the environment

pdf = client.render.pdf(
    {
        "project": "getting-started",
        "template": "welcome",
        "data": {"name": "SDK Demo"},
    }
)
# pdf is bytes
```

Every organization gets a `getting-started` project, published into its `sandbox` environment when the organization is created, with a `welcome` template. A sandbox key renders it with no setup, so the snippet above runs as-is on a fresh organization. It is a normal, editable project: in an organization that renamed it, deleted it or removed it from `sandbox`, the API answers `404 PROJECT_NOT_FOUND` or `404 PROJECT_NOT_IN_ENVIRONMENT`, so use a fresh organization to follow along.

There is no version to pick: a render uses the project's copy published in the API key's environment. For your own templates, publish the project to the environment of the key you render with, then swap the slugs:

```python
pdf = client.render.pdf(
    {
        "project": "billing",
        "template": "invoice",
        "data": {"invoice_number": "INV-001", "total": 1280},
    }
)
```

To preview a template or render inline HTML while you design it, use the playground: <https://play.poli.page>. The API and this SDK render published templates only.

### Async client

Every method is mirrored on `AsyncPoliPage` for asyncio code — same constructor, same options, same return shapes:

```python
import asyncio
from poli_page import AsyncPoliPage


async def main():
    async with AsyncPoliPage() as client:  # reads POLI_PAGE_API_KEY
        pdf = await client.render.pdf(
            {
                "project": "getting-started",
                "template": "welcome",
                "data": {"name": "SDK Demo"},
            }
        )


asyncio.run(main())
```

Pick the variant at construction time. The SDK does not auto-detect "am I in an async context" — that pattern bites later.

### Write a PDF to disk

```python
from poli_page import PoliPage
from poli_page.fs import render_to_file

client = PoliPage()  # reads POLI_PAGE_API_KEY
render_to_file(
    client,
    {
        "project": "getting-started",
        "template": "welcome",
        "data": {"name": "SDK Demo"},
    },
    "./welcome.pdf",
)
```

`render_to_file` streams response bytes directly to disk (bounded memory). Creates parent directories; overwrites existing files. The async variant is `poli_page.fs.async_render_to_file`.

### Try it locally — runnable demos

The repo ships two end-to-end demos that exercise every public method against the real API:

```bash
python demo/sync_demo.py     # synchronous client
python demo/async_demo.py    # asynchronous client
```

The demos render `getting-started`/`welcome`. First run prompts for a `sandbox` key (`pp_sandbox_…`) and saves it to `.env` at the repo root. Subsequent runs are silent. The `POLI_PAGE_API_KEY` env var wins over the file when set; `POLI_PAGE_BASE_URL` (optional) overrides the API host. Outputs land in `demo/output-sync/` and `demo/output-async/`.

Each demo walks nine steps: `render.pdf` → `render.pdf_stream` → `render_to_file` (async: `async_render_to_file`) → `render.document` → `documents.get` → `documents.thumbnails` → `documents.preview` → `documents.delete` → `not-found` (a render of a template that does not exist, caught as `NotFoundError` with code `TEMPLATE_NOT_FOUND`). See [`demo/README.md`](demo/README.md).

### Stream — for large PDFs or piping to S3 / HTTP responses

```python
with client.render.pdf_stream(
    {
        "project": "billing",
        "template": "invoice",
        "data": {"invoice_number": "INV-001"},
    }
) as stream:
    with open("invoice.pdf", "wb") as fh:
        for chunk in stream:
            fh.write(chunk)
```

The context manager closes the underlying HTTP response deterministically. The async client returns an `async with` / `async for`-able equivalent.

## Working with stored documents

Every render produces a stored document, accessible via `document_id` for later download or thumbnails. `render.pdf` and `render.pdf_stream` are conveniences that chain a presigned-URL fetch internally to return bytes; `render.document` returns just the descriptor (skip the auto-download when you'll fetch the bytes later).

```python
# 1. Render and store
doc = client.render.document(
    {
        "project": "billing",
        "template": "invoice",
        "data": {"invoice_number": "INV-001"},
        "metadata": {"customer_id": "cust_123"},  # your own audit data
    }
)
# doc.document_id, doc.page_count, doc.size_bytes, doc.presigned_pdf_url, doc.metadata, ...

# 2. Save doc.document_id in your database
db.invoices.update(id="INV-001", document_id=doc.document_id)

# 3. Later, fetch a fresh presigned URL + download
fresh = client.documents.get(doc.document_id)
pdf = fresh.download_pdf()

# 4. Generate thumbnails
thumbs = client.documents.thumbnails(doc.document_id, {"width": 320, "format": "png"})

# 5. When done, soft-delete
client.documents.delete(doc.document_id)
```

The presigned URL has a 15-minute TTL. If `download_pdf()` fails with `code='DOWNLOAD_FAILED'` (HTTP 403 from S3), call `documents.get(id)` to refresh and retry.

## Authentication & environments

An API key belongs to exactly one environment of your organization, and its text names that environment: a key is `pp_{env}_{32 lowercase hex}`, matching

```text
^pp_(?=[a-z][a-z0-9-]{0,19}_)[a-z][a-z0-9]*(?:-[a-z0-9]+)*_[0-9a-f]{32}$
```

The API resolves the environment from the key and renders the project's copy published there; the SDK never sends an environment.

| Environment                           | Key            | Watermark | Counted |
| ------------------------------------- | -------------- | --------- | ------- |
| `sandbox` (every org)                 | `pp_sandbox_…` | yes       | no      |
| `live` (every org, deletable on Pro+) | `pp_live_…`    | no        | yes     |
| created on Pro+ (e.g. `staging`)      | `pp_staging_…` | no        | yes     |

"Counted" means the render counts toward the organization's monthly PDF quota. `sandbox` renders are watermarked, are not counted, and their documents expire 30 days after creation. There is no watermark option: a template that wants a watermark outside `sandbox` uses the `poli-watermark` class.

Standard and service keys share this one format. Every key hits the same endpoint, `https://api.poli.page` by default or whatever you pass as `base_url` (see [Configuration](#configuration)). The SDK passes the key through as a `Bearer` token and does not check its format.

### Environment variables

Configure without hard-coding:

| Variable | Purpose |
| -------- | ------- |
| `POLI_PAGE_API_KEY` | Used when `api_key=` is omitted on the constructor |
| `POLI_PAGE_BASE_URL` | Used when `base_url=` is omitted (default `https://api.poli.page`) |
| `POLI_PAGE_LOG` | `debug` / `info` / `warning` / `error` — sets the `poli_page` logger level on import |

## Methods

| Method | Returns | Description |
| ------ | ------- | ----------- |
| `client.render.pdf(input)` | `bytes` | Render a PDF, return bytes |
| `client.render.pdf_stream(input)` | context manager yielding `bytes` chunks | Render and stream the response |
| `client.render.document(input)` | `DocumentDescriptor` | Render and return descriptor (skip auto-download) |
| `client.documents.get(id)` | `DocumentDescriptor` | Retrieve a stored document |
| `client.documents.preview(id)` | `DocumentPreviewResult` | Stored document's paginated HTML |
| `client.documents.thumbnails(id, options=None)` | `list[Thumbnail]` | Page thumbnails (JPEG/PNG/WebP, base64) |
| `client.documents.delete(id)` | `None` | Soft-delete a stored document (idempotent) |
| `render_to_file(client, input, path)` *(from `poli_page.fs`)* | `None` | Render and stream to disk |

Every method above also exists on `AsyncPoliPage` (with `async def` / `await`); helpers are `poli_page.fs.async_render_to_file` and `AsyncDocumentDescriptor.download_pdf` (async).

## Configuration

| Option | Type | Default | Description |
| ------ | ---- | ------- | ----------- |
| `api_key` | str | (`POLI_PAGE_API_KEY` env var) | API key of one environment (`pp_{env}_…`) |
| `base_url` | str | `https://api.poli.page` | API base URL |
| `max_retries` | int | 2 | Max retry attempts on retryable errors |
| `retry_delay` | float (seconds) | 0.5 | Base delay before the first retry |
| `timeout` | float (seconds) | 60.0 | Per-request timeout |
| `on_retry` | callable | — | Called before each retry sleep with a `RetryEvent` |
| `on_error` | callable | — | Called when a call terminates in error with a `PoliPageError` |
| `http_client` | `httpx.Client` (or `AsyncClient`) | — | Inject a pre-configured httpx client (proxies, custom TLS, shared pool) |

> **Unit note**: `retry_delay` and `timeout` are **seconds** (Python idiom). The Node SDK uses milliseconds; if you're porting from that, divide by 1000.

### Branching with `with_options`

When you need different settings for a single call (a longer timeout for a heavy render, fewer retries on a webhook-driven path), branch the client instead of reconstructing it:

```python
slow_client = client.with_options(timeout=120.0, max_retries=5)
pdf = slow_client.render.pdf(
    {"project": "billing", "template": "yearly-report", "data": {...}}
)
```

`with_options` returns a **new** client; unspecified options inherit from the original. The branch owns its own connection pool, so closing one does not close the other. The async client exposes the same method on `AsyncPoliPage`.

## Error handling

The SDK ships a typed error hierarchy. Catch the broad base (`PoliPageError`) or the specific subclass — both work:

```python
from poli_page import (
    PoliPage,
    PoliPageError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    BadRequestError,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)

try:
    client.render.pdf({...})
except RateLimitError:
    queue_for_later()
except AuthenticationError:
    refresh_credentials()
except PoliPageError as err:
    if err.is_retryable():
        # SDK already retried up to max_retries
        ...
    print(err.code, err.status, err.request_id)
```

The hierarchy:

```
PoliPageError                       # base — catches everything
├── APIConnectionError              # transport-level (no status)
│   └── APITimeoutError             # per-request deadline exceeded
└── APIStatusError                  # any non-2xx (carries status)
    ├── BadRequestError             (400)
    ├── AuthenticationError         (401)
    ├── PermissionDeniedError       (403)
    ├── NotFoundError               (404)
    ├── ConflictError               (409)
    ├── GoneError                   (410)
    ├── UnprocessableEntityError    (422)
    ├── RateLimitError              (429)
    └── InternalServerError         (5xx)
```

Predicate helpers are kept for cross-language parity:

- `err.is_auth_error()` — 401 or 403
- `err.is_rate_limit_error()` — 429
- `err.is_validation_error()` — 400
- `err.is_network_error()` — any `APIConnectionError` (includes timeout)
- `err.is_retryable()` — 5xx, 429, network, or timeout

For lifecycle and billing failures, route the user to actionable messages:

```python
from poli_page import error_codes

try:
    client.render.document({...})
except PoliPageError as err:
    if err.code == error_codes.ORGANIZATION_PAYMENT_GRACE:
        return show_banner("Subscription has unpaid invoices.")
    if err.code == error_codes.ORGANIZATION_CANCELLED:
        return show_banner("Subscription cancelled — service is read-only.")
    if err.code == error_codes.ORGANIZATION_PURGED:
        return show_banner("Organization has been purged.")
    if err.code == error_codes.DOCUMENT_NOT_FOUND:
        return show_404()
    if err.code == error_codes.DOCUMENT_GONE:
        return show_410()  # deleted, or a sandbox document past 30 days
    raise
```

→ Full error reference: https://poli-page.github.io/sdk-python/reference/errors/

## Cancellation

Per-call timeout (overrides the client-level `timeout`):

```python
pdf = client.render.pdf(
    {"project": "...", "template": "...", "data": {}, "timeout": 5.0}
)
```

For full cancellation in async code, use standard `asyncio` task cancellation:

```python
task = asyncio.create_task(client.render.pdf({...}))
task.cancel()  # → PoliPageError(code='aborted')
```

In sync code, run the call in a thread + cancel via timeout if you need true cancellation; the SDK's per-call `timeout` is the idiomatic path for everything else.

## Observability

Two complementary mechanisms:

### Logger (always-on, silent by default)

```python
import logging

# Opt in to verbose request/response logs:
logging.getLogger("poli_page").setLevel(logging.DEBUG)
# Or via env var at import time:
#   POLI_PAGE_LOG=debug python app.py
```

One DEBUG line per HTTP attempt (`method url status duration_ms attempt`), one INFO line per retry, one ERROR line per terminal failure. Never logs the `Authorization` header or any field name matching `api_key` / `apiKey` / `token`.

### Hooks (`on_retry`, `on_error`)

Optional, sync callables; never break the request:

```python
from poli_page import PoliPage, RetryEvent, PoliPageError


def on_retry(event: RetryEvent) -> None:
    log.warning(f"retry {event.attempt} after {event.delay_ms:.0f} ms: {event.reason.code}")


def on_error(err: PoliPageError) -> None:
    sentry.capture_exception(err)


client = PoliPage(on_retry=on_retry, on_error=on_error)  # reads POLI_PAGE_API_KEY
```

For per-HTTP-request hooks, pass your own `httpx.Client` with `event_hooks={...}` to the SDK — that's the httpx-idiomatic path for request/response wiretaps:

```python
import os

import httpx

client = PoliPage(
    api_key=os.environ["POLI_PAGE_API_KEY"],
    http_client=httpx.Client(
        event_hooks={
            "request": [lambda req: metrics.inc("poli.request")],
            "response": [lambda res: tracing.add_event(res.status_code)],
        }
    ),
)
```

## Retries & idempotency

The SDK retries on **5xx**, **429**, **network errors**, and **timeouts**. Backoff is exponential (`retry_delay * 2^N`) with jitter in `[0.5, 1.5)`, capped by `Retry-After` (seconds, HTTP-date) or `Retry-After-Ms` when the server provides them — capped further at 30 s. Every POST sends an auto-generated `Idempotency-Key` (UUID v4); pass `idempotency_key` in the input dict to override.

## Type system

`py.typed` ships in the wheel. Strict-mode-clean against pyright; mypy strict on `src/` is green in CI as well.

`RenderInput` is the one render input `TypedDict`: `project`, `template` and `data`, plus the optional `format`, `orientation`, `locale`, `metadata`, `idempotency_key` and `timeout`. The request body carries only the documented fields: a key outside that set (such as the removed `version`) is not sent, and a `None` field is left out. Input without a `project` raises `PoliPageError(code="PROJECT_REQUIRED_FOR_DOCUMENT")` before any request.

## Concurrency & thread-safety

The sync client is thread-safe — share a single instance across threads. The async client (`AsyncPoliPage`) is safe to share across asyncio tasks. The client carries no per-request mutable state, so a single instance per process is the expected pattern.

## Runtime support

| Runtime | Status |
| ------- | ------ |
| CPython 3.11 / 3.12 / 3.13 | Supported |
| PyPy 3.11+ | Untested — should work; httpx is the only runtime dep |
| Browsers | Not supported (API keys are server-side secrets) |

**Browsers are not supported.** API keys (`pp_{env}_…`, whatever the environment) are secrets and must never be shipped to a browser. Call the SDK from your backend and proxy the result to the client.

## Requirements

- Python 3.11 or later
- `httpx >= 0.25, < 1.0` (the only runtime dependency)

## Documentation & support

- Platform docs: [docs.poli.page](https://docs.poli.page)
- SDK API reference: [poli-page.github.io/sdk-python](https://poli-page.github.io/sdk-python/)
- Sign up & generate API keys: [app.poli.page](https://app.poli.page)
- Issues: [github.com/poli-page/sdk-python/issues](https://github.com/poli-page/sdk-python/issues)

## License

[MIT](LICENSE) © Poli Page
