#!/usr/bin/env python3
"""Extract the public Poli Page Python SDK surface into MDX reference pages.

Output shape matches the Poli Page SDK docs convention (§2c/§4): one MDX file
per public method under `docs/src/content/docs/reference/methods/`, plus
`client.mdx`, `types.mdx`, `errors.mdx`, `runtime-support.mdx`, and an
`_meta.json` sidecar.

Implementation: stdlib `ast`. No third-party deps — keeps the CI step lean
and avoids pulling griffe into the docs build.

Source of truth for code examples: `examples/<slug>.py` at the repo root.
Each method page embeds its example verbatim; missing files fail the build.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SRC_ROOT = REPO_ROOT / "src" / "poli_page"
EXAMPLES_DIR = REPO_ROOT / "examples"
REFERENCE_OUT = REPO_ROOT / "docs" / "src" / "content" / "docs" / "reference"
EXTRACTOR_VERSION = "0.1.0"

# Method canonical slug + example file per public method on the sync client.
# Order matters: it drives the order of the Methods sidebar group.
METHODS: list[dict[str, str]] = [
    {
        "slug": "render-pdf",
        "name": "render.pdf",
        "class": "RenderSync",
        "func": "pdf",
        "example": "render_pdf.py",
    },
    {
        "slug": "render-pdf-stream",
        "name": "render.pdf_stream",
        "class": "RenderSync",
        "func": "pdf_stream",
        "example": "render_pdf_stream.py",
    },
    {
        "slug": "render-preview",
        "name": "render.preview",
        "class": "RenderSync",
        "func": "preview",
        "example": "render_preview.py",
    },
    {
        "slug": "render-document",
        "name": "render.document",
        "class": "RenderSync",
        "func": "document",
        "example": "render_document.py",
    },
    {
        "slug": "documents-get",
        "name": "documents.get",
        "class": "DocumentsSync",
        "func": "get",
        "example": "documents_get.py",
    },
    {
        "slug": "documents-preview",
        "name": "documents.preview",
        "class": "DocumentsSync",
        "func": "preview",
        "example": "documents_preview.py",
    },
    {
        "slug": "documents-thumbnails",
        "name": "documents.thumbnails",
        "class": "DocumentsSync",
        "func": "thumbnails",
        "example": "documents_thumbnails.py",
    },
    {
        "slug": "documents-delete",
        "name": "documents.delete",
        "class": "DocumentsSync",
        "func": "delete",
        "example": "documents_delete.py",
    },
    {
        "slug": "render-to-file",
        "name": "render_to_file",
        "module": "fs",
        "func": "render_to_file",
        "example": "render_to_file.py",
    },
]

# Public types to document (resolved from src/poli_page/types.py).
PUBLIC_TYPES = [
    "ProjectModeInput",
    "InlineModeInput",
    "RenderInput",
    "RenderMetadata",
    "PreviewResult",
    "DocumentPreviewResult",
    "DocumentDescriptor",
    "AsyncDocumentDescriptor",
    "Thumbnail",
    "ThumbnailOptions",
    "PageFormat",
    "Orientation",
    "Environment",
    "RetryEvent",
    "OnRetry",
    "OnError",
]

# Per-method error mapping. The extractor cannot reliably infer which API
# codes each endpoint raises from source comments — we encode it here once,
# in lockstep with the API spec, and update on changes.
METHOD_ERRORS: dict[str, list[dict[str, str]]] = {
    "render-pdf": [
        {"code": "VALIDATION_ERROR", "when": "The `data` mapping does not satisfy the template schema."},
        {"code": "NOT_FOUND", "when": "The `project/template` slug does not exist."},
        {"code": "QUOTA_EXCEEDED", "when": "Per-key rate limit or monthly quota reached. Retryable."},
        {"code": "timeout", "when": "Request exceeded the configured `timeout`. Retryable."},
        {"code": "network_error", "when": "TCP/TLS-level failure reaching the API. Retryable."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
        {"code": "DOWNLOAD_FAILED", "when": "The S3 second-hop download for the rendered PDF failed."},
    ],
    "render-pdf-stream": [
        {"code": "VALIDATION_ERROR", "when": "The `data` mapping does not satisfy the template schema."},
        {"code": "NOT_FOUND", "when": "The `project/template` slug does not exist."},
        {"code": "QUOTA_EXCEEDED", "when": "Per-key rate limit or monthly quota reached. Retryable."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
        {"code": "DOWNLOAD_FAILED", "when": "The S3 second-hop streaming download failed."},
    ],
    "render-preview": [
        {"code": "VALIDATION_ERROR", "when": "The `data` mapping does not satisfy the template schema."},
        {"code": "NOT_FOUND", "when": "The `project/template` slug does not exist (project mode only)."},
        {"code": "MISSING_DATA", "when": "Request body lacks the required `data` field."},
        {"code": "QUOTA_EXCEEDED", "when": "Per-key rate limit or monthly quota reached. Retryable."},
    ],
    "render-document": [
        {"code": "VALIDATION_ERROR", "when": "The `data` mapping does not satisfy the template schema."},
        {"code": "NOT_FOUND", "when": "The `project/template` slug does not exist."},
        {"code": "PROJECT_REQUIRED_FOR_DOCUMENT", "when": "Inline-shaped input was passed. Rejected locally before the HTTP call."},
        {"code": "QUOTA_EXCEEDED", "when": "Per-key rate limit or monthly quota reached. Retryable."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
    ],
    "documents-get": [
        {"code": "DOCUMENT_NOT_FOUND", "when": "No stored document matches the supplied id."},
        {"code": "INVALID_API_KEY", "when": "The API key is malformed or revoked."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
    ],
    "documents-preview": [
        {"code": "DOCUMENT_NOT_FOUND", "when": "No stored document matches the supplied id."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
    ],
    "documents-thumbnails": [
        {"code": "DOCUMENT_NOT_FOUND", "when": "No stored document matches the supplied id."},
        {"code": "VALIDATION_ERROR", "when": "Thumbnail options failed validation."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
    ],
    "documents-delete": [
        {"code": "DOCUMENT_NOT_FOUND", "when": "No stored document matches the supplied id."},
        {"code": "GONE", "when": "Document was already deleted."},
        {"code": "INTERNAL_ERROR", "when": "The API returned 5xx. Retryable."},
    ],
    "render-to-file": [
        {"code": "PROJECT_REQUIRED_FOR_DOCUMENT", "when": "Inline-shaped input. Rejected locally before the HTTP call."},
        {"code": "VALIDATION_ERROR", "when": "The `data` mapping does not satisfy the template schema."},
        {"code": "NOT_FOUND", "when": "The `project/template` slug does not exist."},
        {"code": "QUOTA_EXCEEDED", "when": "Per-key rate limit or monthly quota reached. Retryable."},
        {"code": "DOWNLOAD_FAILED", "when": "The S3 second-hop streaming download failed."},
    ],
}


# ----------------------------------------------------------------------------
# AST helpers
# ----------------------------------------------------------------------------


@dataclass(slots=True)
class FunctionInfo:
    name: str
    qualname: str
    signature: str
    docstring: str
    params: list[dict[str, str | bool]] = field(default_factory=list)
    returns: str = ""


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _format_signature(name: str, func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    # Strip `self` / `cls` from the rendered signature; callers don't pass it.
    args = func.args
    parts: list[str] = []

    posonly = list(args.posonlyargs)
    pos = list(args.args)
    if posonly and posonly[0].arg in {"self", "cls"}:
        posonly = posonly[1:]
    if not posonly and pos and pos[0].arg in {"self", "cls"}:
        pos = pos[1:]

    defaults_all = list(args.defaults)
    total_with_defaults = len(posonly) + len(pos)
    pad = total_with_defaults - len(defaults_all)
    defaults: list[ast.expr | None] = [None] * pad + defaults_all

    flat = list(posonly) + list(pos)
    for arg, default in zip(flat, defaults, strict=True):
        rendered = arg.arg
        if arg.annotation is not None:
            rendered += f": {_unparse(arg.annotation)}"
        if default is not None:
            rendered += f" = {_unparse(default)}"
        parts.append(rendered)

    if args.vararg is not None:
        v = args.vararg
        s = f"*{v.arg}"
        if v.annotation is not None:
            s += f": {_unparse(v.annotation)}"
        parts.append(s)
    elif args.kwonlyargs:
        parts.append("*")

    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        s = kw_arg.arg
        if kw_arg.annotation is not None:
            s += f": {_unparse(kw_arg.annotation)}"
        if kw_default is not None:
            s += f" = {_unparse(kw_default)}"
        parts.append(s)

    if args.kwarg is not None:
        k = args.kwarg
        s = f"**{k.arg}"
        if k.annotation is not None:
            s += f": {_unparse(k.annotation)}"
        parts.append(s)

    sig = f"{name}({', '.join(parts)})"
    if func.returns is not None:
        sig += f" -> {_unparse(func.returns)}"
    if isinstance(func, ast.AsyncFunctionDef):
        sig = f"async {sig}"
    return sig


def _docstring_first_line(doc: str) -> str:
    doc = (doc or "").strip()
    if not doc:
        return "(no description)"
    # First sentence, or first non-empty line — whichever is shorter.
    first_para = doc.split("\n\n", 1)[0].strip().replace("\n", " ")
    # Truncate at first sentence boundary if present.
    m = re.search(r"\.(?:\s|$)", first_para)
    if m:
        return first_para[: m.end()].strip()
    return first_para


def _collect_functions(mod_path: Path) -> dict[str, dict[str, FunctionInfo]]:
    """Return {class_or_module_qualname: {func_name: FunctionInfo}}.

    Module-level functions key under '<module>'.
    """
    out: dict[str, dict[str, FunctionInfo]] = {}
    module = _parse_module(mod_path)
    out.setdefault("<module>", {})

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = FunctionInfo(
                name=node.name,
                qualname=node.name,
                signature=_format_signature(node.name, node),
                docstring=ast.get_docstring(node) or "",
            )
            out["<module>"][node.name] = info
        elif isinstance(node, ast.ClassDef):
            bag: dict[str, FunctionInfo] = {}
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("_") and child.name not in {"__init__"}:
                        continue
                    qual = f"{node.name}.{child.name}"
                    bag[child.name] = FunctionInfo(
                        name=child.name,
                        qualname=qual,
                        signature=_format_signature(child.name, child),
                        docstring=ast.get_docstring(child) or "",
                    )
            out[node.name] = bag
    return out


def _collect_class_doc(mod_path: Path, class_name: str) -> str:
    tree = _parse_module(mod_path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_docstring(node) or ""
    return ""


# ----------------------------------------------------------------------------
# MDX builders
# ----------------------------------------------------------------------------


def _mdx_escape_for_jsx_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace("`", "\\`")


def _yaml_quote(s: str) -> str:
    """Wrap a string for safe YAML frontmatter.

    Double-quote and escape backslashes + double quotes. Handles colons,
    leading dashes, and other YAML metacharacters that would otherwise
    require careful unquoted handling.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _example_block(slug: str) -> str:
    example_path = EXAMPLES_DIR / next(
        (m["example"] for m in METHODS if m["slug"] == slug)
    )
    if not example_path.exists():
        raise SystemExit(f"extractor: missing example file {example_path}")
    body = example_path.read_text(encoding="utf-8").rstrip()
    return f"```python\n{body}\n```"


