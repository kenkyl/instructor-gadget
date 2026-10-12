// A plan version's diff (spec §4.8: every change shows a diff and a why), drawn like a code diff:
// a gutter sign and a tinted line per change.
import type { Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

type PlanDiff = Schemas["PlanDiff"];
type Kind = "add" | "remove" | "change" | "skip";

const SIGN: Record<Kind, string> = { add: "+", remove: "−", change: "~", skip: "»" };
const LINE: Record<Kind, string> = {
  add: "bg-green/12 [&>span:first-child]:text-green-ink",
  remove: "bg-red/12 [&>span:first-child]:text-red-ink",
  change: "bg-yellow/12 [&>span:first-child]:text-yellow-ink",
  skip: "bg-violet/12 [&>span:first-child]:text-violet-ink",
};
const KIND_LABEL: Record<Kind, string> = { add: "Added", remove: "Removed", change: "Changed", skip: "Test out" };

export function PlanDiffView({ diff, titles }: { diff: PlanDiff; titles: Record<string, string> }) {
  const name = (id: string) => titles[id] ?? id;
  const status = (s: string) => s.replace("_", " ");
  const rows: { kind: Kind; text: string }[] = [
    ...(diff.added ?? []).map((c) => ({ kind: "add" as const, text: c.title })),
    ...(diff.removed ?? []).map((id) => ({ kind: "remove" as const, text: name(id) })),
    ...(diff.prereq_changes ?? []).flatMap((p) =>
      (p.added ?? []).map((a) => ({ kind: "change" as const, text: `${name(p.concept_id)} now needs ${name(a)}` })),
    ),
    ...(diff.status_changes ?? []).map((s) => ({
      kind: "change" as const,
      text: `${name(s.concept_id)}: ${status(s.old)} → ${status(s.new)}`,
    })),
    ...(diff.test_out ?? []).map((id) => ({ kind: "skip" as const, text: `${name(id)}: lesson skipped, quiz next` })),
  ];
  if (!rows.length) return null;
  return (
    <ul className="overflow-hidden rounded-md border text-sm">
      {rows.map((r, i) => (
        <li key={i} className={cn("flex gap-3 px-3 py-1.5", LINE[r.kind])}>
          <span className="num w-3 shrink-0 text-center font-semibold" aria-hidden="true">
            {SIGN[r.kind]}
          </span>
          <span>
            <span className="sr-only">{KIND_LABEL[r.kind]}: </span>
            {r.text}
          </span>
        </li>
      ))}
    </ul>
  );
}
