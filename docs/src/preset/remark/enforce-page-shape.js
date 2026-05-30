import { parseFrontmatter } from './shared.js';
import { fromMarkdown } from 'mdast-util-from-markdown';
import { visit } from 'unist-util-visit';
import { join, relative } from 'node:path';
const ALLOWED_ASIDE_TYPES = new Set(['note', 'tip', 'caution']);
const MAX_DESCRIPTION_LENGTH = 155;
export function lintPageShape({ file, source, frontmatter, }) {
    const errs = [];
    const parsed = parseFrontmatter(source);
    // If the caller supplied frontmatter directly (e.g. Astro's MDX pipeline
    // strips `---` before invoking remark plugins), prefer it.
    const fm = frontmatter && Object.keys(frontmatter).length > 0 ? frontmatter : parsed.data;
    const { bodyLineOffset } = parsed;
    if (typeof fm.title !== 'string' || !fm.title.trim()) {
        errs.push({
            file,
            line: 1,
            rule: 'frontmatter-title',
            message: 'frontmatter must include a non-empty `title`',
        });
    }
    if (typeof fm.description !== 'string' || !fm.description.trim()) {
        errs.push({
            file,
            line: 1,
            rule: 'frontmatter-description',
            message: 'frontmatter must include a non-empty `description`',
        });
    }
    else if (fm.description.length > MAX_DESCRIPTION_LENGTH) {
        errs.push({
            file,
            line: 1,
            rule: 'description-length',
            message: `description is ${String(fm.description.length)} chars (max ${String(MAX_DESCRIPTION_LENGTH)})`,
        });
    }
    const bodyStart = source.startsWith('---\n') ? source.indexOf('\n---\n', 4) + 5 : 0;
    const body = source.slice(bodyStart);
    const tree = fromMarkdown(body);
    const headings = [];
    let sawNonHeadingBeforeFirstH2 = false;
    let firstH2Seen = false;
    visit(tree, (node) => {
        const line = (node.position?.start.line ?? 1) + bodyLineOffset - 1;
        if (node.type === 'heading') {
            const h = node;
            const text = (h.children ?? []).map((c) => c.value ?? '').join('').trim();
            headings.push({ depth: h.depth, text, line });
            if (h.depth === 1) {
                errs.push({
                    file,
                    line,
                    rule: 'no-manual-h1',
                    message: 'manual `#` H1 found; remove and rely on frontmatter title',
                });
            }
            if (h.depth === 2 && !firstH2Seen)
                firstH2Seen = true;
        }
        if (!firstH2Seen && node.type === 'paragraph') {
            sawNonHeadingBeforeFirstH2 = true;
        }
        if (node.type === 'code') {
            const c = node;
            if (!c.lang) {
                errs.push({
                    file,
                    line,
                    rule: 'code-block-language',
                    message: 'fenced code block must declare a language',
                });
            }
        }
    });
    if (firstH2Seen && !sawNonHeadingBeforeFirstH2) {
        const firstH2Line = headings.find((h) => h.depth === 2)?.line ?? 1;
        errs.push({
            file,
            line: firstH2Line,
            rule: 'lede-required',
            message: 'a lede paragraph is required between frontmatter and the first `##`',
        });
    }
    const isNarrative = file.startsWith('getting-started/') ||
        file.startsWith('concepts/') ||
        file.startsWith('production/');
    if (isNarrative) {
        const h2s = headings.filter((h) => h.depth === 2).map((h) => h.text);
        const lastTwo = h2s.slice(-2);
        if (lastTwo[0] !== 'Example' || lastTwo[1] !== 'See also') {
            errs.push({
                file,
                line: headings.at(-1)?.line ?? 1,
                rule: 'narrative-trailing-sections',
                message: 'narrative pages must end with `## Example` then `## See also` (in that order)',
            });
        }
    }
    const asideTypeRe = /<Aside\s+type=["']([^"']+)["']/g;
    let m;
    while ((m = asideTypeRe.exec(source)) !== null) {
        const type = m[1] ?? '';
        if (!ALLOWED_ASIDE_TYPES.has(type)) {
            const line = source.slice(0, m.index).split('\n').length;
            errs.push({
                file,
                line,
                rule: 'callout-type',
                message: `<Aside type="${type}"> is not allowed; use note | tip | caution`,
            });
        }
    }
    return errs;
}
export const enforcePageShape = function () {
    return (_tree, file) => {
        const source = String(file.value ?? '');
        // Astro's MDX integration strips `---` before invoking remark plugins
        // and attaches the parsed frontmatter to `file.data.astro.frontmatter`.
        // Read it from there so the lint sees title/description even when the
        // source no longer contains the frontmatter block.
        const data = file.data;
        const frontmatter = data.astro?.frontmatter;
        // Prefer a path relative to `<project>/src/content/docs/` so the lint's
        // narrative-section detection (`file.startsWith('getting-started/')` etc.)
        // matches in both standalone and Astro pipelines. Fall back to the raw
        // history entry when no cwd is available.
        const docsRoot = file.cwd ? join(file.cwd, 'src', 'content', 'docs') : '';
        const abs = file.path ?? file.history[0] ?? '';
        const fileRel = abs && docsRoot ? relative(docsRoot, abs) || abs : abs || 'unknown.mdx';
        const errs = lintPageShape(frontmatter
            ? { file: fileRel, source, frontmatter }
            : { file: fileRel, source });
        for (const e of errs) {
            file.message(`[${e.rule}] ${e.message}`, { line: e.line, column: 1 });
        }
        if (errs.length > 0) {
            file.fail(new Error(`enforce-page-shape: ${String(errs.length)} violation(s) in ${fileRel}`));
        }
    };
};
//# sourceMappingURL=enforce-page-shape.js.map