def _params_for_method(spec: dict[str, str], func_info: FunctionInfo) -> list[dict[str, object]]:
    """Build the ParamsTable rows from the parsed signature.

    All public methods take simple, well-known shapes (`input: ...`,
    `id: str`, `options: ...`). We hand-tune brief descriptions per slug
    rather than trying to extract them from the docstring — keeps the
    output stable across docstring rewordings.
    """
    descriptions: dict[str, dict[str, str]] = {
        "render-pdf": {"input": "Project-mode render input (`project`, `template`, `data`, plus optional `version`, `format`, `orientation`, `locale`, `metadata`, `idempotency_key`)."},
        "render-pdf-stream": {"input": "Project-mode render input. Same shape as `render.pdf`."},
        "render-preview": {"input": "Render input — accepts project mode OR inline mode."},
        "render-document": {"input": "Project-mode render input. Same shape as `render.pdf`."},
        "documents-get": {"id": "The `document_id` returned by a prior `render.document` call."},
        "documents-preview": {"id": "The `document_id` of the stored document to preview."},
        "documents-thumbnails": {
            "id": "The `document_id` of the stored document.",
            "options": "Thumbnail options — `width` (required), `format`, `quality`, `pages`.",
        },
        "documents-delete": {"id": "The `document_id` of the stored document to delete."},
        "render-to-file": {
            "client": "A `PoliPage` instance.",
            "input": "Project-mode render input.",
            "path": "Destination path. Parent directories are created automatically.",
        },
    }
    field_desc = descriptions.get(spec["slug"], {})

    sig = func_info.signature
    # Re-parse signature parameters in a forgiving way; just grab names and
    # annotations between the outer parens.
    inside = sig[sig.index("(") + 1 : sig.rfind(")")]
    rows: list[dict[str, object]] = []
    depth = 0
    buf = ""
    pieces: list[str] = []
    for ch in inside:
        if ch == "(" or ch == "[":
            depth += 1
        elif ch == ")" or ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            pieces.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        pieces.append(buf.strip())

    for piece in pieces:
        if piece in {"*", "/"} or piece.startswith("*"):
            continue
        # Drop default values for the rendered type column.
        head = piece.split("=", 1)[0].strip()
        if ":" in head:
            name, type_part = head.split(":", 1)
            name = name.strip()
            type_str = type_part.strip()
        else:
            name = head
            type_str = "Any"
        required = "=" not in piece and not name.startswith("**")
        rows.append({
            "name": name,
            "type": type_str,
            "required": required,
            "description": field_desc.get(name, "(no description)"),
        })
    return rows


