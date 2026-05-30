import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';
import starlight from '@astrojs/starlight';
import { unified } from '@astrojs/markdown-remark';

import {
  polipagePreset,
  enforcePageShape,
  canonicalSlugs,
} from './src/preset/index.js';

// The preset lives at docs/src/preset/. It's vendored from the
// sdk-docs-preset reference repo; see docs/src/preset/README.md.
// The `@preset` alias is what every MDX file uses to import shared
// components (e.g. `@preset/components/ApiKeyCallout.astro`) and the
// shared CSS path (`@preset/styles/poli-page.css`).
const presetRoot = fileURLToPath(new URL('./src/preset', import.meta.url));

export default defineConfig({
  site: 'https://poli-page.github.io',
  base: '/sdk-python',
  vite: {
    resolve: {
      alias: { '@preset': presetRoot },
    },
  },
  markdown: {
    processor: unified({
      remarkPlugins: [enforcePageShape, canonicalSlugs],
    }),
  },
  integrations: [
    starlight(
      polipagePreset({
        language: 'python',
        repo: 'poli-page/sdk-python',
        package: { kind: 'pypi', name: 'poli-page' },
        minRuntime: '3.11',
      }),
    ),
  ],
});
