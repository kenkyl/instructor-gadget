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
type Course = DashboardData["courses"][number];

export function Dashboard() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        <ConceptStrip done={c.concepts_complete} total={c.concepts_total} />
        <p className="text-muted-foreground flex flex-wrap gap-x-5 text-sm">
          <span>
            <span className="num text-foreground">
              {c.concepts_complete}/{c.concepts_total}
            </span>{" "}
            concepts complete
          </span>
          <span>{c.scope === "org" ? `${c.org_name} course` : "Personal course"}</span>
        </p>
      </Link>
    </li>
  );
}

// One cell per concept, filled as they complete: the plan's rail, flattened.
function ConceptStrip({ done, total }: { done: number; total: number }) {
  return (
    <div className="flex max-w-md gap-1" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={cn("h-1.5 flex-1 rounded-full", i < done ? "bg-green" : "bg-muted")} />
      ))}
    </div>
  );
}
