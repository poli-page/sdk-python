import { existsSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { getProfile, MIGRATION_PAGE } from '../profiles.js';
import { formatLintFailure, listMdxPages } from './shared.js';
const ALLOWED_TOP_LEVEL = new Set([
    'index.mdx',
    'getting-started',
    'concepts',
    'production',
    'reference',
    'support',
]);
export function lintCanonicalSlugs(files, opts = {}) {
    const profile = getProfile(opts.profile ?? 'sdk');
    const errs = [];
    const set = new Set(files);
    const required = new Set(profile.requiredPages);
    for (const page of profile.requiredPages) {
        if (!set.has(page)) {
            errs.push({
                file: page,
                line: 0,
                rule: 'required-page',
                message: `required page missing: ${page}`,
            });
        }
    }
    if (profile.migrationPage === 'with-migration-md') {
        const hasGuide = opts.repoHasMigrationGuide ?? false;
        if (hasGuide && !set.has(MIGRATION_PAGE)) {
            errs.push({
                file: MIGRATION_PAGE,
                line: 0,
                rule: 'migration-page',
                message: `the repo has MIGRATION.md, so ${MIGRATION_PAGE} is required`,
            });
        }
        else if (!hasGuide && set.has(MIGRATION_PAGE)) {
            errs.push({
                file: MIGRATION_PAGE,
                line: 0,
                rule: 'migration-page',
                message: `the repo has no MIGRATION.md, so ${MIGRATION_PAGE} is not allowed`,
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
        if (required.has(file))
            continue;
        // The migration rule above has already judged this page.
        if (file === MIGRATION_PAGE && profile.migrationPage === 'with-migration-md')
            continue;
        const isOptionalOk = profile.optionalPages.some((re) => re.test(file));
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
let cached = null;
export const canonicalSlugs = function (options = {}) {
    const profile = options.profile ?? 'sdk';
    return (_tree, file) => {
        // The site is the Astro project (`file.cwd`); it lives in `docs/` at the
        // repo root, so the repo's MIGRATION.md is one level above it.
        const docsRoot = join(file.cwd, 'src', 'content', 'docs');
        const key = `${profile}\0${docsRoot}`;
        if (!cached || cached.key !== key) {
            const pages = listMdxPages(docsRoot);
            const repoHasMigrationGuide = existsSync(join(dirname(file.cwd), 'MIGRATION.md'));
            cached = {
                key,
                pages: new Set(pages),
                errs: lintCanonicalSlugs(pages, { profile, repoHasMigrationGuide }),
            };
        }
        const { pages, errs } = cached;
        const here = relative(docsRoot, file.path ?? '');
        // A violation about a page that exists is reported on that page. One about
        // a page that does not exist (a missing required page) is reported on
        // every page, since no page of its own will ever be processed.
        const myErrs = errs.filter((e) => e.file === here || !pages.has(e.file));
        for (const e of myErrs) {
            file.message(`[${e.rule}] ${e.message}`, { line: e.line || 1, column: 1 });
        }
        if (myErrs.length > 0) {
            file.fail(new Error(formatLintFailure(`canonical-slugs: ${String(myErrs.length)} violation(s) at ${here}`, myErrs)));
        }
    };
};
