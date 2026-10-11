// Lesson prose is LLM-written Markdown. react-markdown builds React elements and never renders
// raw HTML (no rehype-raw), so model output can't inject markup; javascript: URLs are dropped
// by its default urlTransform.
import ReactMarkdown from "react-markdown";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="lesson-md">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
