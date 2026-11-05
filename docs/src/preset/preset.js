import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { getLanguage } from './languages.js';
import { listMdxPages } from './remark/shared.js';
import { buildSidebar } from './sidebar.js';
import { POLI_PAGE_CSS_PATH } from './theme.js';
export function polipagePreset(opts) {
    if (opts.profile === 'integration')
        return integrationPreset(opts);
    const lang = getLanguage(opts.language);
    return {
        title: `Poli Page ${lang.displayName} SDK`,
        description: `Render polished PDFs from HTML templates — ${lang.displayName} SDK.`,
        sidebar: buildSidebar('sdk'),
        ...repoLinks(opts.repo),
    };
}
function integrationPreset(opts) {
    // Sites call the preset from untyped astro.config.mjs, so check the options
    // here, as the SDK branch does through getLanguage.
    if (typeof opts.framework !== 'string' || !opts.framework.trim()) {
        throw new Error('integration profile: `framework` must be the framework display name, e.g. `NestJS`');
    }
    if (typeof opts.repo !== 'string' || !/^[^/\s]+\/[^/\s]+$/.test(opts.repo)) {
        throw new Error(`integration profile: \`repo\` must be \`owner/name\`, got ${JSON.stringify(opts.repo)}`);
    }
    // The site folder is process.cwd(), the folder `astro build` runs in. The
    // lint plugins resolve the site from the same place (vfile's cwd), so the
    // sidebar and the lint always read the same pages.
    const docsRoot = join(process.cwd(), 'src', 'content', 'docs');
    if (!existsSync(docsRoot)) {
        throw new Error(`integration profile: no src/content/docs/ under ${process.cwd()}; run \`astro build\` in the site folder (the repo's docs/)`);
    }
    return {
        title: `Poli Page ${opts.framework} integration`,
        description: `Render polished PDFs from HTML templates — ${opts.framework} integration.`,
        sidebar: buildSidebar('integration', listMdxPages(docsRoot)),
        ...repoLinks(opts.repo),
    };
}
function repoLinks(repo) {
    return {
        social: [{ icon: 'github', label: 'GitHub', href: `https://github.com/${repo}` }],
        customCss: [POLI_PAGE_CSS_PATH],
        editLink: { baseUrl: `https://github.com/${repo}/edit/main/docs/` },
    };
}
