import { getLanguage } from './languages.js';
import { buildSidebar } from './sidebar.js';
import { POLI_PAGE_CSS_PATH } from './theme.js';
export function polipagePreset(opts) {
    const lang = getLanguage(opts.language);
    return {
        title: `Poli Page ${lang.displayName} SDK`,
        description: `Render polished PDFs from HTML templates — ${lang.displayName} SDK.`,
        sidebar: buildSidebar(),
        social: [
            { icon: 'github', label: 'GitHub', href: `https://github.com/${opts.repo}` },
        ],
        customCss: [POLI_PAGE_CSS_PATH],
        editLink: { baseUrl: `https://github.com/${opts.repo}/edit/main/docs/` },
    };
}
//# sourceMappingURL=preset.js.map