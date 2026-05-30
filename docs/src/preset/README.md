# Vendored Starlight preset

The files in this directory are vendored from the local reference repo at `sdk-docs-preset/`. They define the shared sidebar, theme, lint plugins, and Astro components used by every Poli Page SDK doc site.

**This is a copy, not a dependency.** The site does not depend on any npm package named `@poli-page/starlight-preset`. Imports use the local alias `@preset` (configured in `astro.config.mjs` and `tsconfig.json`).

## Updating

When the upstream preset changes:

1. Edit the source in `sdk-docs-preset/`.
2. Run `npm run build` and `npm test` there to validate.
3. Sync the relevant files back into `docs/src/preset/`. The mapping is:

| Source (`sdk-docs-preset/`)   | Destination (`docs/src/preset/`) |
|-------------------------------|----------------------------------|
| `dist/*.js`                   | (flat)                           |
| `dist/remark/*.js`            | `remark/`                        |
| `dist/canonical-*.json`       | (flat)                           |
| `src/components/*.astro`      | `components/`                    |
| `src/styles/poli-page.css`    | `styles/`                        |

4. After syncing, run `npm run build` in `docs/` to verify nothing regressed.

The same sync needs to happen for every other SDK that vendors the preset (sdk-go, sdk-python, sdk-ruby, sdk-php, sdk-rust). That's the trade-off of skipping the npm-published path.

## What is NOT vendored

- TypeScript source files (`src/*.ts`) — we ship the compiled `dist/*.js` instead so the docs build doesn't need to recompile the preset.
- `templates/*.mdx` — not used by this site.
- The `poli-docs-scaffold` CLI — not invoked at site-build time.
