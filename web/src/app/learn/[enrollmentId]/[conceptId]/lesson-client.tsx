"use client";

// One lesson (spec §4.5): explanation → worked example → diagram → prototype (hands-on only).
// A stored lesson loads with a GET; otherwise the POST streams it (SSE), field by field, as the
// model writes it. A locked concept (409) shows the override gate instead (spec §4.8).
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BackLink, Page } from "@/components/app-shell";
import { DocCitation } from "@/components/doc-citation";
import { Markdown } from "@/components/markdown";
import { MermaidDiagram } from "@/components/mermaid-diagram";
import { OverrideGate } from "@/components/override-gate";
import { PrototypeFrame } from "@/components/prototype-frame";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";
import { citeId } from "@/lib/citations";
import { CACHE_LABEL } from "@/lib/labels";
import { postSse } from "@/lib/sse";

type LessonView = Schemas["LessonView"];
type EnrollmentDetail = Schemas["EnrollmentDetail"];
// SSE payloads aren't in the OpenAPI schema (the route yields ServerSentEvent); this mirrors
// FieldDeltaEvent in backend/app/services/learning.py.
type Delta = { field: string; text: string; replace: boolean };
type Fields = Partial<Record<"explanation_md" | "example_md" | "diagram_mermaid", string>>;

