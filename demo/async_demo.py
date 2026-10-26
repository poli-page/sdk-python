"""poli-page SDK — asynchronous Python demo.

Run:
    python demo/async_demo.py

Mirrors `sync_demo.py` step-for-step using the async client surface: the
same nine steps, ending with the `not-found` step. Same artifacts land in
`demo/output-async/` so you can diff against the sync demo's
`demo/output-sync/` to confirm both surfaces produce equivalent output.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _shared import c, ensure_api_key, file_link, resolve_base_url, step

from poli_page import AsyncPoliPage, PoliPageError, RenderInput, RetryEvent, error_codes
from poli_page.fs import async_render_to_file

OUT_DIR = Path(__file__).resolve().parent / "output-async"
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


async def main() -> None:
    async with AsyncPoliPage(api_key=API_KEY, base_url=BASE_URL, on_retry=_on_retry) as client:
        # ───────────────────────────────────────────────────────────────
        # 1. render.pdf
        # ───────────────────────────────────────────────────────────────
        step(1, TOTAL_STEPS, "render.pdf() — PDF bytes in memory")
        pdf_bytes = await client.render.pdf(PROJECT_INPUT)
        render_path = OUT_DIR / "render.pdf"
        render_path.write_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes)} bytes, magic: {c.bold(pdf_bytes[:4].decode('latin-1'))}")
        print(f"  {c.dim('open:')} {file_link(render_path)}")

        # ───────────────────────────────────────────────────────────────
        # 2. render.pdf_stream
        # ───────────────────────────────────────────────────────────────
        step(2, TOTAL_STEPS, "render.pdf_stream() — streaming chunks")
        stream_path = OUT_DIR / "stream.pdf"
        total = 0
        async with client.render.pdf_stream(PROJECT_INPUT) as stream:
            with stream_path.open("wb") as fh:
                async for chunk in stream:
                    fh.write(chunk)
                    total += len(chunk)
        print(f"  {total} bytes streamed to disk")
        print(f"  {c.dim('open:')} {file_link(stream_path)}")

        # ───────────────────────────────────────────────────────────────
        # 3. async_render_to_file
        # ───────────────────────────────────────────────────────────────
        step(3, TOTAL_STEPS, "async_render_to_file() — straight to disk")
        file_path = OUT_DIR / "file.pdf"
        await async_render_to_file(client, PROJECT_INPUT, file_path)
        print(f"  wrote {file_path.stat().st_size} bytes")
        print(f"  {c.dim('open:')} {file_link(file_path)}")

        # ───────────────────────────────────────────────────────────────
        # 4. render.document
        # ───────────────────────────────────────────────────────────────
        step(4, TOTAL_STEPS, "render.document() — store, return descriptor")
        doc = await client.render.document(PROJECT_INPUT)
        print(f"  {c.dim('document_id:')} {c.bold(doc.document_id)}")
        print(f"  {c.dim('page_count:')} {doc.page_count}  {c.dim('size_bytes:')} {doc.size_bytes}")

        # ───────────────────────────────────────────────────────────────
        # 5. documents.get
        # ───────────────────────────────────────────────────────────────
        step(5, TOTAL_STEPS, "documents.get() — refresh descriptor")
        fetched = await client.documents.get(doc.document_id)
        print(f"  {c.dim('refreshed presigned URL valid until:')} {fetched.expires_at}")

        # ───────────────────────────────────────────────────────────────
        # 6. documents.thumbnails
        # ───────────────────────────────────────────────────────────────
        step(6, TOTAL_STEPS, "documents.thumbnails() — page images (Starter+ tier)")
        try:
            thumbs = await client.documents.thumbnails(
                doc.document_id, {"width": 320, "format": "png"}
            )
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

        # ───────────────────────────────────────────────────────────────
        # 7. documents.preview
        # ───────────────────────────────────────────────────────────────
        step(7, TOTAL_STEPS, "documents.preview() — stored HTML (no engine work)")
        stored = await client.documents.preview(doc.document_id)
        stored_path = OUT_DIR / "documents_preview.html"
        stored_path.write_text(stored.html, encoding="utf-8")
        print(f"  {c.bold(stored.page_count)} page(s), {len(stored.html)} chars")
        print(f"  {c.dim('open:')} {file_link(stored_path)}")

        # ───────────────────────────────────────────────────────────────
        # 8. documents.delete
        # ───────────────────────────────────────────────────────────────
        step(8, TOTAL_STEPS, "documents.delete() — soft-delete")
        await client.documents.delete(doc.document_id)
        print(f"  {c.green('✔')} deleted {doc.document_id}")

        # ───────────────────────────────────────────────────────────────
        # 9. not-found
        # ───────────────────────────────────────────────────────────────
        step(9, TOTAL_STEPS, "not-found — DEMO ONLY (we trigger an error on purpose)")
        print(
            c.yellow("  ⚠  This step is intentional — the SDK is about to throw, but")
            + " the demo will catch and inspect it. "
            + c.bold("The demo is NOT crashing.")
        )
        print(
            c.dim("     (We render template 'does-not-exist', expecting 404 TEMPLATE_NOT_FOUND.)")
        )
        print()
        try:
            await client.render.pdf(NOT_FOUND_INPUT)
            print(c.red("  ✗ unexpected: the call succeeded but should have failed"))
        except PoliPageError as err:
            print(f"  {c.green('✔')} Error caught successfully. PoliPageError exposed:")
            print(f"     code={err.code!r}  status={err.status}")
            print(f"     message={err.message!r}")
            print(f"     request_id={err.request_id!r}")
            if err.code != error_codes.TEMPLATE_NOT_FOUND:
                print(c.red(f"  ✗ unexpected code: expected {error_codes.TEMPLATE_NOT_FOUND!r}"))

    print(
        f"\n{c.green('✔')} {c.bold('All steps completed.')} "
        f"Inspect output in {file_link(OUT_DIR)}\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
