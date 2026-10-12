// The learner's plan drawn like a commit graph: core concepts are nodes on one rail, in order;
// a remediation concept (inserted by the adapt rules, ADR-0022) forks off the rail and merges
// back into the concept it was inserted to support. Node shape and colour encode status.
import Link from "next/link";

import { MasteryMeter } from "@/components/mastery-meter";
import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api";
import { STATUS_LABEL, shortDate } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Progress = Schemas["ProgressView"];
type Concept = Schemas["Concept"];
type Status = Schemas["ConceptStatus"];

// Rail geometry (px): the main lane's centre, the branch lane's centre, the node row's centre.
const MAIN = 12;
const BRANCH = 34;
const NODE_Y = 13;

const STATUS_INK: Record<Status, string> = {
  complete: "text-green-ink",
  in_progress: "text-blue-ink",
  unlocked: "text-blue-ink",
  locked: "text-muted-foreground",
};

export function Node({ status, remediation }: { status: Status; remediation?: boolean }) {
  if (remediation) {
    return (
      <span
        className={cn(
          "block size-[11px] rotate-45 border-2 border-orange",
          status === "complete" || status === "in_progress" ? "bg-orange" : "bg-background",
        )}
      />
    );
  }
  return (
    <span
      className={cn(
        "block size-[14px] rounded-full border-2",
        status === "complete" && "border-green bg-green",
        status === "in_progress" && "border-blue bg-blue ring-4 ring-blue/25",
        status === "unlocked" && "border-blue bg-background",
        status === "locked" && "border-rail bg-background",
      )}
    />
  );
}

function Rail({ first, last, remediation, status }: { first: boolean; last: boolean; remediation: boolean; status: Status }) {
  return (
    <div className="relative" aria-hidden="true">
      {/* The main lane runs through every row; it starts at the first node and ends at the last. */}
      <span
        className="bg-rail absolute w-0.5"
        style={{ left: MAIN - 1, top: first ? NODE_Y : 0, ...(last ? { height: NODE_Y } : { bottom: 0 }) }}
      />
      {remediation ? (
        <>
          {/* Fork out of the main lane above the node, and merge back below it. */}
          <span
            className="border-orange absolute rounded-tr-[16px] border-t-2 border-r-2"
            style={{ left: MAIN, width: BRANCH - MAIN + 1, top: -10, height: NODE_Y + 10 - 5 }}
          />
          <span
            className="border-orange absolute rounded-br-[16px] border-r-2 border-b-2"
            style={{ left: MAIN, width: BRANCH - MAIN + 1, top: NODE_Y + 5, bottom: -2 }}
          />
          <span className="absolute" style={{ left: BRANCH - 5.5, top: NODE_Y - 5.5 }}>
            <Node status={status} remediation />
          </span>
        </>
      ) : (
        <span className="absolute" style={{ left: MAIN - 7, top: NODE_Y - 7 }}>
          <Node status={status} />
        </span>
      )}
    </div>
  );
}

export function PlanGraph({
  enrollmentId,
  progress,
  concepts,
}: {
  enrollmentId: string;
  progress: Progress[];
  concepts: Record<string, Concept>;
}) {
  return (
    <ol className="space-y-0">
      {progress.map((p, i) => {
        const c = concepts[p.concept_id];
        const locked = p.status === "locked";
        const remediation = p.kind === "remediation";
        const href =
          p.test_out && !p.has_lesson
            ? `/learn/${enrollmentId}/${p.concept_id}/quiz`
            : `/learn/${enrollmentId}/${p.concept_id}`;
        return (
          <li
            key={p.concept_id}
            className="grid grid-cols-[3rem_1fr]"
            aria-current={p.status === "in_progress" ? "step" : undefined}
          >
            <Rail first={i === 0} last={i === progress.length - 1} remediation={remediation} status={p.status} />
            <div className={cn("min-w-0 pb-7", remediation && "pl-3")}>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <Link
                  href={href}
                  className={cn(
                    "text-[1.0625rem] leading-[26px] font-semibold underline-offset-4 hover:underline",
                    locked ? "text-muted-foreground" : "text-strong",
                  )}
                >
                  {c.title}
                </Link>
                <span className={cn("text-sm font-medium", STATUS_INK[p.status])}>
                  {STATUS_LABEL[p.status]}
                </span>
                {remediation && <Badge variant="orange">Remediation</Badge>}
                {p.overridden && <Badge variant="yellow">Opened early</Badge>}
                {p.test_out && <Badge variant="violet">Testing out</Badge>}
              </div>
              <p className="text-muted-foreground mt-1 max-w-[68ch] text-sm">{c.mastery_statement}</p>
              {p.band && (
                <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
                  <MasteryMeter band={p.band} mastery={p.mastery ?? 0} />
                  {p.last_score != null && (
                    <span className="text-muted-foreground">
                      Last score <span className="num text-foreground">{p.last_score}/4</span> after{" "}
                      {p.attempts} attempt{p.attempts === 1 ? "" : "s"}
                    </span>
                  )}
                  {p.due && <span className="text-muted-foreground">Review {shortDate(p.due)}</span>}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function PlanLegend() {
  const items: [Status, string, boolean?][] = [
    ["complete", "Complete"],
    ["in_progress", "In progress"],
    ["unlocked", "Ready"],
    ["locked", "Locked"],
    ["in_progress", "Remediation", true],
  ];
  return (
    <ul className="text-muted-foreground flex flex-wrap gap-x-5 gap-y-2 text-xs" aria-label="Legend">
      {items.map(([s, label, rem]) => (
        <li key={label} className="flex items-center gap-2">
          <span className="grid size-4 place-items-center">
            <Node status={s} remediation={rem} />
          </span>
          {label}
        </li>
      ))}
    </ul>
  );
}
