"""poli-page SDK — synchronous Python demo.

Run:
    python demo/sync_demo.py

Walks every public method of `PoliPage` end-to-end against a real Poli Page
API. Renders the `welcome` template of the `getting-started` project, which
every organization gets in its `sandbox` environment, so it works out of the
box with a `sandbox` key (`pp_sandbox_…`) of a fresh organization. Reads
`POLI_PAGE_API_KEY` and, optionally, `POLI_PAGE_BASE_URL`.

Outputs land in `demo/output-sync/`:

  - render.pdf             — `client.render.pdf()`
  - stream.pdf             — `client.render.pdf_stream()`
  - file.pdf               — `render_to_file()`
  - thumbs/page_<n>.png    — `client.documents.thumbnails()` (Starter+ tier)
  - documents_preview.html — `client.documents.preview(id)` after `render.document()`

Step 9 (`not-found`) renders a template that does not exist: the demo catches
the `PoliPageError` (404 `TEMPLATE_NOT_FOUND`) and prints its fields. The
script does NOT crash there. Any other outcome (another error, or a render
that succeeds) ends the demo with exit status 1.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

# Allow running directly: `python demo/sync_demo.py` (no install needed).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _shared import c, ensure_api_key, file_link, resolve_base_url, step

from poli_page import PoliPage, PoliPageError, RenderInput, RetryEvent, error_codes
from poli_page.fs import render_to_file

OUT_DIR = Path(__file__).resolve().parent / "output-sync"
OUT_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = ensure_api_key()
BASE_URL = resolve_base_url()

PROJECT_INPUT: RenderInput = {
    "project": "getting-started",
    "template": "welcome",
    "data": {"name": "SDK Demo"},
}

NOT_FOUND_INPUT: RenderInput = {
    "project": "getting-started",
    "template": "does-not-exist",
    "data": {},
}

TOTAL_STEPS = 9


def _on_retry(event: RetryEvent) -> None:
    print(
        c.yellow("  ↻")
        + c.dim(
            f" retrying attempt={event.attempt} delay={event.delay_ms:.0f}ms"
            f" reason={event.reason.code}"
        )
    )


with PoliPage(api_key=API_KEY, base_url=BASE_URL, on_retry=_on_retry) as client:
    # ─────────────────────────────────────────────────────────────────────
    # 1. render.pdf — PDF bytes in memory
    # ─────────────────────────────────────────────────────────────────────
    step(1, TOTAL_STEPS, "render.pdf() — PDF bytes in memory")
    pdf_bytes = client.render.pdf(PROJECT_INPUT)
    render_path = OUT_DIR / "render.pdf"
    render_path.write_bytes(pdf_bytes)
    print(f"  {len(pdf_bytes)} bytes, magic: {c.bold(pdf_bytes[:4].decode('latin-1'))}")
    print(f"  {c.dim('open:')} {file_link(render_path)}")

    # ─────────────────────────────────────────────────────────────────────
    # 2. render.pdf_stream — chunk iterator, bounded memory
    # ─────────────────────────────────────────────────────────────────────
    step(2, TOTAL_STEPS, "render.pdf_stream() — streaming chunks")
    stream_path = OUT_DIR / "stream.pdf"
    total_bytes = 0
    with client.render.pdf_stream(PROJECT_INPUT) as stream, stream_path.open("wb") as fh:
        for chunk in stream:
            fh.write(chunk)
            total_bytes += len(chunk)
    print(f"  {total_bytes} bytes streamed to disk")
    print(f"  {c.dim('open:')} {file_link(stream_path)}")

    # ─────────────────────────────────────────────────────────────────────
    # 3. render_to_file — convenience helper on top of pdf_stream
    # ─────────────────────────────────────────────────────────────────────
    step(3, TOTAL_STEPS, "render_to_file() — straight to disk")
    file_path = OUT_DIR / "file.pdf"
    render_to_file(client, PROJECT_INPUT, file_path)
    print(f"  wrote {file_path.stat().st_size} bytes")
    print(f"  {c.dim('open:')} {file_link(file_path)}")

    # ─────────────────────────────────────────────────────────────────────
    # 4. render.document — store the document; defer PDF download
    # ─────────────────────────────────────────────────────────────────────
    step(4, TOTAL_STEPS, "render.document() — store, return descriptor")
    doc = client.render.document(PROJECT_INPUT)
    print(f"  {c.dim('document_id:')} {c.bold(doc.document_id)}")
    print(f"  {c.dim('page_count:')} {doc.page_count}  {c.dim('size_bytes:')} {doc.size_bytes}")

    # ─────────────────────────────────────────────────────────────────────
    # 5. documents.get — refresh the descriptor (fresh presigned URL)
    # ─────────────────────────────────────────────────────────────────────
    step(5, TOTAL_STEPS, "documents.get() — refresh descriptor")
    fetched = client.documents.get(doc.document_id)
    print(f"  {c.dim('refreshed presigned URL valid until:')} {fetched.expires_at}")

    # ─────────────────────────────────────────────────────────────────────
    # 6. documents.thumbnails — per-page images (tier-aware)
    # ─────────────────────────────────────────────────────────────────────
    step(6, TOTAL_STEPS, "documents.thumbnails() — page images (Starter+ tier)")
    try:
        thumbs = client.documents.thumbnails(doc.document_id, {"width": 320, "format": "png"})
    except PoliPageError as err:
        if err.code == "THUMBNAILS_NOT_AVAILABLE":
            print(f"  {c.yellow('skipped')} — {err.code} (Starter+ feature, not on Free)")
        else:
            raise
    else:
        thumb_dir = OUT_DIR / "thumbs"
        thumb_dir.mkdir(exist_ok=True)
        for thumb in thumbs:
            out = thumb_dir / f"page_{thumb.page}.png"
            out.write_bytes(base64.b64decode(thumb.data))
            print(f"  wrote {out.name} ({thumb.width}x{thumb.height})")
        print(f"  {c.dim('open:')} {file_link(thumb_dir)}")

    # ─────────────────────────────────────────────────────────────────────
    # 7. documents.preview — stored HTML (no engine work)
    # ─────────────────────────────────────────────────────────────────────
    step(7, TOTAL_STEPS, "documents.preview() — stored HTML (no engine work)")
    stored = client.documents.preview(doc.document_id)
    stored_path = OUT_DIR / "documents_preview.html"
    stored_path.write_text(stored.html, encoding="utf-8")
    print(f"  {c.bold(stored.page_count)} page(s), {len(stored.html)} chars")
    print(f"  {c.dim('open:')} {file_link(stored_path)}")

    # ─────────────────────────────────────────────────────────────────────
    # 8. documents.delete — soft-delete the demo document
    # ─────────────────────────────────────────────────────────────────────
    step(8, TOTAL_STEPS, "documents.delete() — soft-delete")
    client.documents.delete(doc.document_id)
    print(f"  {c.green('✔')} deleted {doc.document_id}")

    # ─────────────────────────────────────────────────────────────────────
    # 9. not-found — render a template that does not exist, on purpose
    # ─────────────────────────────────────────────────────────────────────
    step(9, TOTAL_STEPS, "not-found — DEMO ONLY (we trigger an error on purpose)")
    print(
        c.yellow("  ⚠  This step is intentional — the SDK is about to throw, but")
        + " the demo will catch and inspect it. "
        + c.bold("The demo is NOT crashing.")
    )
    print(c.dim("     (We render template 'does-not-exist', expecting 404 TEMPLATE_NOT_FOUND.)"))
    print()
    try:
        client.render.pdf(NOT_FOUND_INPUT)
    except PoliPageError as err:
        if err.status != 404 or err.code != error_codes.TEMPLATE_NOT_FOUND:
            sys.exit(
                c.red("  ✗ unexpected error:")
                + f" expected 404 {error_codes.TEMPLATE_NOT_FOUND!r}, got {err.status} {err.code!r}"
                + f" (message={err.message!r}, request_id={err.request_id!r})"
            )
        print(f"  {c.green('✔')} Error caught successfully. PoliPageError exposed:")
        print(f"     code={err.code!r}  status={err.status}")
        print(f"     message={err.message!r}")
        print(f"     request_id={err.request_id!r}")
    else:
        sys.exit(c.red("  ✗ unexpected: the call succeeded but should have failed"))

print(f"\n{c.green('✔')} {c.bold('All steps completed.')} Inspect output in {file_link(OUT_DIR)}\n")
