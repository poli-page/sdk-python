#!/usr/bin/env bash
# scripts/check-contract-version.sh — the release's major.minor must be the
# pinned API contract's.
#
# Usage: scripts/check-contract-version.sh X.Y.Z   (or vX.Y.Z, or a PEP 440
#        prerelease such as 0.13.0rc1)
#
# The SDK shares its major.minor with the Poli Page API, so a release X.Y.z
# must pass the API contract X.Y. This reads the contract commit pinned in
# .github/workflows/ci.yml (never its `# vX.Y.Z` comment, never a commented-out
# line), checks that publish.yml pins the same commit, lists the contract
# repository's tags, and fails unless that commit carries a stable tag vX.Y.Z
# with the release's major.minor. Patch numbers are free.
#
# Run by scripts/release.sh and by the Publish workflow. API_CONTRACT_REMOTE
# overrides the contract repository (the tests point it at a local one).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$REPO_ROOT/.github/workflows/ci.yml"
REMOTE="${API_CONTRACT_REMOTE:-https://github.com/poli-page/api-contract.git}"

fail() { echo "check-contract-version: $1" >&2; exit 1; }

[ "$#" -eq 1 ] || fail "usage: $(basename "$0") X.Y.Z"
version="${1#v}"
if ! [[ "$version" =~ ^([0-9]+)\.([0-9]+)\.[0-9]+([^0-9].*)?$ ]]; then
	fail "release version '$1' is not X.Y.Z"
fi
release_minor="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"

# The pinned commit of a `uses:` step line; a commented-out line does not count.
pin_of() {
	sed -n 's|^[[:space:]]*-\{0,1\}[[:space:]]*uses:[[:space:]]*poli-page/api-contract@\([0-9a-f]\{40\}\).*|\1|p' "$1" | head -n 1
}

contract_sha="$(pin_of "$WORKFLOW")"
[ -n "$contract_sha" ] || fail "no poli-page/api-contract pin found in .github/workflows/ci.yml"

# The Publish workflow runs the contract tests against its own pin: it must be the same one.
PUBLISH="$REPO_ROOT/.github/workflows/publish.yml"
if [ -f "$PUBLISH" ]; then
	publish_sha="$(pin_of "$PUBLISH")"
	[ "$publish_sha" = "$contract_sha" ] ||
		fail "publish.yml pins the API contract ${publish_sha:-nowhere}, ci.yml pins $contract_sha: pin the same commit in both"
fi

tags="$(git ls-remote --tags "$REMOTE")" || fail "cannot list the tags of $REMOTE"

# An annotated tag is listed twice: its own object, then `^{}` with the commit
# it points at. A lightweight tag is listed once, with its commit.
stable_tags="$(
	awk -v sha="$contract_sha" '$1 == sha { ref = $2; sub(/^refs\/tags\//, "", ref); sub(/\^\{\}$/, "", ref); print ref }' <<<"$tags" |
		grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -u -V || true
)"
short_sha="${contract_sha:0:8}"
if [ -z "$stable_tags" ]; then
	fail "release v$version needs the API contract v$release_minor.x, but the pinned contract commit $short_sha has no stable vX.Y.Z tag: pin a released contract"
fi

while IFS= read -r tag; do
	if [[ "$tag" =~ ^v([0-9]+)\.([0-9]+)\. ]] && [ "${BASH_REMATCH[1]}.${BASH_REMATCH[2]}" = "$release_minor" ]; then
		echo "API contract $tag ($short_sha) matches release v$version"
		exit 0
	fi
done <<<"$stable_tags"

pinned="$(tr '\n' ' ' <<<"$stable_tags" | sed 's/ $//')"
# The newest of the commit's tags, which may carry two (an unchanged contract).
[[ "$(tail -n 1 <<<"$stable_tags")" =~ ^v([0-9]+)\.([0-9]+)\. ]]
fail "release v$version and the pinned API contract $pinned ($short_sha) differ in major.minor: pin the contract v$release_minor.x, or release v${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.x"
