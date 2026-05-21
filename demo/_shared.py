"""Shared helpers for the sync and async demos.

No external deps — stdlib only. Mirrors sdk-node/demo/_shared.mjs:
ANSI colors, step banner, file-URL formatting, and API-key resolution
(env → repo-root `.env` → interactive prompt → append to `.env`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------

_use_color: Final[bool] = sys.stdout.isatty() and os.environ.get("NO_COLOR") != "1"


def _ansi(code: str) -> _Wrap:
    return _Wrap(code)


class _Wrap:
    __slots__ = ("_code",)

    def __init__(self, code: str) -> None:
        self._code = code

    def __call__(self, value: object) -> str:
        if _use_color:
            return f"\x1b[{self._code}m{value}\x1b[0m"
        return str(value)


class _Colors:
    bold = _ansi("1")
    dim = _ansi("2")
    red = _ansi("31")
    green = _ansi("32")
    yellow = _ansi("33")
    cyan = _ansi("36")


c = _Colors()


def step(n: int, total: int, name: str) -> None:
    """Print a `[n/total] name` section banner in bold cyan."""
    print()
    print(c.cyan(c.bold(f"[{n}/{total}] {name}")))


def file_link(path: str | os.PathLike[str]) -> str:
    """Format a path as a clickable `file://` URL for modern terminals."""
    return c.cyan(Path(path).resolve().as_uri())


# ---------------------------------------------------------------------------
# .env handling — simple KEY=value parser, no external deps
# ---------------------------------------------------------------------------

# `.env` lives at the repo root — one level above the demo/ folder. Every
# demo (sync, async, eventual framework recipes) reads from the same file.
ENV_FILE: Final[Path] = Path(__file__).resolve().parent.parent / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq == -1:
            continue
        key = line[:eq].strip()
        value = line[eq + 1 :].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        result[key] = value
    return result


def _append_to_env_file(path: Path, key: str, value: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    needs_leading_newline = bool(existing) and not existing.endswith("\n")
    with path.open("a", encoding="utf-8") as fh:
        if needs_leading_newline:
            fh.write("\n")
        fh.write(f"{key}={value}\n")


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def resolve_base_url() -> str:
    """Resolve the API base URL: env → `.env` → default `https://api.poli.page`."""
    if "POLI_PAGE_BASE_URL" in os.environ:
        return os.environ["POLI_PAGE_BASE_URL"]
    from_file = _read_env_file(ENV_FILE).get("POLI_PAGE_BASE_URL")
    if from_file:
        return from_file
    return "https://api.poli.page"


def ensure_api_key() -> str:
    """Resolve `POLI_PAGE_API_KEY`. Prompt and persist on first run.

    Resolution order:
      1. `os.environ['POLI_PAGE_API_KEY']` — wins for CI / shell.
      2. `.env` at the repo root.
      3. Interactive prompt; pasted key appends to `.env` for future runs.

    Exits with a friendly error if the input doesn't start with `pp_test_`.
    """
    if "POLI_PAGE_API_KEY" in os.environ:
        return os.environ["POLI_PAGE_API_KEY"]

    from_file = _read_env_file(ENV_FILE).get("POLI_PAGE_API_KEY")
    if from_file:
        print(c.dim(f"  using POLI_PAGE_API_KEY from {ENV_FILE}"))
        return from_file

    rule = c.dim("  ─────────────────────────────────────────────────────────────────────")
    print()
    print(rule)
    print(c.bold(c.yellow("   No POLI_PAGE_API_KEY found.")))
    print(rule)
    print()
    print(
        "   This demo needs a test key (" + c.cyan("pp_test_*") + ") to talk to the Poli Page API."
    )
    print("   Test keys never bill or send real documents.")
    print()
    print(c.bold("   How to get one:"))
    print("     1. Sign in at " + c.cyan("https://app.poli.page"))
    print("     2. Go to your organization's API keys page:")
    print("          " + c.cyan("https://app.poli.page/orgs/{YOUR_ORG}/keys"))
    print(c.dim("        (replace {YOUR_ORG} with your org slug — visible in the"))
    print(c.dim("         dashboard URL when you're inside your organization)"))
    print("     3. Click 'Create key' and copy the value (starts with " + c.cyan("pp_test_") + ").")
    print()
    print("   Paste it below — we'll save it to " + c.cyan(str(ENV_FILE)) + " so future")
    print("   runs pick it up automatically. (You can also set")
    print("   " + c.dim("POLI_PAGE_API_KEY") + " in your shell — that wins over the file.)")
    print()

    try:
        key = input(c.bold("   Paste your pp_test_* key") + " (or Ctrl-C to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)

    if not key.startswith("pp_test_"):
        print()
        print("  " + c.red("✗") + " Expected a key starting with `pp_test_`. Aborting.")
        print()
        sys.exit(1)

    _append_to_env_file(ENV_FILE, "POLI_PAGE_API_KEY", key)
    print(f"  {c.green('✔')} saved to {c.cyan(str(ENV_FILE))}")
    print()
    return key
