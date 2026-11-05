import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { parse as parseYaml } from 'yaml';
export function formatLintError(e) {
    return `${e.file}:${e.line}  [${e.rule}]  ${e.message}`;
}
/**
 * The message of the error a lint plugin passes to `file.fail`: a summary
 * line, then one `formatLintError` line per violation. Astro prints this
 * error and not the file's messages, so the violations must be in it.
 */
export function formatLintFailure(summary, errs) {
    return [summary, ...errs.map((e) => `  ${formatLintError(e)}`)].join('\n');
}
export function parseFrontmatter(source) {
    if (!source.startsWith('---\n')) {
        return { data: {}, bodyLineOffset: 1 };
    }
    const end = source.indexOf('\n---\n', 4);
    if (end === -1)
        return { data: {}, bodyLineOffset: 1 };
    const yaml = source.slice(4, end);
    const data = parseYaml(yaml);
    const headerLines = yaml.split('\n').length + 2;
    return { data: data ?? {}, bodyLineOffset: headerLines + 1 };
}
/** Every `.mdx` page under `docsRoot`, as paths relative to it (`concepts/foo.mdx`). */
export function listMdxPages(docsRoot, prefix = '') {
    const out = [];
    for (const entry of readdirSync(docsRoot, { withFileTypes: true })) {
        const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.isDirectory())
            out.push(...listMdxPages(join(docsRoot, entry.name), rel));
        else if (entry.name.endsWith('.mdx'))
            out.push(rel);
    }
    return out;
}
