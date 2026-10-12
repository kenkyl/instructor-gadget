"use client";

// The learner's plan (J2): concepts in sequence with status, band, mastery and review date, and
// the plan's history: every version with its trigger, why and diff (spec §4.8). A locked concept
// opens to the override gate; remediation concepts are the ones the adapt rules inserted.
import { GraduationCap } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BackLink, Page, PageMessage } from "@/components/app-shell";
import { PlanDiffView } from "@/components/plan-diff";
import { PlanGraph, PlanLegend } from "@/components/plan-graph";
import { Badge } from "@/components/ui/badge";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
import { RULE_LABEL, TRIGGER_LABEL } from "@/lib/labels";

type EnrollmentDetail = Schemas["EnrollmentDetail"];
type PlanVersionView = Schemas["PlanVersionView"];

export default function PlanPage() {
  const { enrollmentId } = useParams<{ enrollmentId: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<EnrollmentDetail | null>(null);
  const [history, setHistory] = useState<PlanVersionView[]>([]);
  const [dueCount, setDueCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fail = (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    };
    apiGet<EnrollmentDetail>(`/enrollments/${enrollmentId}`).then((p) => {
      setPlan(p);
      const now = Date.now(); // read once per load, not during render
      setDueCount(p.progress.filter((c) => c.due && Date.parse(c.due) <= now).length);
    }, fail);
    apiGet<PlanVersionView[]>(`/enrollments/${enrollmentId}/plans`).then(setHistory, fail);
  }, [enrollmentId, router]);

  if (!plan) return <PageMessage error={error}>Loading your plan…</PageMessage>;
  const concepts = Object.fromEntries(plan.concept_map.concepts.map((c) => [c.id, c]));
  const titles = Object.fromEntries(plan.concept_map.concepts.map((c) => [c.id, c.title]));
  const done = plan.progress.filter((p) => p.status === "complete").length;

  return (
    <Page className="space-y-10">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <h1>{plan.title}</h1>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <Stat label="Plan">
            <span className="num text-violet-ink font-semibold">v{plan.plan_version}</span>
          </Stat>
          <Stat label="Complete">
            <span className="num">
              {done}/{plan.progress.length}
            </span>
          </Stat>
          <Stat label="Due for review">
            <span className="num">{dueCount}</span>
          </Stat>
          <Link
            href={`/trace?course=${plan.course_id}`}
            className="text-cyan-ink underline-offset-4 hover:underline"
            title="Every model call made for this course, and what the cache saved"
          >
            Instructor trace
          </Link>
        </dl>
        {plan.status === "complete" && (
          <p className="bg-green/12 text-green-ink flex items-center gap-2 rounded-md px-3 py-2 font-semibold">
            <GraduationCap className="size-5" />
            Course complete
            {plan.completed_at && ` on ${new Date(plan.completed_at).toLocaleDateString()}`}
          </p>
        )}
      </header>

      <section className="space-y-5" aria-labelledby="plan-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="plan-heading">Your path</h2>
          <PlanLegend />
        </div>
        <PlanGraph enrollmentId={enrollmentId} progress={plan.progress} concepts={concepts} />
      </section>

      {history.length > 0 && (
        <section className="space-y-5" aria-labelledby="history-heading">
          <div>
            <h2 id="history-heading">How the plan changed</h2>
            <p className="text-muted-foreground mt-1 text-sm">
              Every change has a reason and a diff. Newest first.
            </p>
          </div>
          <ol className="space-y-8">
            {history.map((v) => (
              <li key={v.version} className="grid grid-cols-[3rem_1fr] gap-x-0">
                <span className="num text-violet-ink pt-px text-sm font-semibold">v{v.version}</span>
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <h3>{TRIGGER_LABEL[v.trigger] ?? v.trigger.replaceAll("_", " ")}</h3>
                    {v.rule && <Badge variant="violet">{RULE_LABEL[v.rule] ?? v.rule.replaceAll("_", " ")}</Badge>}
                    <time dateTime={v.created_at} className="text-muted-foreground text-sm">
                      {new Date(v.created_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                  <p className="max-w-[68ch]">{v.reason}</p>
                  {v.diff && <PlanDiffView diff={v.diff} titles={titles} />}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </Page>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-strong">{children}</dd>
    </div>
  );
}