def _returns_for(slug: str, func_info: FunctionInfo) -> str:
    sig = func_info.signature
    if "->" not in sig:
        return ""
    ret = sig.split("->", 1)[1].strip()
    # Some methods return private internal helpers (e.g. `_PdfStreamContext`)
    # — present the user-facing protocol instead.
    public_ret_overrides = {
        "render-pdf-stream": "ContextManager[Iterator[bytes]]",
    }
    ret = public_ret_overrides.get(slug, ret)
    descriptions = {
        "render-pdf": "the rendered PDF as raw bytes.",
        "render-pdf-stream": "a context manager yielding `Iterator[bytes]` chunks of the PDF stream.",
        "render-preview": "a `PreviewResult` with `html`, `total_pages`, and `environment` fields.",
        "render-document": "a `DocumentDescriptor` whose `download_pdf()` fetches the bytes on demand.",
        "documents-get": "a `DocumentDescriptor` refreshed with a new `presigned_pdf_url` (15-minute TTL).",
        "documents-preview": "a `DocumentPreviewResult` with `html` and `page_count`.",
        "documents-thumbnails": "a list of `Thumbnail` objects in page order, base64-encoded.",
        "documents-delete": "`None`. The PDF is purged; metadata is retained for audit.",
        "render-to-file": "`None`. The PDF is streamed to disk at `path`.",
    }
    return f"`{ret}` — {descriptions.get(slug, '')}"


