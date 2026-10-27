# `poli-page` — runnable Python demos

Small, self-contained programs that exercise the SDK end-to-end against the live Poli Page API. Use them as a learning tool, a smoke test before publishing, or a reference when porting to another language.

## TL;DR

```bash
# from the repo root
python demo/sync_demo.py     # synchronous client (PoliPage)
python demo/async_demo.py    # asynchronous client (AsyncPoliPage)
```

Each demo walks the SDK's full public surface in spec order and writes the artifacts to a sibling output folder so you can diff sync vs. async results.

## How the demos resolve your API key

Each demo needs a key of your organization's `sandbox` environment (`pp_sandbox_…`). Use a fresh organization: the demos render the `welcome` template of the `getting-started` project, which every organization gets in its `sandbox` environment. In an organization that renamed, deleted or unpublished that project, the API answers `404 PROJECT_NOT_FOUND` or `404 PROJECT_NOT_IN_ENVIRONMENT`.

Every demo reads `POLI_PAGE_API_KEY` from these sources, in order (an empty value counts as unset):

1. **`os.environ`** — wins if set in your shell. Best for CI.
2. **`.env` at the repo root** — the canonical project file, gitignored, survives across runs.
3. **Interactive prompt** — if neither of the above has the key, the demo prints full instructions and accepts the key on stdin, **then appends it to `.env`** so future runs skip the prompt. A pasted key must match the SDK contract's full-key regex, `^pp_(?=[a-z][a-z0-9-]{0,19}_)[a-z][a-z0-9]*(?:-[a-z0-9]+)*_[0-9a-f]{32}$`; the demo does not check the environment name.

The "first run prompts, subsequent runs silent" experience is the design goal.

To pre-populate without the prompt:

```bash
echo 'POLI_PAGE_API_KEY=pp_sandbox_x' > .env   # replace pp_sandbox_x with your full key
```

`POLI_PAGE_BASE_URL` (optional, same sources) overrides the API host; the default is `https://api.poli.page`.

## What the demos do

Both demos walk the SDK's full surface in this order:

| # | Method | Output |
|---|---|---|
| 1 | `render.pdf()` | `render.pdf` — PDF bytes in memory |
| 2 | `render.pdf_stream()` | `stream.pdf` — bounded-memory streamed PDF |
| 3 | `render_to_file()` (async: `async_render_to_file`) | `file.pdf` — streamed straight to disk |
| 4 | `render.document()` | descriptor logged (no file) |
| 5 | `documents.get(id)` | fresh presigned URL logged |
| 6 | `documents.thumbnails(id, …)` | `thumbs/page_<n>.png` (Starter+ tier; skipped on Free) |
| 7 | `documents.preview(id)` | `documents_preview.html` |
| 8 | `documents.delete(id)` | soft-deletes the demo document |
| 9 | `not-found` | renders template `does-not-exist` with `data={}`, on purpose: the 404 `TEMPLATE_NOT_FOUND` is caught and its `code`, `status`, `message` and `request_id` printed; any other error, or a render that succeeds, ends the demo with exit status 1 |

Steps 1 to 8 render `getting-started`/`welcome` with `data={"name": "SDK Demo"}` and no version: the API renders the project's copy published in the key's environment.

Sync outputs land in `demo/output-sync/`; async outputs in `demo/output-async/`. The PDFs are byte-equivalent across sync and async modulo creation timestamps.

## Cross-language porters

This demo is the canonical reference for the Python port of the SDK. Sister demos in other languages (`sdk-node`, `sdk-php`, `sdk-go`) follow the same method order so output can be diffed across implementations.

The `getting-started`/`welcome` template, published into every organization's `sandbox` environment, is used everywhere — no project setup needed with a `sandbox` key of a fresh organization. To preview a template or render inline HTML, use the playground at https://play.poli.page.
