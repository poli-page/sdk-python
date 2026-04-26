# CLAUDE.md

> Instructions for Claude Code agents working in this repository.

## 1. Repo at a glance

| Field        | Value |
| ------------ | ----- |
| Repository   | `poli-page/sdk-python` |
| Type         | Core SDK |
| Language     | Python |
| Registry     | PyPI — `poli-page` |
| Depends on   | — |
| Roadmap slot | P1.0 |

The full roadmap, the public API contract, and the reasoning behind the multi-repo split live in the platform repo (`poli-page/poli-page`) under `docs/onboarding/micka/`. Xavier will share the briefings with you. Read them before starting on a new repo:

- `agent-guide.md` — the master version of this file. If you want to update conventions, change it there first; this file is its inlined derivative.
- `project-briefing.md` — what Poli Page is, develop credentials, expected repo layout.
- `sdk-specification.md` — the API contract every SDK must implement.
- `sdk-roadmap.md` — what to build, in which order, why.

---

## 2. Working language

- **Code, comments, file names, commit messages, PR descriptions, repository documentation**: English.
- **Day-to-day conversation with Xavier**: French, tutoiement.
- **Conversation in this Claude Code session**: French is fine for the chat; the artifacts you produce (code, commits, READMEs) stay English.

---

## 3. Test-Driven Development is mandatory

TDD is the working method, not a "nice to have". The cycle is **RED → GREEN → refactor**:

1. **RED** — write the smallest possible failing test that captures the next bit of behavior.
2. **GREEN** — write the minimum code to make that test pass. No speculative generality, no extra branches.
3. **Refactor** — clean up the just-written code (or the call site) while the test stays green.

Every pull request lands as a sequence of these cycles, never as a "I wrote it all then added tests".

### What to test

- **Every public method** of the client class.
- **Every error path** — 4xx mapping, 5xx retry behaviour, network failure, timeout, malformed JSON.
- **Every retry edge case** — exponential backoff, max attempts, never retrying 4xx, honouring `Retry-After`.
- **Every input variant** — stored project (`project + template + version`) vs inline HTML (`template`), each rendering endpoint (PDF, preview, thumbnails).

### What NOT to over-test

- Don't test the language standard library or the HTTP client library — assume they work.
- Don't test private helpers in isolation if they're already exercised by a public-method test.
- Don't write tests that snapshot massive objects when an assertion on the field that matters would be clearer.

### Test layout

- Tests live in `tests/` (or the language's idiomatic location for this repo — see section 7).
- One test file per source file, mirroring the structure (`src/client.<ext>` → matching test file).
- Group integration tests under `tests/integration/` so they're runnable separately from the unit suite.
- **Unit tests** mock the HTTP transport, assert request shape and response handling. These are 90 %+ of the suite.
- **Integration tests** hit the real develop API with a `pp_test_*` key from `POLI_PAGE_API_KEY`. Render a known template, verify the PDF is non-empty and `Content-Type: application/pdf`. Keep them few and idempotent.

---

## 4. Robustness over shortcuts

Xavier's hard rule: **no hacks to make a test pass or a corner case go away.** If something is broken, fix the underlying cause. If a workaround is genuinely required (a third-party bug, an API quirk), document it inline with a one-line comment starting with `Why:` that explains the constraint — not the symptom.

Concrete corollaries:
- Don't catch and swallow errors to silence a test.
- Don't add test-environment branches in production code.
- Don't add fallbacks for cases that can't happen — trust internal code and framework guarantees.
- Validate at boundaries (user input, external APIs), not at every internal layer.

---

## 5. Code conventions

- **Style**: follow the dominant style guide of the language. Pin the formatter and linter major version in the manifest so contributors and CI agree.
- **No commented-out code.** Delete it; git remembers.
- **No `TODO` without a linked GitHub issue** — `// TODO(#42): refactor` is fine, `// TODO: refactor` is not.
- **No debug prints** in committed code.
- **Default to no comments.** Identifiers and short functions should explain themselves. Add a comment only when the *why* is non-obvious — a hidden constraint, a workaround, a surprising invariant. Comments that just restate what the code already says are noise.

---

## 6. Commits and Pull Requests

- **Conventional Commits** for every commit:
  - `feat:` new behaviour visible to users.
  - `fix:` bug fix (link an issue when it exists).
  - `docs:` documentation only.
  - `refactor:` no behaviour change, no test change.
  - `test:` only adds/changes tests.
  - `chore:` build, deps, tooling.
- **One concern per PR.** A reviewer should be able to land it in under 30 minutes.
- **PR description** includes: what changed, why, how it was tested. Link issues; mention any follow-ups deliberately deferred.
- **CI must be green** before merge.

---

## 7. Continuous Integration

The workflow lives at `.github/workflows/ci.yml`. The contract is identical across all 10 SDK repos:

- **Triggers**: every `push` (any branch) and every `pull_request` targeting `main`.
- **Matrix**: Python 3.11 / 3.12 / 3.13.
- **Jobs**: a single `test` job doing *Install → Lint → Test* in order.
- **Auto-skip is built in**: each step short-circuits with a friendly message when the relevant manifest, lint config, or test directory does not yet exist. This means a freshly scaffolded repo has a green pipeline from day one, and the pipeline starts running real work as soon as you add the manifest, lint config, and tests.

When working in this repo with Claude Code:
- After adding the manifest (`pyproject.toml`), the install step lights up.
- After adding a lint config (`ruff (lint + format)`), the lint step lights up.
- After adding the first test in `tests/`, the test step lights up.

If you change the workflow, the change MUST stay compatible with this auto-skip behaviour — never make CI fail because of "missing setup".

---

## 8. Per-language specifics for this repo

- **Test framework**: pytest
- **Lint / format**: ruff (lint + format)
- **Manifest file**: `pyproject.toml`
- **Run tests locally**: `pytest`
- **Run lint locally**: `ruff check . && ruff format --check .`

---

## 9. End-to-end "ship a feature" walk-through

This is what a single working day looks like:

1. **Pick** the next sliver from `sdk-specification.md` (or the open issue you're assigned to).
2. **Branch** from `main`: `git switch -c feat/<short-description>`.
3. **RED**: write one failing test that captures the slice. Run the suite — it fails on this test only.
4. **GREEN**: write the minimum code to pass. Run the suite — green.
5. **Refactor**: clean up. Suite stays green.
6. Repeat 3–5 for the next sliver of behaviour.
7. **Commit** with a Conventional Commits message.
8. **Push**. CI runs.
9. **Open a PR** with a clear description.
10. **Merge** when green and approved.

If a step takes more than half a day without a test going green, stop and talk to Xavier — the slice is probably too big.

---

## 10. Adding a new dependency

- Justify it. "We could write this in 20 lines" usually means we should write it in 20 lines.
- Pin the version (caret OK in Node, exact otherwise unless ecosystem convention says otherwise).
- Run the test suite before committing the lockfile change.
- Mention the new dependency and its purpose in the commit message.

---

## 11. When stuck

- Re-read `sdk-specification.md` — many "open questions" are already answered there.
- Compare with the Node SDK reference implementation: `github.com/poli-page/sdk-node` (npm: `@poli-page/sdk`).
- Ask Xavier early. A two-line message is faster than half a day rebuilding the wrong thing.
- If a CI failure looks unrelated to your change, look for the same failure on `main` first before assuming you caused it.
