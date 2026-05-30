import { readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
const REQUIRED = [
    'index.mdx',
    'getting-started/install.mdx',
    'getting-started/quick-start.mdx',
    'concepts/authentication.mdx',
    'concepts/render-modes.mdx',
    'concepts/output-handling.mdx',
    'concepts/configuration.mdx',
    'production/errors.mdx',
    'production/retries-and-idempotency.mdx',
    'production/cancellation.mdx',
    'production/observability.mdx',
    'reference/client.mdx',
    'reference/types.mdx',
    'reference/errors.mdx',
    'reference/runtime-support.mdx',
    'support/migration.mdx',
    'support/changelog.mdx',
    'support/license.mdx',
];
const REQUIRED_SET = new Set(REQUIRED);
const ALLOWED_TOP_LEVEL = new Set([
    'index.mdx',
    'getting-started',
    'concepts',
    'production',
    'reference',
    'support',
]);
const OPTIONAL_PERMITTED_PARENTS = [
    /^concepts\/integrations\//,
    /^concepts\/[a-z0-9-]+\.mdx$/,
    /^reference\/methods\//,
];
export function lintCanonicalSlugs(files) {
    const errs = [];
    const set = new Set(files);
    for (const required of REQUIRED) {
        if (!set.has(required)) {
            errs.push({
                file: required,
                line: 0,
                rule: 'required-page',
                message: `required page missing: ${required}`,
            });
        }
    }
    for (const file of files) {
        const top = file.split('/')[0] ?? '';
        if (!ALLOWED_TOP_LEVEL.has(top) && !ALLOWED_TOP_LEVEL.has(file)) {
            errs.push({
                file,
                line: 0,
                rule: 'top-level-section',
                message: `top-level entry outside the canonical 5 sections: ${top}`,
            });
            continue;
        }
        if (REQUIRED_SET.has(file))
            continue;
        const isOptionalOk = file === 'index.mdx' || OPTIONAL_PERMITTED_PARENTS.some((re) => re.test(file));
        if (!isOptionalOk) {
            errs.push({
                file,
                line: 0,
                rule: 'optional-page-location',
                message: `non-canonical page in unsupported location: ${file}`,
            });
        }
    }
    return errs;
}
function collectAllMdx(root, prefix = '') {
    const out = [];
    for (const entry of readdirSync(root, { withFileTypes: true })) {
        const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.isDirectory())
            out.push(...collectAllMdx(join(root, entry.name), rel));
        else if (entry.name.endsWith('.mdx'))
            out.push(rel);
    }
    return out;
}
let cached = null;
export const canonicalSlugs = function () {
    return (_tree, file) => {
        const docsRoot = join(file.cwd, 'src', 'content', 'docs');
        if (!cached || cached.docsRoot !== docsRoot) {
            cached = { docsRoot, errs: lintCanonicalSlugs(collectAllMdx(docsRoot)) };
        }
        const here = relative(docsRoot, file.path ?? '');
        const myErrs = cached.errs.filter((e) => e.file === here);
        for (const e of myErrs) {
            file.message(`[${e.rule}] ${e.message}`, { line: e.line || 1, column: 1 });
        }
        if (myErrs.length > 0) {
            file.fail(new Error(`canonical-slugs: ${String(myErrs.length)} violation(s) at ${here}`));
        }
    };
};
//# sourceMappingURL=canonical-slugs.js.map