"use client";

// One lesson (spec §4.5): explanation → worked example → diagram → prototype (hands-on only).
// A stored lesson loads with a GET; otherwise the POST streams it (SSE), field by field, as the
// model writes it. A locked concept (409) shows the override gate instead (spec §4.8).
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/markdown";
import { MermaidDiagram } from "@/components/mermaid-diagram";
import { OverrideGate } from "@/components/override-gate";
import { PrototypeFrame } from "@/components/prototype-frame";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";
import { postSse } from "@/lib/sse";

type LessonView = Schemas["LessonView"];
// SSE payloads aren't in the OpenAPI schema (the route yields ServerSentEvent); this mirrors
// FieldDeltaEvent in backend/app/services/learning.py.
type Delta = { field: string; text: string; replace: boolean };
type Fields = Partial<Record<"explanation_md" | "example_md" | "diagram_mermaid", string>>;

export default function LessonPage() {
  const { enrollmentId, conceptId } = useParams<{ enrollmentId: string; conceptId: string }>();
  const router = useRouter();
  const [fields, setFields] = useState<Fields>({});
  const [lesson, setLesson] = useState<LessonView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [attempt, setAttempt] = useState(0);

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
  const streaming = lesson === null && error === null && !locked;

  if (locked) {
    return (
      <main className="mx-auto max-w-2xl p-10 space-y-6">
        <Link href={`/learn/${enrollmentId}`} className="text-muted-foreground text-sm hover:underline">
          ← Plan
        </Link>
        <OverrideGate
          enrollmentId={enrollmentId}
          conceptId={conceptId}
          onOpened={() => {
            setLocked(false);
            setAttempt((n) => n + 1);
          }}
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-8">
      <header className="flex items-center gap-3">
        <Link href={`/learn/${enrollmentId}`} className="text-muted-foreground text-sm hover:underline">
          ← Plan
        </Link>
        {lesson && <Badge variant="outline">{lesson.cache_result.replace("_", " ")}</Badge>}
        {lesson?.kind === "remediation" && <Badge>remediation</Badge>}
        {streaming && <span className="text-muted-foreground text-sm">Writing your lesson…</span>}
      </header>

      {error && (
        <div className="flex items-center gap-3">
          <span className="text-destructive text-sm">{error}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setError(null);
              setFields({});
              setAttempt((n) => n + 1);
            }}
          >
            Retry
          </Button>
        </div>
      )}

      {shown.explanation_md && <Markdown>{shown.explanation_md}</Markdown>}
      {shown.example_md && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Worked example</h2>
          <Markdown>{shown.example_md}</Markdown>
        </section>
      )}
      {shown.diagram_mermaid && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Diagram</h2>
          {lesson ? (
            <MermaidDiagram source={lesson.content.diagram_mermaid} />
          ) : (
            <pre className="bg-muted overflow-x-auto rounded p-3 text-xs">{shown.diagram_mermaid}</pre>
          )}
        </section>
      )}
      {lesson?.prototype && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Try it: {lesson.prototype.title}</h2>
          <p className="text-muted-foreground text-sm">
            Change the knobs until something surprises you, then work out why.
          </p>
          <PrototypeFrame title={lesson.prototype.title} html={lesson.prototype.html} />
        </section>
      )}
      {lesson && (
        <section className="space-y-2 border-t pt-6">
          <p className="text-muted-foreground text-sm">
            Next: 4 questions in situations the lesson didn&apos;t use, plus one to explain in your own
            words. No hints; only your first answers count.
          </p>
          <Link href={`/learn/${enrollmentId}/${conceptId}/quiz`} className={buttonVariants()}>
            Take the quiz →
          </Link>
        </section>
      )}
    </main>
  );
}
