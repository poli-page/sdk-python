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

Every demo reads `POLI_PAGE_API_KEY` from these sources, in order:

1. **`os.environ`** — wins if set in your shell. Best for CI.
2. **`.env` at the repo root** — the canonical project file, gitignored, survives across runs.
3. **Interactive prompt** — if neither of the above has the key, the demo prints full instructions and accepts the key on stdin, **then appends it to `.env`** so future runs skip the prompt.

The "first run prompts, subsequent runs silent" experience is the design goal.

To pre-populate without the prompt:

```bash
echo 'POLI_PAGE_API_KEY=pp_test_your_key_here' > .env
```

## What the demos do

Both demos walk the SDK's full surface in this order:

| # | Method | Output |
|---|---|---|
| 1 | `render.pdf()` | `render.pdf` — PDF bytes in memory |
| 2 | `render.pdf_stream()` | `stream.pdf` — bounded-memory streamed PDF |
| 3 | `render_to_file()` (async: `async_render_to_file`) | `file.pdf` — streamed straight to disk |
| 4 | `render.preview()` | `render_preview.html` — paginated HTML |
| 5 | `render.document()` | descriptor logged (no file) |
| 6 | `documents.get(id)` | fresh presigned URL logged |
| 7 | `documents.thumbnails(id, …)` | `thumbs/page_<n>.png` (Starter+ tier; skipped on Free) |
| 8 | `documents.preview(id)` | `documents_preview.html` |
| 9 | `documents.delete(id)` | soft-deletes the demo document |
| 10 | error path | DELIBERATE 400 `INVALID_VERSION_FORMAT` — caught + inspected |

Sync outputs land in `demo/output-sync/`; async outputs in `demo/output-async/`. The PDFs are byte-equivalent across sync and async modulo creation timestamps.

## Cross-language porters

This demo is the canonical reference for the Python port of the SDK. Sister demos in other languages (`sdk-node`, `sdk-php`, `sdk-go`) follow the same method order so output can be diffed across implementations.

The auto-provisioned `getting-started/welcome/1.0.0` template is used everywhere — no project setup needed for a fresh API key.
