# Migration Guide

This file documents breaking changes between major versions of `poli-page`
(Python). Follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
breaking changes only ship in major version bumps and always come with an
entry here.

## 1.0

The first stable release. There are no prior public releases to migrate from.

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

### Storage workflow (1.0)

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