def _method_mdx(spec: dict[str, str], func_info: FunctionInfo) -> str:
    name = spec["name"]
    desc = _docstring_first_line(func_info.docstring) or f"{name} method."
    # Strip trailing period for description (matches sdk-node house style).
    if desc.endswith("."):
        desc_clean = desc[:-1]
    else:
        desc_clean = desc
    # Cap description at 155 chars to satisfy the page-shape lint.
    if len(desc_clean) > 150:
        desc_clean = desc_clean[:147].rstrip() + "..."

    signature_for_card = f"{name}{func_info.signature[len(func_info.name):]}"
    # Some methods return private internal helpers; rewrite the rendered
    # signature card to the user-facing protocol so docs reflect intent.
    sig_card_overrides = {
        "render-pdf-stream": (
            "render.pdf_stream(input: ProjectModeInput) -> ContextManager[Iterator[bytes]]"
        ),
    }
    signature_for_card = sig_card_overrides.get(spec["slug"], signature_for_card)
    # The MethodSignature card shows the canonical name (e.g. `render.pdf`)
    # rather than the raw function name on the namespace class.
    code = _mdx_escape_for_jsx_string(signature_for_card)

    params = _params_for_method(spec, func_info)
    params_json = json.dumps(params, separators=(",", ":"))

    returns = _returns_for(spec["slug"], func_info)
    errors_rows = METHOD_ERRORS.get(spec["slug"], [])
    errors_json = json.dumps(errors_rows, separators=(",", ":"))

    example = _example_block(spec["slug"])

    body_doc = func_info.docstring.strip()
    # Lede: first paragraph of docstring, fall back to the description.
    lede = body_doc.split("\n\n", 1)[0].strip().replace("\n", " ") if body_doc else desc

    parts = [
        "---",
        f"title: {_yaml_quote(name)}",
        f"description: {_yaml_quote(desc_clean + '.')}",
        "sidebar:",
        f"  label: {_yaml_quote(name)}",
        "---",
        "",
        "import MethodSignature from '@preset/components/MethodSignature.astro';",
        "import ParamsTable from '@preset/components/ParamsTable.astro';",
        "import ErrorTable from '@preset/components/ErrorTable.astro';",
        "",
        f"<MethodSignature lang=\"python\" code={{`{code}`}} />",
        "",
        lede,
        "",
        "## Parameters",
        "",
        f"<ParamsTable params={{{params_json}}} />",
        "",
    ]
    if returns:
        parts += ["## Returns", "", returns, ""]
    if errors_rows:
        parts += ["## Errors", "", f"<ErrorTable errors={{{errors_json}}} />", ""]
    parts += [
        "## Example",
        "",
        example,
        "",
        "## See also",
        "- [Errors](../../../production/errors/)",
        "- [Configuration](../../../concepts/configuration/)",
        "",
    ]
    return "\n".join(parts)


