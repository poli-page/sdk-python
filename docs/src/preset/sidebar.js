export function buildSidebar() {
    return [
        {
            label: 'Getting started',
            items: [
                { slug: 'getting-started/install' },
                { slug: 'getting-started/quick-start' },
            ],
        },
        {
            label: 'Concepts',
            items: [
                { slug: 'concepts/authentication' },
                { slug: 'concepts/render-modes' },
                { slug: 'concepts/output-handling' },
                { slug: 'concepts/configuration' },
                // Starlight v0.39 requires `autogenerate` items to be nested inside
                // a labeled group, rather than being a labeled item themselves.
                { label: 'More concepts', items: [{ autogenerate: { directory: 'concepts' } }] },
            ],
        },
        {
            label: 'Production',
            items: [
                { slug: 'production/errors' },
                { slug: 'production/retries-and-idempotency' },
                { slug: 'production/cancellation' },
                { slug: 'production/observability' },
            ],
        },
        {
            label: 'Reference',
            items: [
                { slug: 'reference/client' },
                { label: 'Methods', items: [{ autogenerate: { directory: 'reference/methods' } }] },
                { slug: 'reference/types' },
                { slug: 'reference/errors' },
                { slug: 'reference/runtime-support' },
            ],
        },
        {
            label: 'Support',
            items: [
                { slug: 'support/migration' },
                { slug: 'support/changelog' },
                { slug: 'support/license' },
            ],
        },
    ];
}
//# sourceMappingURL=sidebar.js.map