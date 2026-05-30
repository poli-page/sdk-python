export const LANGUAGES = {
    go: { id: 'go', displayName: 'Go', exampleExt: '.go', packageKind: 'go-module' },
    node: { id: 'node', displayName: 'Node.js', exampleExt: '.ts', packageKind: 'npm' },
    php: { id: 'php', displayName: 'PHP', exampleExt: '.php', packageKind: 'composer' },
    python: { id: 'python', displayName: 'Python', exampleExt: '.py', packageKind: 'pypi' },
    ruby: { id: 'ruby', displayName: 'Ruby', exampleExt: '.rb', packageKind: 'rubygems' },
    rust: { id: 'rust', displayName: 'Rust', exampleExt: '.rs', packageKind: 'crate' },
};
export function getLanguage(id) {
    const lang = LANGUAGES[id];
    if (!lang)
        throw new Error(`unknown language: ${String(id)}`);
    return lang;
}
//# sourceMappingURL=languages.js.map