def _client_mdx(class_doc: str) -> str:
    lede = (
        class_doc.split("\n\n", 1)[0].strip().replace("\n", " ")
        if class_doc
        else "Poli Page client. Entry point for the namespaced render API."
    )
    return textwrap.dedent(
        """\
        ---
        title: Client
        description: The PoliPage and AsyncPoliPage classes — the only entry points to the Python SDK.
        ---

        import MethodSignature from '@preset/components/MethodSignature.astro';

        <MethodSignature lang="python" code={`PoliPage(*, api_key: str | None = None, base_url: str | None = None, timeout: float = 60.0, max_retries: int = 2, retry_delay: float = 0.5, on_retry=None, on_error=None, http_client=None)`} />

        __LEDE__

        ## Constructor

        Every parameter is keyword-only and optional. `api_key` falls back to `POLI_PAGE_API_KEY` from the environment. See [Configuration](../../concepts/configuration/) for the full list of options and defaults, and [`PoliPageOptions`](../types/) for every field.

        ## Sync vs async

        The SDK ships two parallel client classes:

        - `PoliPage` — synchronous, backed by `httpx.Client`. Use as a context manager (`with PoliPage(...) as client:`) or call `.close()` to release sockets.
        - `AsyncPoliPage` — `asyncio`-native, backed by `httpx.AsyncClient`. Use `async with AsyncPoliPage(...) as client:` or call `await client.aclose()`.

        The two surfaces are byte-equivalent except for `async`/`await`.

        ## Namespaces

        The client exposes two namespaces:

        - [`render`](./methods/render-pdf/) — render PDFs (in memory, streaming, or to a stored document).
        - [`documents`](./methods/documents-get/) — fetch, preview, thumbnail, or delete stored documents.

        The standalone helpers [`render_to_file`](./methods/render-to-file/) and `async_render_to_file` live in `poli_page.fs`.

        ## See also
        - [Types](../types/)
        - [Errors](../errors/)
        - [Runtime support](../runtime-support/)
        """
    ).replace("__LEDE__", lede)


