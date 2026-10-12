"use client";

import { GraduationCap, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Page, PageMessage } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

type DashboardData = Schemas["DashboardResponse"];
type OrgMembership = Schemas["OrgMembershipOut"];
type Course = DashboardData["courses"][number];
type OrgCourse = Schemas["OrgCourseSummary"];

export function Dashboard() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [orgs, setOrgs] = useState<OrgMembership[]>([]);
  const [managed, setManaged] = useState<OrgCourse[]>([]);

  useEffect(() => {
    // Only decides the org links and the admin's course list, so a failure just hides them.
    apiGet<OrgMembership[]>("/orgs").then(
      (ms) => {
        setOrgs(ms);
        // An org template has no enrollment for its admin, so this list is the way back to it.
        const admin = ms.find((m) => m.role === "admin");
        if (admin) {
          apiGet<OrgCourse[]>(`/orgs/${admin.slug}/courses`).then(setManaged, () => setManaged([]));
        }
      },
      () => setOrgs([]),
    );
  }, []);

  useEffect(() => {
    apiGet<DashboardData>("/dashboard").then(setData, (e: Error) => {
      // Cookie present but session expired or revoked: the API is the real auth check.
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [router]);

  async function logout() {
    await apiPost("/auth/logout");
    router.replace("/login");
  }

  if (!data) return <PageMessage error={error}>Loading your courses…</PageMessage>;

  return (
    <Page
      className="space-y-8"
      bar={
        <>
          {/* Makes the cache-aside layer visible: "cache" = Redis JSON hit, "db" = rebuilt from Postgres */}
          <span
            className="text-cyan-ink hidden items-center gap-1.5 text-xs sm:inline-flex"
            title={`Generated ${new Date(data.generated_at).toLocaleTimeString()}`}
          >
            <span className="bg-cyan size-1.5 rounded-full" />
            {data.served_from === "cache" ? "Served from Redis cache" : "Rebuilt from Postgres"}
          </span>
          {orgs.length > 0 && (
            <Link href="/org/docs" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Org docs
            </Link>
          )}
          {orgs.some((o) => o.role === "admin") && (
            <Link href="/org/impact" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Org impact
            </Link>
          )}
          <Link href="/trace" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            Trace
          </Link>
          <span className="text-muted-foreground hidden text-sm sm:inline">{data.user.display_name}</span>
          <Button variant="ghost" size="sm" onClick={logout}>
            Log out
          </Button>
        </>
      }
    >
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1>Your courses</h1>
          <p className="text-muted-foreground">Signed in as {data.user.username}</p>
        </div>
        <Link href="/courses/new" className={buttonVariants()}>
          <Plus data-icon="inline-start" />
          New course
        </Link>
      </header>

      {data.courses.length === 0 ? (
        <div className="space-y-3 rounded-lg border border-dashed p-8">
          <p className="text-strong font-semibold">No courses yet</p>
          <p className="text-muted-foreground max-w-[60ch]">
            Name a topic and the instructor checks what you already know, then plans a course from
            there.
          </p>
          <Link href="/courses/new" className={buttonVariants({ variant: "outline" })}>
            Start your first course
          </Link>
        </div>
      ) : (
        <ul className="divide-y border-y">
          {data.courses.map((c) => (
            <CourseRow key={c.enrollment_id} course={c} />
          ))}
        </ul>
      )}

      {managed.length > 0 && (
        <section className="space-y-3" aria-labelledby="managed">
          <h2 id="managed">Org courses you manage</h2>
          <ul className="divide-y border-y">
            {managed.map((c) => (
              <li key={c.course_id}>
                <Link
                  href={`/courses/${c.course_id}`}
                  className="group hover:bg-muted/60 -mx-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 rounded-md px-3 py-3 text-sm transition-colors"
                >
                  <span className="text-strong group-hover:underline group-hover:underline-offset-4">
                    {c.title}
                  </span>
                  <span className="text-muted-foreground flex flex-wrap items-center gap-x-5">
                    {c.status === "active" ? (
                      <Badge variant="green">Accepted</Badge>
                    ) : (
                      <Badge variant="yellow">Draft</Badge>
                    )}
                    <span>
                      <span className="num text-foreground">{c.doc_count}</span>{" "}
                      {c.doc_count === 1 ? "doc" : "docs"}
                    </span>
                    <span>
                      <span className="num text-foreground">{c.assigned_count}</span> assigned
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

function CourseRow({ course: c }: { course: Course }) {
  const complete = c.status === "complete";
  return (
    <li>
      <Link
        href={`/learn/${c.enrollment_id}`}
        className="group hover:bg-muted/60 -mx-3 block space-y-3 rounded-md px-3 py-5 transition-colors"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-strong text-lg font-semibold group-hover:underline group-hover:underline-offset-4">
            {c.title}
          </span>
          {complete && (
            <Badge variant="green">
              <GraduationCap />
              Complete
            </Badge>
          )}
          {c.due_count > 0 && <Badge variant="yellow">{c.due_count} due for review</Badge>}
        </div>
        <ConceptStrip concepts={c.concepts} />
        <p className="text-muted-foreground flex flex-wrap gap-x-5 text-sm">
          <span>
            <span className="num text-foreground">
              {c.concepts_complete}/{c.concepts_total}
            </span>{" "}
            concepts complete
          </span>
          <BandSummary bands={c.bands} />
          <span>{c.scope === "org" ? `${c.org_name} course` : "Personal course"}</span>
        </p>
      </Link>
    </li>
  );
}

type Concept = Course["concepts"][number];
type Bands = Course["bands"];

const CELL: Record<NonNullable<Concept["band"]>, string> = {
  shaky: "bg-red",
  learning: "bg-yellow",
  solid: "bg-green/60",
  mastered: "bg-green",
};

// One cell per concept in plan order, coloured by mastery band; a ring marks one due for review.
// The band counts beside it say the same in words (colour is never the only cue).
function ConceptStrip({ concepts }: { concepts: Concept[] }) {
  return (
    <div className="flex max-w-md gap-1" aria-hidden="true">
      {concepts.map((c) => (
        <span
          key={c.concept_id}
          title={`${c.title}: ${c.band ?? "not started"}${c.due ? ", due for review" : ""}`}
          className={cn(
            "h-1.5 flex-1 rounded-full",
            c.band ? CELL[c.band] : "bg-muted",
            c.due && "ring-yellow ring-2 ring-offset-1",
          )}
        />
      ))}
    </div>
  );
}

const BAND_ORDER = ["mastered", "solid", "learning", "shaky", "not_started"] as const;

function BandSummary({ bands }: { bands: Bands }) {
  const parts = BAND_ORDER.filter((b) => bands[b] > 0);
  if (parts.length === 0) return null;
  return (
    <span>
      {parts.map((b, i) => (
        <span key={b}>
          {i > 0 && " · "}
          <span className="num text-foreground">{bands[b]}</span> {b.replace("_", " ")}
        </span>
      ))}
    </span>
  );
}
