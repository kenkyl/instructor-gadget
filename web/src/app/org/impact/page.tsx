"use client";

// The org admin's cache impact view (ADR-0030): the learner's trace tile over every learner's
// calls on the org's courses. Counts and dollars only, no prompt or response text (ADR-0027):
// the first learner to open a lesson pays to generate it, and the ones after them reuse it.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BackLink, Page, PageMessage } from "@/components/app-shell";
import { ImpactTile, usd } from "@/components/impact-tile";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
import { pct } from "@/lib/labels";

type OrgMembership = Schemas["OrgMembershipOut"];
type OrgImpact = Schemas["OrgImpactResponse"];
type Impact = Schemas["CacheImpact"];

const rate = (i: Impact) => (i.hit_rate === null ? "–" : pct(i.hit_rate));

export default function OrgImpactPage() {
  const router = useRouter();
  const [data, setData] = useState<OrgImpact | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<OrgMembership[]>("/orgs")
      .then(async (orgs) => {
        const org = orgs.find((o) => o.role === "admin");
        if (!org) return setError("Only org admins can see the org's cache impact.");
        setData(await apiGet<OrgImpact>(`/orgs/${org.slug}/impact`));
      })
      .catch((e: Error) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError(e.message);
      });
  }, [router]);

  if (!data) return <PageMessage error={error}>Loading the org’s cache impact…</PageMessage>;

  return (
    <Page className="space-y-8">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <h1>{data.org_name} cache impact</h1>
        <p className="text-muted-foreground max-w-[64ch]">
          What the cache saved across this org&apos;s courses. Lessons are shared only between
          courses grounded in exactly the same docs, so a learner after the first reuses what was
          already generated. Counts and dollars only: you never see what a learner answered.
        </p>
      </header>

      <ImpactTile impact={data.impact} scope="All org courses" />

      <section className="space-y-3" aria-labelledby="by-learner">
        <h2 id="by-learner">By learner</h2>
        <p className="text-muted-foreground text-sm">
          In the order each person first used an org course. Spend falls for the people after the
          first, because their lessons are already generated.
        </p>
        {data.learners.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed p-6">
            No model calls on org courses yet.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {data.learners.map((l) => (
              <li
                key={l.user_id}
                className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3 text-sm"
              >
                <span className="text-strong">{l.display_name}</span>
                <span className="text-muted-foreground flex flex-wrap gap-x-5">
                  <span>
                    <span className="num text-foreground">{l.impact.calls}</span>{" "}
                    {l.impact.calls === 1 ? "call" : "calls"}
                  </span>
                  <span>
                    hit rate <span className="num text-foreground">{rate(l.impact)}</span>
                  </span>
                  <span>
                    spent <span className="num text-foreground">{usd(l.impact.spent_usd)}</span>
                  </span>
                  <span>
                    saved <span className="num text-cyan-ink">{usd(l.impact.saved_usd)}</span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3" aria-labelledby="by-course">
        <h2 id="by-course">By course</h2>
        {data.courses.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed p-6">
            No org course has made a model call yet.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {data.courses.map((c) => (
              <li
                key={c.course_id}
                className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3 text-sm"
              >
                <span className="text-strong">{c.title}</span>
                <span className="text-muted-foreground flex flex-wrap gap-x-5">
                  <span>
                    <span className="num text-foreground">{c.learners}</span>{" "}
                    {c.learners === 1 ? "learner" : "learners"}
                  </span>
                  <span>
                    <span className="num text-foreground">{c.impact.calls}</span>{" "}
                    {c.impact.calls === 1 ? "call" : "calls"}
                  </span>
                  <span>
                    hit rate <span className="num text-foreground">{rate(c.impact)}</span>
                  </span>
                  <span>
                    spent <span className="num text-foreground">{usd(c.impact.spent_usd)}</span>
                  </span>
                  <span>
                    saved <span className="num text-cyan-ink">{usd(c.impact.saved_usd)}</span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Page>
  );
}
