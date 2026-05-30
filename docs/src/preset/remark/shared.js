import { parse as parseYaml } from 'yaml';
export function formatLintError(e) {
    return `${e.file}:${e.line}  [${e.rule}]  ${e.message}`;
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
//# sourceMappingURL=shared.js.map