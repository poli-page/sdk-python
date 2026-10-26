# Migration Guide

This file documents breaking changes between versions of `poli-page`
(Python). The package follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
while it is on 0.x, a breaking change bumps the minor version, and every
breaking change comes with an entry here.

## From 0.9.x to 0.10.0

0.10.0 moves the SDK to the environments contract. Nobody depended on the old
contract yet, so every removal ships at once, with no deprecation window.

### API keys name their environment

A key is `pp_{env}_{32 lowercase hex}`, where `{env}` is the one environment
the key belongs to: `pp_sandbox_…`, `pp_live_…`, `pp_staging_…`. It matches

```text
^pp_(?=[a-z][a-z0-9-]{0,19}_)[a-z][a-z0-9]*(?:-[a-z0-9]+)*_[0-9a-f]{32}$
```

The `pp_test_` and `pp_sa_` prefixes are gone; standard and service keys share
this one format. Replace a `pp_test_…` key with a key of your organization's
`sandbox` environment, and a `pp_sa_…` key with a key of the environment it
should render in. The SDK passes the key through unchanged and does not check
its format. `DocumentDescriptor.environment` is now any environment name the
API returns (`Environment = str`).

### No more `version`

A render uses the project's copy published in the key's environment. Publish
the project to that environment instead of pinning a version.

```python
# 0.9.x
client.render.pdf({"project": "billing", "template": "invoice", "version": "1.0.0", "data": data})

# 0.10.0
client.render.pdf({"project": "billing", "template": "invoice", "data": data})
```

The SDK no longer sends a `version` key left in the input dict; remove it all
the same. `DocumentDescriptor.version` / `AsyncDocumentDescriptor.version` are
gone.

### No more `render.preview` or inline HTML

`render.preview` (sync and async) and inline-HTML rendering are removed. To
preview a template or render inline HTML while you design it, use the
playground at https://play.poli.page. `documents.preview(id)`, the stored HTML
of a document you already rendered, stays.

```python
# 0.9.x
result = client.render.preview({"template": "<h1>Hello {{ name }}</h1>", "data": data})

# 0.10.0: publish the template, render it, then read its stored HTML
doc = client.render.document({"project": "billing", "template": "invoice", "data": data})
stored = client.documents.preview(doc.document_id)
```

### Types

| 0.9.x | 0.10.0 |
|---|---|
| `ProjectModeInput` | `RenderInput` (the only render input type) |
| `InlineModeInput` | removed |
| `RenderInput` (union of both) | `RenderInput` (the `TypedDict` above) |
| `PreviewResult` | removed |
| `Environment = Literal["sandbox", "live"]` | `Environment = str` |
| `ThumbnailOptions.width` required | every `ThumbnailOptions` key optional |

### Error codes

| 0.9.x constant | 0.10.0 |
|---|---|
| `GONE` | `DOCUMENT_GONE` (`410`: deleted, or a `sandbox` document older than 30 days) |
| `PAYMENT_REQUIRED` | `ORGANIZATION_PAYMENT_GRACE` (`403`) |
| `VERSION_NOT_FOUND`, `INVALID_VERSION_FORMAT`, `VERSION_REQUIRED`, `INVALID_VERSION_FOR_KEY_ENV` | removed with versions |
| `MISSING_PROJECT_OR_TEMPLATE` | removed |

New constants: `PUBLISH_IN_PROGRESS`, `ENVIRONMENT_MISMATCH`,
`PROJECT_NOT_IN_ENVIRONMENT`, `TEMPLATE_NOT_FOUND`, `DOCUMENT_GONE`,
`ENVIRONMENT_PROTECTED`, `ORGANIZATION_PAYMENT_GRACE`, `EMPTY_DOCUMENT`,
`STORAGE_ACCESS_DENIED`, `ORGANIZATION_MIGRATING`, `PROJECT_NOT_FOUND`,
`TEMPLATE_ERROR`, `THUMBNAILS_NOT_AVAILABLE`, `RATE_LIMIT_EXCEEDED`,
`RENDER_BODY_TOO_LARGE`, `DOCUMENT_TOO_LARGE` and `RENDER_TIMEOUT`. A code the
SDK does not list still reaches `err.code` verbatim.

```python
# 0.9.x
if err.code == error_codes.GONE:
    ...
if err.code == error_codes.PAYMENT_REQUIRED:
    ...

# 0.10.0
if err.code == error_codes.DOCUMENT_GONE:
    ...
if err.code == error_codes.ORGANIZATION_PAYMENT_GRACE:
    ...
```

### Thumbnails and delete

- `documents.thumbnails(id, options=None)`: every option is optional, `format`
  also accepts `"webp"`, and with no option the API defaults apply (400 px
  `jpeg`).
- `documents.delete(id)` is idempotent: deleting an already-deleted document
  succeeds (`204`).

See [CHANGELOG.md](CHANGELOG.md#0100---2026-10-26) for the full list.

## 0.9.0

The first public release. There are no prior public releases to migrate from.

### Coming from `@poli-page/sdk` (Node)?

The Python and Node SDKs share a single contract (`sdk-specification.md`).
Behavior — retry policy, error codes, predicates, project-mode constraint —
is identical. The differences are surface-level, not semantic:

| Concern | Node | Python |
|---|---|---|
| Casing | camelCase | snake_case |
| Class | `new PoliPage({ apiKey })` | `PoliPage(api_key=...)` |
| Async | `await client.render.pdf(...)` | `await AsyncPoliPage(...).render.pdf(...)` (separate class) |
| Errors | single `PoliPageError` + predicates | typed hierarchy + same predicates |
| File helper | `import { renderToFile } from '@poli-page/sdk/node'` | `from poli_page.fs import render_to_file` |
| Stream | returns a `ReadableStream` | returns a context manager yielding bytes |
| Time units | milliseconds (`retryDelay: 500`, `timeout: 60_000`) | seconds (`retry_delay=0.5`, `timeout=60.0`) |
| Cancellation | `AbortSignal` | per-call `timeout=`; `asyncio.CancelledError` in async |
| Idempotency override | `idempotencyKey: "..."` in input | `idempotency_key: "..."` in input |

`metadata` on `DocumentDescriptor` is **always** present (defaults to `{}`)
on both SDKs — parity with Node's `RawDocumentDescriptor.metadata: RenderMetadata`.

### Storage workflow (0.9.0)

Every `render.*` (except `render.preview`) produces a stored document
server-side. `render.pdf` and `render.pdf_stream` are SDK conveniences that
chain a presigned-URL fetch internally to return PDF bytes. `render.document`
returns just the descriptor — use it when you'd rather hold the `document_id`
and fetch bytes later.

This means `render.pdf` makes two HTTP calls (`POST /v1/render` +
`GET presigned_pdf_url`). The presigned URL is short-lived (15 min) —
refresh via `client.documents.get(id)` when needed.

`render.preview` is the exception — it doesn't store and returns paginated
HTML directly. It's also the only render method that accepts inline-mode HTML.

See [CHANGELOG.md](CHANGELOG.md) for the full per-feature list.
