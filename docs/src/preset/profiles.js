export const MIGRATION_PAGE = 'support/migration.mdx';
/** Matches `concepts/<idiom>.mdx`, the one optional location both profiles share. */
export const CONCEPT_IDIOM_PAGE = /^concepts\/[a-z0-9-]+\.mdx$/;
const SDK = {
    id: 'sdk',
    requiredPages: [
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
        MIGRATION_PAGE,
        'support/changelog.mdx',
        'support/license.mdx',
    ],
    optionalPages: [/^concepts\/integrations\//, CONCEPT_IDIOM_PAGE, /^reference\/methods\//],
    migrationPage: 'required',
};
const INTEGRATION = {
    id: 'integration',
    requiredPages: [
        'index.mdx',
        'getting-started/install.mdx',
        'getting-started/quick-start.mdx',
        'concepts/configuration.mdx',
        'concepts/client-access.mdx',
        'concepts/responses.mdx',
        'production/errors.mdx',
        'production/observability.mdx',
        'production/testing.mdx',
        'reference/api.mdx',
        'reference/sdk.mdx',
        'support/changelog.mdx',
        'support/license.mdx',
    ],
    optionalPages: [CONCEPT_IDIOM_PAGE],
    migrationPage: 'with-migration-md',
};
export const PROFILES = {
    sdk: SDK,
    integration: INTEGRATION,
};
export function getProfile(id) {
    const profile = PROFILES[id];
    if (!profile)
        throw new Error(`unknown profile: ${String(id)}`);
    return profile;
}
