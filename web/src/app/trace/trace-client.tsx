"use client";

// Instructor trace (PC3.4): every model call made for this learner, cache hits included, and the
// cache impact tile. Hits cost nothing and log the original generation's cost and time, so the
// savings shown are measured, not estimated. Cyan is the system-telemetry tone (ADR-0025).
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BackLink, Page, PageMessage } from "@/components/app-shell";
import { dur, ImpactTile, usd } from "@/components/impact-tile";
import { Badge } from "@/components/ui/badge";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

type Trace = Schemas["TraceResponse"];
type Call = Schemas["TraceCall"];

const RESULT: Record<
  Call["cache_result"],
  { label: string; variant: "cyan" | "outline" | "secondary" }
> = {
  exact_hit: { label: "Exact hit", variant: "cyan" },
  semantic_hit: { label: "Semantic hit", variant: "cyan" },
  miss: { label: "Miss", variant: "secondary" },
  bypass: { label: "Bypass", variant: "outline" },
};

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export default function TracePage() {
  const router = useRouter();
  const course = useSearchParams().get("course");
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Trace>(
      course ? `/trace?course_id=${encodeURIComponent(course)}` : "/trace",
    ).then(setTrace, (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [course, router]);

  if (!trace)
    return <PageMessage error={error}>Loading the trace…</PageMessage>;
  const filtered = trace.courses.find((c) => c.id === trace.course_id);

  return (
    <Page className="space-y-10">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <h1>Instructor trace</h1>
            <p className="text-muted-foreground max-w-[60ch]">
              Every model call made for you, including the ones the cache
              answered instead.
            </p>
          </div>
          {trace.courses.length > 0 && (
            <NativeSelect
              aria-label="Course"
              value={trace.course_id ?? ""}
              onChange={(e) =>
                router.replace(
                  e.target.value ? `/trace?course=${e.target.value}` : "/trace",
                )
              }
              className="max-w-full"
            >
              <NativeSelectOption value="">All courses</NativeSelectOption>
              {trace.courses.map((c) => (
                <NativeSelectOption key={c.id} value={c.id}>
                  {c.title} ({c.calls})
                </NativeSelectOption>
              ))}
            </NativeSelect>
          )}
        </div>
      </header>

      <ImpactTile
        impact={trace.impact}
        scope={filtered?.title ?? "All courses"}
      />

      <section className="space-y-4" aria-labelledby="calls-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="calls-heading">Calls</h2>
          <p className="text-muted-foreground text-sm">
            Newest first
            {trace.truncated && `, latest ${trace.calls.length} shown`}
          </p>
        </div>
        {trace.calls.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed p-6">
            No model calls yet. Start a course and they appear here.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {trace.calls.map((c) => (
              <CallRow key={c.id} call={c} showCourse={!trace.course_id} />
            ))}
          </ul>
        )}
      </section>
    </Page>
  );
}

function CallRow({ call: c, showCourse }: { call: Call; showCourse: boolean }) {
  const r = RESULT[c.cache_result];
  const hit =
    c.cache_result === "exact_hit" || c.cache_result === "semantic_hit";
  const failed = c.status === "error";
  return (
    <li>
      <details className="group py-3">
        <summary className="hover:bg-muted/60 -mx-3 cursor-pointer list-none space-y-1 rounded-md px-3 py-1 [&::-webkit-details-marker]:hidden">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-strong font-semibold">
              {c.skill}
              <span className="text-muted-foreground font-normal">
                {" "}
                / {c.call}
              </span>
            </span>
            <Badge variant={r.variant}>{r.label}</Badge>
            {failed && <Badge variant="red">Error</Badge>}
            <time
              dateTime={c.created_at}
              className="text-muted-foreground ml-auto text-xs"
            >
              {when(c.created_at)}
            </time>
          </div>
          {showCourse && c.course_title && (
            <p className="text-muted-foreground text-sm">{c.course_title}</p>
          )}
          <p className="num text-muted-foreground flex flex-wrap gap-x-4 text-xs">
            {hit ? (
              <>
                {c.similarity !== null && (
                  <span className="text-cyan-ink">
                    similarity {c.similarity.toFixed(3)}
                  </span>
                )}
                <span>{dur(c.latency_ms)}</span>
                <span className="text-cyan-ink">
                  saved {usd(c.saved_cost_usd)} ·{" "}
                  {dur(Math.max(c.saved_latency_ms - c.latency_ms, 0))}
                </span>
              </>
            ) : (
              <>
                <span>
                  {c.input_tokens.toLocaleString()} →{" "}
                  {c.output_tokens.toLocaleString()} tokens
                </span>
                <span>{dur(c.latency_ms)}</span>
                <span>{usd(c.est_cost_usd)}</span>
              </>
            )}
          </p>
        </summary>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <Detail label="Model">{c.model}</Detail>
          <Detail label="Prompt">{c.prompt_version}</Detail>
          {c.error && (
            <Detail label="Error" className="text-red-ink">
              {c.error}
            </Detail>
          )}
          {c.prompt_excerpt && <Detail label="Sent">{c.prompt_excerpt}</Detail>}
          {c.response_excerpt && (
            <Detail label="Received">{c.response_excerpt}</Detail>
          )}
        </dl>
      </details>
    </li>
  );
}

function Detail({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "num min-w-0 text-xs break-words whitespace-pre-wrap",
          className,
        )}
      >
        {children}
      </dd>
    </>
  );
}
