#!/usr/bin/env bash
# scripts/release.sh — manual release of `poli-page` to PyPI.
#
# This is the PRIMARY supported publishing path (per the engineering
# guide). The signed-attestation `.github/workflows/publish.yml` is an
# optional augment; this script is what most releases run.
#
# What it does, in order:
#   1. Pre-flight: on main, clean tree, tag doesn't already exist.
#   2. Verify: ruff, pyright, unit tests (integration if POLI_PAGE_API_KEY set).
#   3. Build: python -m build (wheel + sdist into dist/).
#   4. Inspect: twine check, list contents, show total size.
#   5. Confirm with the user before uploading.
#   6. Upload: twine upload (PyPI by default; --testpypi targets TestPyPI).
#   7. Tag: create v<version> locally (does NOT push — that's a separate step).
#
# Usage:
#   ./scripts/release.sh                  # full release to PyPI
#   ./scripts/release.sh --dry-run        # everything except the upload
#   ./scripts/release.sh --testpypi       # release to TestPyPI instead
#   ./scripts/release.sh --testpypi --dry-run
#
# Before running, you must have manually:
#   - bumped the version in src/poli_page/_version.py
#   - moved the [Unreleased] CHANGELOG section to a real version heading
#   - committed those changes to main

set -euo pipefail

cd "$(dirname "$0")/.."

DRY_RUN=0
TARGET="pypi"

for arg in "$@"; do
	case "$arg" in
		--dry-run)
			DRY_RUN=1
			;;
		--testpypi)
			TARGET="testpypi"
			;;
		*)
			echo "Unknown argument: $arg" >&2
			echo "Usage: $0 [--dry-run] [--testpypi]" >&2
			exit 2
			;;
	esac
done

# ─── colors (TTY-aware, NO_COLOR-aware) ─────────────────────────────────────
if [[ -t 1 && "${NO_COLOR:-}" != "1" ]]; then
	bold=$'\033[1m'
	dim=$'\033[2m'
	red=$'\033[31m'
	green=$'\033[32m'
	yellow=$'\033[33m'
	cyan=$'\033[36m'
	reset=$'\033[0m'
else
	bold=""; dim=""; red=""; green=""; yellow=""; cyan=""; reset=""
fi

step() { echo; echo "${cyan}${bold}▸ $1${reset}"; }
ok()   { echo "  ${green}✔${reset} $1"; }
fail() { echo "  ${red}✗${reset} $1" >&2; exit 1; }

# Pick the Python interpreter — prefer the project's .venv when present.
if [[ -x ".venv/bin/python" ]]; then
	PY=".venv/bin/python"
else
	PY="$(command -v python3 || command -v python)"
	[[ -z "$PY" ]] && fail "no python interpreter found"
fi

# ─── 1. version + branding ──────────────────────────────────────────────────
NAME="poli-page"
VERSION="$($PY -c 'import re,sys; m=re.search(r"__version__\s*=\s*\"([^\"]+)\"", open("src/poli_page/_version.py").read()); print(m.group(1)) if m else sys.exit("could not parse version")')"

echo
echo "  Releasing ${bold}${NAME}@${VERSION}${reset} → ${bold}${TARGET}${reset}"
[[ $DRY_RUN -eq 1 ]] && echo "  ${yellow}⚠  dry-run mode — will build but NOT upload${reset}"

# ─── 2. pre-flight ──────────────────────────────────────────────────────────
step "Pre-flight checks"

current_branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" != "main" ]]; then
	if [[ $DRY_RUN -eq 1 ]]; then
		echo "  ${yellow}⚠${reset} not on main (currently on $current_branch) — allowed for --dry-run"
	else
		fail "must be on main branch (currently on $current_branch)"
	fi
else
	ok "on main branch"
fi

if ! git diff --quiet HEAD || ! git diff --cached --quiet HEAD; then
	fail "working tree has uncommitted changes — commit or stash first"
fi
ok "working tree is clean"

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
	fail "tag v$VERSION already exists. Bump the version in src/poli_page/_version.py first."
fi
ok "tag v$VERSION does not exist yet"

# ─── 3. verify ──────────────────────────────────────────────────────────────
step "Lint + format + typecheck + unit tests"
$PY -m ruff check .
$PY -m ruff format --check .
$PY -m pyright
$PY -m pytest tests/unit/ tests/test_smoke.py -q
ok "all checks passed"

if [[ -n "${POLI_PAGE_API_KEY:-}" ]]; then
	step "Integration tests (POLI_PAGE_API_KEY is set)"
	$PY -m pytest tests/integration/ -m integration -q
	ok "integration tests passed"
else
	echo "  ${dim}(POLI_PAGE_API_KEY not set — skipping integration tests)${reset}"
fi

# ─── 4. build ───────────────────────────────────────────────────────────────
step "Build wheel + sdist"
rm -rf dist/
$PY -m build
ok "built dist/"

# ─── 5. inspect ─────────────────────────────────────────────────────────────
step "twine check"
$PY -m twine check dist/*
ok "twine check passed"

step "Pack contents"
for f in dist/*; do
	size=$(du -h "$f" | cut -f1)
	echo "  ${dim}${size}${reset}  $f"
done
echo
WHEEL=$(ls dist/*.whl | head -n1)
echo "  ${dim}Wheel contents:${reset}"
$PY -m zipfile -l "$WHEEL" | sed 's/^/    /'

# ─── 6. confirm ─────────────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 0 ]]; then
	echo
	read -r -p "  Upload ${bold}${NAME}@${VERSION}${reset} to ${bold}${TARGET}${reset}? [y/N] " confirm
	if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
		echo "  ${yellow}aborted by user${reset}"
		exit 0
	fi
fi

# ─── 7. upload ──────────────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
	step "Dry run — would have run: twine upload --repository ${TARGET} dist/*"
	echo
	echo "  ${green}${bold}✔ Dry run complete${reset}"
	exit 0
fi

step "Upload to ${TARGET}"
if [[ "$TARGET" == "testpypi" ]]; then
	$PY -m twine upload --repository testpypi dist/*
else
	$PY -m twine upload dist/*
fi
ok "uploaded $NAME@$VERSION"

# ─── 8. tag (local only — push manually) ────────────────────────────────────
step "Tag"
git tag "v$VERSION"
ok "created local tag v$VERSION"
echo "  ${dim}push it when ready:${reset} ${cyan}git push origin v$VERSION${reset}"

echo
echo "  ${green}${bold}✔ Released ${NAME}@${VERSION} to ${TARGET}${reset}"
if [[ "$TARGET" == "pypi" ]]; then
	echo "  ${dim}verify with:${reset} ${cyan}pip install ${NAME}==${VERSION}${reset}"
else
	echo "  ${dim}verify with:${reset} ${cyan}pip install --index-url https://test.pypi.org/simple/ ${NAME}==${VERSION}${reset}"
fi
echo
