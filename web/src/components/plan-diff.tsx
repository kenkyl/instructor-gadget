// A plan version's diff (spec §4.8: every change shows a diff and a why).
import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api";

type PlanDiff = Schemas["PlanDiff"];

export function PlanDiffView({ diff, titles }: { diff: PlanDiff; titles: Record<string, string> }) {
  const name = (id: string) => titles[id] ?? id;
  const rows: { tag: string; text: string }[] = [
    ...(diff.added ?? []).map((c) => ({ tag: "added", text: c.title })),
    ...(diff.removed ?? []).map((id) => ({ tag: "removed", text: name(id) })),
    ...(diff.prereq_changes ?? []).flatMap((p) =>
      (p.added ?? []).map((a) => ({ tag: "prereq", text: `${name(p.concept_id)} now needs ${name(a)}` })),
    ),
    ...(diff.status_changes ?? []).map((s) => ({
      tag: s.new,
      text: `${name(s.concept_id)}: ${s.old.replace("_", " ")} → ${s.new.replace("_", " ")}`,
    })),
    ...(diff.test_out ?? []).map((id) => ({ tag: "test out", text: `${name(id)}: lesson skipped, quiz next` })),
  ];
  if (!rows.length) return null;
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((r, i) => (
        <li key={i} className="flex items-center gap-2">
          <Badge variant={r.tag === "added" ? "default" : "outline"}>{r.tag}</Badge>
          <span>{r.text}</span>
        </li>
      ))}
    </ul>
  );
}