def _types_mdx(type_docs: dict[str, str]) -> str:
    lines = [
        "---",
        "title: Types",
        "description: Public types and dataclasses exported from poli_page.",
        "---",
        "",
        "The Python SDK exposes the types below. Import any of them from the top-level `poli_page` module:",
        "",
        "```python",
        "from poli_page import (",
        "    ProjectModeInput,",
        "    InlineModeInput,",
        "    RenderInput,",
        "    PreviewResult,",
        "    DocumentDescriptor,",
        "    AsyncDocumentDescriptor,",
        "    DocumentPreviewResult,",
        "    Thumbnail,",
        "    ThumbnailOptions,",
        "    RetryEvent,",
        ")",
        "```",
        "",
    ]
    for name in PUBLIC_TYPES:
        doc = type_docs.get(name, "").strip()
        first = doc.split("\n\n", 1)[0].replace("\n", " ").strip() if doc else ""
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(first or "Public type exported from `poli_page`.")
        lines.append("")
    lines.append(
        "For the full field lists on each dataclass and TypedDict, see "
        "[the source on GitHub](https://github.com/poli-page/sdk-python/blob/main/src/poli_page/types.py)."
    )
    lines.append("")
    return "\n".join(lines)


def _errors_mdx() -> str:
    return textwrap.dedent(
        """\
        ---
        title: Errors
        description: All error codes raised by PoliPageError, grouped by source.
        ---

        import ErrorTable from '@preset/components/ErrorTable.astro';

        Every failure raised by the SDK is an instance of `PoliPageError` with a `code`. SDK-internal codes are lowercase; codes from the API are uppercase.

        ## SDK-internal

        <ErrorTable errors={[{"code":"invalid_options","when":"Constructor arguments are missing or malformed."},{"code":"network_error","when":"TCP/TLS-level failure reaching the API. Retryable."},{"code":"timeout","when":"The request did not complete within `timeout`. Retryable."},{"code":"DOWNLOAD_FAILED","when":"The S3 second-hop download failed. Not retried by the SDK."}]} />

        ## Authentication

        <ErrorTable errors={[{"code":"MISSING_API_KEY","when":"No API key in the request."},{"code":"INVALID_API_KEY","when":"The API key is malformed or revoked."}]} />

        ## Billing and lifecycle

        <ErrorTable errors={[{"code":"PAYMENT_REQUIRED","when":"Organization billing is past due."},{"code":"FORBIDDEN","when":"The key does not have access to the requested resource."},{"code":"ORGANIZATION_CANCELLED","when":"The organization has been cancelled."},{"code":"ORGANIZATION_PURGED","when":"The organization has been purged."}]} />

        ## Not found

        <ErrorTable errors={[{"code":"NOT_FOUND","when":"The project/template slug does not exist or is not published."},{"code":"VERSION_NOT_FOUND","when":"The pinned version does not exist for this template."},{"code":"DOCUMENT_NOT_FOUND","when":"No stored document matches the supplied id."},{"code":"GONE","when":"The resource existed but has been deleted."}]} />

        ## Validation

        <ErrorTable errors={[{"code":"VALIDATION_ERROR","when":"`data` does not satisfy the template schema."},{"code":"MISSING_DATA","when":"Request body lacks the required `data` field."},{"code":"MISSING_PROJECT_OR_TEMPLATE","when":"Project mode call without both `project` and `template`."},{"code":"MISSING_TEMPLATE_SLUG","when":"Template slug is missing."},{"code":"PROJECT_REQUIRED_FOR_DOCUMENT","when":"Inline-shaped input on a PDF-producing method. Rejected locally before any HTTP call."},{"code":"INVALID_VERSION_FORMAT","when":"The `version` string is not a valid semver."},{"code":"VERSION_REQUIRED","when":"Live keys require a pinned `version`."},{"code":"INVALID_VERSION_FOR_KEY_ENV","when":"Sandbox key targeting a live-only version, or vice versa."}]} />

        ## Rate and quota

        <ErrorTable errors={[{"code":"QUOTA_EXCEEDED","when":"Per-key rate limit or monthly quota reached. Retryable."},{"code":"OVERAGE_CAP_EXCEEDED","when":"Hard overage cap reached. Not retryable."}]} />

        ## Server

        <ErrorTable errors={[{"code":"INTERNAL_ERROR","when":"The API returned 5xx. Retryable."}]} />
        """
    )