export default function LessonPage() {
  const { enrollmentId, conceptId } = useParams<{ enrollmentId: string; conceptId: string }>();
  const router = useRouter();
  const [fields, setFields] = useState<Fields>({});
  const [lesson, setLesson] = useState<LessonView | null>(null);
  const [plan, setPlan] = useState<EnrollmentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // The concept's title and place in the plan (no model call).
    apiGet<EnrollmentDetail>(`/enrollments/${enrollmentId}`).then(setPlan, () => {});
  }, [enrollmentId]);

  useEffect(() => {
    // Aborting on cleanup also covers React's dev double-mount: the server sees the client go
    // away and stops that generation, so only one lesson is generated.
    const abort = new AbortController();
    const base = `/enrollments/${enrollmentId}/concepts/${conceptId}/lesson`;
    (async () => {
      try {
        setLesson(await apiGet<LessonView>(base)); // already generated: no model call
        return;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return router.replace("/login");
        if (!(e instanceof ApiError && e.status === 404)) throw e;
      }
      await postSse(
        base,
        ({ event, data }) => {
          if (event === "field_delta") {
            const d = data as Delta;
            const key = d.field as keyof Fields;
            setFields((f) => ({ ...f, [key]: d.replace ? d.text : (f[key] ?? "") + d.text }));
          } else if (event === "restart") {
            setFields({}); // the first draft failed validation; a retry is streaming
          } else if (event === "done") {
            setLesson((data as { lesson: LessonView }).lesson);
            // Design the quiz (~20 s) while the learner reads. The endpoint is get-or-create, so
            // "Take the quiz" then opens this same attempt instantly. Only after a fresh lesson,
            // so revisiting a finished concept doesn't start a new round.
            apiPost(`/enrollments/${enrollmentId}/concepts/${conceptId}/quiz`).catch(() => {});
          } else if (event === "error") {
            setError((data as { message: string }).message);
          }
        },
        abort.signal,
      );
    })().catch((e: Error) => {
      if (e instanceof ApiError && e.status === 409) setLocked(true);
      else if (e.name !== "AbortError") setError(e.message);
    });
    return () => abort.abort();
  }, [enrollmentId, conceptId, router, attempt]);

  const shown: Fields = lesson?.content ?? fields;
  // Org courses (ADR-0029): sources and gaps arrive with the finished lesson, not mid-stream.
  const citations = lesson?.content.citations ?? [];
  const notInDocs = lesson?.content.not_in_docs ?? [];
  const cited = citations.length > 0;
  const streaming = lesson === null && error === null && !locked;
  const concept = plan?.concept_map.concepts.find((c) => c.id === conceptId);
  const position = plan ? plan.progress.findIndex((p) => p.concept_id === conceptId) + 1 : 0;

  const header = (
    <header className="space-y-3">
      <BackLink href={`/learn/${enrollmentId}`}>Plan</BackLink>
      {concept && (
        <>
          <h1>{concept.title}</h1>
          <p className="text-muted-foreground max-w-[68ch]">{concept.mastery_statement}</p>
        </>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        {position > 0 && plan && (
          <span className="text-muted-foreground">
            Concept <span className="num text-foreground">{position}</span> of{" "}
            <span className="num text-foreground">{plan.progress.length}</span>
          </span>
        )}
        {lesson?.kind === "remediation" && <Badge variant="orange">Remediation</Badge>}
        {lesson && (
          <Badge variant="cyan" title="How this lesson was produced (the LLM cache tier that served it)">
            {CACHE_LABEL[lesson.cache_result]}
          </Badge>
        )}
        {streaming && (
          <span className="text-blue-ink inline-flex items-center gap-2">
            <span className="bg-blue size-1.5 animate-pulse rounded-full" />
            Writing your lesson…
          </span>
        )}
      </div>
    </header>
  );

  if (locked) {
    return (
      <Page className="space-y-8">
        {header}
        <OverrideGate
          enrollmentId={enrollmentId}
          conceptId={conceptId}
          onOpened={() => {
            setLocked(false);
            setAttempt((n) => n + 1);
          }}
        />
      </Page>
    );
  }

  return (
    <Page className="space-y-12">
      {header}

      {error && (
        <div className="border-red bg-red/10 flex flex-wrap items-center gap-3 rounded-md border-l-2 px-4 py-3">
          <span className="text-red-ink text-sm">{error}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setError(null);
              setFields({});
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </Button>
        </div>
      )}

      {shown.explanation_md && <Markdown cited={cited}>{shown.explanation_md}</Markdown>}
      {notInDocs.length > 0 && (
        <section className="border-yellow bg-yellow/10 max-w-[68ch] space-y-2 rounded-md border-l-2 px-4 py-3">
          <p className="text-yellow-ink font-semibold">This isn&apos;t covered in your docs</p>
          <ul className="space-y-2">
            {notInDocs.map((n) => (
              <li key={n.point}>
                <span className="text-strong">{n.point}</span>
                {n.general_knowledge && (
                  <span className="text-muted-foreground block text-sm">
                    General knowledge, not from your docs: {n.general_knowledge}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {shown.example_md && (
        <LessonSection title="Worked example">
          <Markdown cited={cited}>{shown.example_md}</Markdown>
        </LessonSection>
      )}
      {shown.diagram_mermaid && (
        <LessonSection title="Diagram">
          {lesson ? (
            <MermaidDiagram source={lesson.content.diagram_mermaid} />
          ) : (
            <pre className="bg-muted num overflow-x-auto rounded-md p-3 text-xs">{shown.diagram_mermaid}</pre>
          )}
        </LessonSection>
      )}
      {lesson?.prototype && (
        <LessonSection title={`Try it: ${lesson.prototype.title}`}>
          <p className="text-muted-foreground">
            Change the knobs until something surprises you, then work out why.
          </p>
          <PrototypeFrame title={lesson.prototype.title} html={lesson.prototype.html} />
        </LessonSection>
      )}
      {cited && (
        <LessonSection title="Sources">
          <ol className="max-w-[68ch] space-y-3">
            {citations.map((c, i) => (
              <li key={i} id={citeId(i + 1)} className="flex scroll-mt-24 gap-3">
                <span className="num text-muted-foreground">[{i + 1}]</span>
                <DocCitation citation={c} />
              </li>
            ))}
          </ol>
        </LessonSection>
      )}
      {lesson && (
        <section className="bg-muted/60 space-y-4 rounded-lg p-6">
          <h2>Check your understanding</h2>
          <p className="max-w-[60ch]">
            Four questions set in situations the lesson didn&apos;t use, plus one to explain in your
            own words. No hints, and only your first answers count.
          </p>
          <Link href={`/learn/${enrollmentId}/${conceptId}/quiz`} className={buttonVariants()}>
            Take the quiz
          </Link>
        </section>
      )}
    </Page>
  );
}

function LessonSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-4 border-t pt-8">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
