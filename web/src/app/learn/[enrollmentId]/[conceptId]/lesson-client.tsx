"use client";

// One lesson (spec §4.5): explanation → worked example → diagram. A stored lesson loads with a
// GET; otherwise the POST streams it (SSE), field by field, as the model writes it.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/markdown";
import { MermaidDiagram } from "@/components/mermaid-diagram";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
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
          } else if (event === "error") {
            setError((data as { message: string }).message);
          }
        },
        abort.signal,
      );
    })().catch((e: Error) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    return () => abort.abort();
  }, [enrollmentId, conceptId, router, attempt]);

  const shown: Fields = lesson?.content ?? fields;
  const streaming = lesson === null && error === null;

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-8">
      <header className="flex items-center gap-3">
        <Link href={`/learn/${enrollmentId}`} className="text-muted-foreground text-sm hover:underline">
          ← Plan
        </Link>
        {lesson && <Badge variant="outline">{lesson.cache_result.replace("_", " ")}</Badge>}
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
      {lesson && (
        <p className="text-muted-foreground text-sm">
          The quiz for this concept arrives in the next build step: 4 questions, no hints.
        </p>
      )}
    </main>
  );
}