def _runtime_support_mdx(version: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        title: Runtime support
        description: Supported Python versions and operating systems for poli-page v{version}.
        ---

        import RuntimeMatrix from '@preset/components/RuntimeMatrix.astro';

        The Python SDK is built and tested against the matrix below.

        <RuntimeMatrix matrix={{{{
          runtimes: ['3.11', '3.12', '3.13'],
          os: ['linux', 'macos', 'windows'],
          cells: {{
            '3.11': {{ linux: 'tested', macos: 'tested', windows: 'tested' }},
            '3.12': {{ linux: 'tested', macos: 'tested', windows: 'tested' }},
            '3.13': {{ linux: 'tested', macos: 'tested', windows: 'tested' }},
          }},
        }}}} />

        The minimum supported Python version is **3.11**. Earlier versions lack PEP 655 (`Required` / `NotRequired` in `TypedDict`) which the public input types rely on.

        ## Dependencies

        - `httpx>=0.25,<1.0` — the only runtime dependency. No `pydantic`, no `typing-extensions`, no `requests`.
        """
    )


def _read_version() -> str:
    text = (SRC_ROOT / "_version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


# ----------------------------------------------------------------------------
# Type docstring collector
# ----------------------------------------------------------------------------


def _collect_type_docs() -> dict[str, str]:
    """Pull docstrings for the public types from `types.py`.

    Literal/TypeAlias entries (PageFormat, Orientation, …) don't have
    docstrings — we use placeholder copy in those cases.
    """
    out: dict[str, str] = {}
    types_mod = _parse_module(SRC_ROOT / "types.py")
    for node in types_mod.body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = ast.get_docstring(node) or ""
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            # Only catch top-level type aliases like `PageFormat = Literal[...]`.
            out.setdefault(node.target.id, "")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.setdefault(target.id, "")
    return out


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def main() -> None:
    version = _read_version()
    # Reset the output directory (gitignored) on every run.
    if REFERENCE_OUT.exists():
        shutil.rmtree(REFERENCE_OUT)
    (REFERENCE_OUT / "methods").mkdir(parents=True, exist_ok=True)

    # Parse the SDK source.
    sync_funcs = _collect_functions(SRC_ROOT / "_render.py")
    docs_funcs = _collect_functions(SRC_ROOT / "_documents.py")
    fs_funcs = _collect_functions(SRC_ROOT / "fs.py")
    client_doc = _collect_class_doc(SRC_ROOT / "_client.py", "PoliPage")
    type_docs = _collect_type_docs()

    # Build the client page.
    (REFERENCE_OUT / "client.mdx").write_text(_client_mdx(client_doc), encoding="utf-8")

    # Build one method page per entry in METHODS.
    for spec in METHODS:
        if "class" in spec:
            bucket = sync_funcs if spec["class"] == "RenderSync" else docs_funcs
            func_info = bucket.get(spec["class"], {}).get(spec["func"])
        elif spec.get("module") == "fs":
            func_info = fs_funcs["<module>"].get(spec["func"])
        else:
            func_info = None
        if func_info is None:
            raise SystemExit(f"extractor: could not resolve {spec['name']!r}")
        mdx = _method_mdx(spec, func_info)
        (REFERENCE_OUT / "methods" / f"{spec['slug']}.mdx").write_text(mdx, encoding="utf-8")

    # Build the types / errors / runtime-support pages.
    (REFERENCE_OUT / "types.mdx").write_text(_types_mdx(type_docs), encoding="utf-8")
    (REFERENCE_OUT / "errors.mdx").write_text(_errors_mdx(), encoding="utf-8")
    (REFERENCE_OUT / "runtime-support.mdx").write_text(
        _runtime_support_mdx(version), encoding="utf-8"
    )

    # _meta.json sidecar consumed by LangSwitcher (§4c).
    meta = {
        "language": "python",
        "package": {"kind": "pypi", "name": "poli-page", "version": version},
        "extractedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "extractorVersion": EXTRACTOR_VERSION,
        "client": {"name": "PoliPage", "kind": "class"},
        "methods": [{"slug": m["slug"], "name": m["name"]} for m in METHODS],
        "types": [{"slug": t.lower().replace("_", "-"), "name": t} for t in PUBLIC_TYPES],
        "errors": sorted(
            {row["code"] for rows in METHOD_ERRORS.values() for row in rows}
        ),
    }
    meta["errors"] = [{"code": c} for c in meta["errors"]]
    (REFERENCE_OUT / "_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    print(f"extractor: wrote {REFERENCE_OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
