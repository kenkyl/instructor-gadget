// Where a grounded claim comes from: the doc and section anchor (as the org docs page lists
// them) and the words quoted from it, which the backend checked are really there (ADR-0029).
import type { Schemas } from "@/lib/api";

type Citation = Schemas["Citation"];

export function DocCitation({ citation }: { citation: Citation }) {
  return (
    <span className="space-y-1">
      <span className="text-muted-foreground block font-mono text-xs">
        {citation.doc} › {citation.section}
      </span>
      <span className="block">“{citation.quote}”</span>
    </span>
  );
}
