// Lesson prose is LLM-written Markdown. react-markdown builds React elements and never renders
// raw HTML (no rehype-raw), so model output can't inject markup; javascript: URLs are dropped
// by its default urlTransform.
import ReactMarkdown from "react-markdown";

import { linkCitations } from "@/lib/citations";

/** `cited`: the text carries `[n]` markers for a grounded lesson's sources (ADR-0029). */
export function Markdown({ children, cited = false }: { children: string; cited?: boolean }) {
  return (
    <div className="lesson-md">
      <ReactMarkdown
        components={{
          a: ({ href, children: label }) =>
            href?.startsWith("#cite-") ? (
              <sup>
                <a href={href} className="cite-marker">
                  {label}
                </a>
              </sup>
            ) : (
              <a href={href}>{label}</a>
            ),
        }}
      >
        {cited ? linkCitations(children) : children}
      </ReactMarkdown>
    </div>
  );
}
