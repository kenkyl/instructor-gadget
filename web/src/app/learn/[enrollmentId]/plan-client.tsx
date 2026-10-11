"use client";

// The learner's plan (J2): concepts in sequence with status and band. Locked concepts can't be
// opened until their prereqs are solid (spec §4.8); the override arrives in PC2.6.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ApiError, apiGet, type Schemas } from "@/lib/api";

type EnrollmentDetail = Schemas["EnrollmentDetail"];

export default function PlanPage() {
  const { enrollmentId } = useParams<{ enrollmentId: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<EnrollmentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<EnrollmentDetail>(`/enrollments/${enrollmentId}`).then(setPlan, (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [enrollmentId, router]);

  if (!plan) return <p className="p-10 text-muted-foreground">{error ?? "Loading…"}</p>;
  const concepts = Object.fromEntries(plan.concept_map.concepts.map((c) => [c.id, c]));

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{plan.title}</h1>
        <p className="text-muted-foreground text-sm">Plan v{plan.plan_version}</p>
      </header>
      <ol className="space-y-3">
        {plan.progress.map((p, i) => {
          const c = concepts[p.concept_id];
          const locked = p.status === "locked";
          return (
            <li key={p.concept_id} className="rounded border p-3 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-sm">{i + 1}.</span>
                {locked ? (
                  <span className="font-medium text-muted-foreground">{c.title}</span>
                ) : (
                  <Link
                    href={`/learn/${enrollmentId}/${p.concept_id}`}
                    className="font-medium hover:underline"
                  >
                    {c.title}
                  </Link>
                )}
                <Badge variant="outline">{p.status.replace("_", " ")}</Badge>
                {p.band && <Badge variant="secondary">{p.band}</Badge>}
              </div>
              <p className="text-muted-foreground text-sm">{c.mastery_statement}</p>
            </li>
          );
        })}
      </ol>
    </main>
  );
}
