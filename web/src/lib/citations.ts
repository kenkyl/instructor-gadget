// Grounded lessons mark each claim from the org's docs with `[n]`, pointing at citations[n-1]
// (ADR-0029). Same rule as backend/agent/sources.py citation_markers(): markers in code (fenced
// blocks, inline spans) and link text (`[3](…)`) aren't citations, so they're left alone.
// Code to keep verbatim: a fenced block (group 1 = its fence), or an inline span (group 2).
const CODE = /^ {0,3}(`{3,}|~{3,})[^]*?^ {0,3}\1[ \t]*$|(`+)[^]+?\2/gm;
const MARKER = /\[(\d{1,2})\](?!\()/g;

export const citeId = (n: number) => `cite-${n}`;

/** Turn each `[n]` marker in prose into a link to the lesson's source list. */
export function linkCitations(markdown: string): string {
  const link = (prose: string) =>
    prose.replace(MARKER, (_, n: string) => `[[${n}]](#${citeId(Number(n))})`);
  let out = "";
  let last = 0;
  for (const m of markdown.matchAll(CODE)) {
    out += link(markdown.slice(last, m.index)) + m[0];
    last = m.index + m[0].length;
  }
  return out + link(markdown.slice(last));
}
