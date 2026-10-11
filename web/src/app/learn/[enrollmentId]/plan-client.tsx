"use client";

// The learner's plan (J2): concepts in sequence with status, band, mastery and review date, and
// the plan's history: every version with its trigger, why and diff (spec §4.8). A locked concept
// opens to the override gate; remediation concepts are the ones the adapt rules inserted.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PlanDiffView } from "@/components/plan-diff";
import { Badge } from "@/components/ui/badge";
import { ApiError, apiGet, type Schemas } from "@/lib/api";

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

  if (!plan) return <p className="p-10 text-muted-foreground">{error ?? "Loading…"}</p>;
  const concepts = Object.fromEntries(plan.concept_map.concepts.map((c) => [c.id, c]));
  const titles = Object.fromEntries(plan.concept_map.concepts.map((c) => [c.id, c.title]));

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-8">
      <header className="space-y-1">
        <Link href="/" className="text-muted-foreground text-sm hover:underline">
          ← Dashboard
        </Link>
        <h1 className="text-2xl font-semibold">{plan.title}</h1>
        <p className="text-muted-foreground text-sm">
          Plan v{plan.plan_version} · {plan.progress.filter((p) => p.status === "complete").length}/
          {plan.progress.length} complete · {dueCount} due for review
        </p>
        {plan.status === "complete" && (
          <p className="font-semibold">
            🎓 Course complete
            {plan.completed_at && ` on ${new Date(plan.completed_at).toLocaleDateString()}`}
          </p>
        )}
      </header>

      <ol className="space-y-3">
        {plan.progress.map((p, i) => {
          const c = concepts[p.concept_id];
          const locked = p.status === "locked";
          const href =
            p.test_out && !p.has_lesson
              ? `/learn/${enrollmentId}/${p.concept_id}/quiz`
              : `/learn/${enrollmentId}/${p.concept_id}`;
          return (
            <li
              key={p.concept_id}
              className={`rounded border p-3 space-y-1 ${p.kind === "remediation" ? "ml-6 border-dashed" : ""}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground text-sm">{i + 1}.</span>
                <Link
                  href={href}
                  className={`font-medium hover:underline ${locked ? "text-muted-foreground" : ""}`}
                >
                  {c.title}
                </Link>
                <Badge variant="outline">{locked ? "🔒 locked" : p.status.replace("_", " ")}</Badge>
                {p.band && (
                  <Badge variant="secondary">
                    {p.band} · {Math.round((p.mastery ?? 0) * 100)}%
                  </Badge>
                )}
                {p.kind === "remediation" && <Badge>remediation</Badge>}
                {p.test_out && <Badge variant="outline">testing out</Badge>}
                {p.overridden && <Badge variant="destructive">opened early</Badge>}
              </div>
              <p className="text-muted-foreground text-sm">{c.mastery_statement}</p>
              {p.last_score != null && (
                <p className="text-muted-foreground text-xs">
                  Last score {p.last_score}/4 after {p.attempts} attempt{p.attempts === 1 ? "" : "s"}
                  {p.due && ` · review ${new Date(p.due).toLocaleDateString()}`}
                </p>
              )}
            </li>
          );
        })}
      </ol>

      {history.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Plan history</h2>
          {history.map((v) => (
            <div key={v.version} className="space-y-2 rounded border p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge>v{v.version}</Badge>
                <Badge variant="outline">{v.trigger.replaceAll("_", " ")}</Badge>
                {v.rule && <Badge variant="secondary">{v.rule.replaceAll("_", " ")}</Badge>}
                <span className="text-muted-foreground">{new Date(v.created_at).toLocaleString()}</span>
              </div>
              <p className="text-sm">{v.reason}</p>
              {v.diff && <PlanDiffView diff={v.diff} titles={titles} />}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
