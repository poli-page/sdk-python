# Contributing to `poli-page`

Thanks for your interest. A few short rules:

## Working method

We use **TDD**: write a failing test first, then the minimum code to pass.
See the platform `agent-guide.md` for the full methodology.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                     # unit tests
ruff check . && ruff format --check .   # lint + format
pyright                    # strict on src/, basic on tests/
mypy src/                  # secondary type-checker (not a CI gate; informational)
python -m build            # build wheel + sdist into dist/
```

The `dev` extra installs `pytest`, `pytest-asyncio`, `respx`, `ruff`,
`pyright`, `mypy`, and `build`. No other dev tooling is required.

## API reference site

The reference at https://docs.poli.page/reference/sdk/python/ is built
from docstrings by [`pdoc`](https://pdoc.dev/) and deployed via
`.github/workflows/docs.yml` on every push to `main` and every published
release. There are no hand-written pages — every section in the site
comes from a docstring in `src/poli_page/`. To preview locally:

```bash
python -m pdoc poli_page --output-directory docs-site
open docs-site/index.html
```

If your change touches the public API, eyeball the generated page for
the modified module before merging.

## Lockfile (`uv.lock`)

The repo ships a `uv.lock` for reproducible dev environments. CI does not
yet consume it (see `.github/workflows/ci.yml`), but contributors who want
the exact same dependency set can use [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras          # creates .venv from uv.lock
uv run pytest                 # runs tests against the locked set
```

Regenerate after editing `pyproject.toml` dependencies:

```bash
uv lock                       # rewrite uv.lock to match pyproject.toml
```

Commit the resulting `uv.lock` change in the same PR as the dependency edit.

## Integration tests

Integration tests hit the live API. They're gated on `POLI_PAGE_API_KEY`
and skipped when the env var is unset:

```bash
export POLI_PAGE_API_KEY=pp_test_...
pytest tests/integration/ -m integration
```

The full set of integration tests round-trips every public method against
the auto-provisioned `getting-started/welcome/1.0.0` template.

## Releasing

Releases are **manual**. There is no CI workflow that auto-publishes — by
design. The only supported publishing path is `scripts/release.sh`.

1. Bump version in `src/poli_page/_version.py` (`__version__ = "X.Y.Z"`).
2. Move `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`.
3. Commit `chore(release): X.Y.Z`.
4. From a clean main branch, run:
   ```bash
   ./scripts/release.sh             # full release to PyPI
   ./scripts/release.sh --dry-run   # everything except the actual publish
   ./scripts/release.sh --testpypi  # publish to TestPyPI instead
   ```
   The script runs pre-flight checks (clean tree, on main, tag doesn't
   exist), lint / typecheck / unit tests, builds the wheel + sdist,
   inspects with `twine check`, prints contents + size, and asks you to
   confirm before publishing. On success, it creates a local `vX.Y.Z` tag.
5. Push the tag manually when you're ready: `git push origin vX.Y.Z`.

You must have a PyPI token in `~/.pypirc` (or be using `twine`'s OS-keychain
support). The script does not touch CI secrets — it's a local-machine
release.

### Stable vs. prerelease channels

PyPI natively supports prereleases — `pip install` ignores them unless
`--pre` is passed. Suffix scheme (PEP 440): `1.2.3rc1`, `2.0.0b0`,
`1.3.0a2`.

#### Cutting a prerelease

1. Bump `__version__` in `src/poli_page/_version.py` to e.g. `2.0.0rc1`.
2. Move `[Unreleased]` entries under `[2.0.0rc1] - YYYY-MM-DD` in
   `CHANGELOG.md`.
3. Commit, then run `./scripts/release.sh`. PyPI auto-detects the suffix
   and ships it to the prerelease channel; stable installs are
   unaffected.
4. Tag the commit locally and push: `git tag v2.0.0rc1 && git push origin v2.0.0rc1`.

Users opt in:

```bash
pip install --pre poli-page          # latest prerelease
pip install poli-page==2.0.0rc1      # specific prerelease
```

#### Promoting a prerelease to stable

When the prerelease is ready, cut a stable release at the same semver
minus the suffix:

1. Bump `__version__` to `2.0.0` (drop the suffix).
2. Move the prerelease entries in `CHANGELOG.md` under `[2.0.0] - YYYY-MM-DD`.
3. Run `./scripts/release.sh`.

Stable and prerelease channels must never point at the same version —
once a prerelease is promoted, the next prerelease starts a new pre-suffix
sequence (e.g. `2.1.0b0`).

## PyPI Trusted Publishing

The `workflow_dispatch`-gated `.github/workflows/publish.yml` provides a
signed-attestation path for releases that want PEP 740 attestations
attached automatically. The local `scripts/release.sh` remains the
primary, recommended path; the workflow is the optional augment.
