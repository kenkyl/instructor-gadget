"use client";

// J1 after intake, on one page (spec §4.2–4.4):
//   draft    → write the diagnostic questions
//   probed   → answer them all on one screen
//   assessed → the demonstrated level, why, and the gaps. If it differs from the claim the
//              instructor says so plainly (no silent re-levelling). Answers are then locked.
//   mapped   → the concept map: a dependency-ordered list with the reasoning for the order.
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";

type CourseDetail = Schemas["CourseDetail"];
type Assessment = Schemas["AssessOutput"];
type ConceptMap = Schemas["ConceptMap"];

export default function CoursePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<CourseDetail>(`/courses/${id}`).then(setCourse, (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [id, router]);

  async function post(path: string, label: string, body?: unknown) {
    setBusy(label);
    setError(null);
    try {
      setCourse(await apiPost<CourseDetail>(`/courses/${id}/${path}`, body));
    } catch (e) {
      setError((e as Error).message); // typed answers stay in state, so a retry loses nothing
    } finally {
      setBusy(null);
    }
  }

  function submitAnswers(e: FormEvent) {
    e.preventDefault();
    const all = Object.fromEntries(questions.map((q) => [q.id, answers[q.id] ?? ""]));
    void post("assess", "Assessing your answers…", { answers: all });
  }

  if (!course) {
    return <p className="p-10 text-muted-foreground">{error ?? "Loading…"}</p>;
  }

  const questions = course.questions ?? [];
  const assessment = course.assessment ?? null;
  const conceptMap = course.concept_map ?? null;
  const { config, mission } = course;

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-6">
      <header className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{course.title}</h1>
          <Badge variant="outline">{course.status}</Badge>
        </div>
        <p className="text-muted-foreground text-sm">
          {config.target_hours} h · {mission.mode} · target {config.target_level} · you said{" "}
          {config.self_level}
        </p>
      </header>

      {questions.length === 0 ? (
        <Card>
          <CardContent className="space-y-3">
            <p className="text-sm">
              Next, the instructor writes 3–4 questions to check where you really are.
            </p>
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button
              onClick={() => post("probe", "Writing your diagnostic questions…")}
              disabled={busy !== null}
            >
              {busy ?? "Write my diagnostic questions"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {assessment && <AssessmentCard assessment={assessment} />}
          {conceptMap && (
            <ConceptMapCard map={conceptMap} targetMinutes={Math.round(config.target_hours * 60)} />
          )}
          {assessment && !conceptMap && (
            <div className="flex items-center gap-3">
              <Button
                onClick={() => post("map", "Planning your course…")}
                disabled={busy !== null}
              >
                {busy ?? "Build my concept map"}
              </Button>
              {error && <span className="text-destructive text-sm">{error}</span>}
            </div>
          )}

          <form onSubmit={submitAnswers} className="space-y-4">
            {!assessment && (
              <div>
                <h2 className="text-lg font-medium">Where are you really?</h2>
                <p className="text-muted-foreground text-sm">
                  You said {config.self_level}. Answer in a few sentences each; your answers, not
                  the label, decide where the course starts. A blank answer counts as “I don’t
                  know”, which is fine.
                </p>
              </div>
            )}
            {questions.map((q, i) => {
              const evidence = assessment?.evidence.find((e) => e.question_id === q.id);
              return (
                <Card key={q.id}>
                  <CardHeader>
                    <CardTitle className="text-base font-normal">
                      <span className="text-muted-foreground mr-2">{i + 1}.</span>
                      {q.prompt}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Label htmlFor={q.id} className="sr-only">
                      Your answer to question {i + 1}
                    </Label>
                    {assessment ? (
                      <p className="text-sm whitespace-pre-wrap border-l-2 pl-3">
                        {course.answers?.[q.id] || (
                          <span className="text-muted-foreground">(no answer)</span>
                        )}
                      </p>
                    ) : (
                      <Textarea
                        id={q.id}
                        rows={4}
                        value={answers[q.id] ?? ""}
                        onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                        disabled={busy !== null}
                      />
                    )}
                    {evidence && (
                      <p className="text-sm">
                        <Badge variant="secondary" className="mr-2">
                          points to {evidence.points_to}
                        </Badge>
                        {evidence.observation}
                      </p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
            {!assessment && (
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={busy !== null}>
                  {busy ?? "Submit answers"}
                </Button>
                {error && <span className="text-destructive text-sm">{error}</span>}
              </div>
            )}
          </form>
        </>
      )}
    </main>
  );
}

function AssessmentCard({ assessment: a }: { assessment: Assessment }) {
  const adjusted = a.assessed_level !== a.claimed_level;
  return (
    <Card className={adjusted ? "border-amber-500" : undefined}>
      <CardHeader>
        <CardTitle>
          We’ll start at <span className="capitalize">{a.assessed_level}</span>
        </CardTitle>
        <CardDescription>
          You said {a.claimed_level} · confidence {Math.round(a.confidence * 100)}%
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* The instructor's own words: what changed, which answer drove it, and why. */}
        {adjusted && a.adjustment_message && <p>{a.adjustment_message}</p>}
        {!adjusted && <p>Your answers match the level you gave.</p>}
        {a.gaps.length > 0 && (
          <div>
            <p className="font-medium">Gaps the course will cover first</p>
            <ul className="list-disc pl-5">
              {a.gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ConceptMapCard({ map, targetMinutes }: { map: ConceptMap; targetMinutes: number }) {
  const byId = new Map(map.concepts.map((c) => [c.id, c]));
  const total = map.concepts.reduce((sum, c) => sum + c.est_minutes, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your concept map</CardTitle>
        <CardDescription>
          {map.concepts.length} concepts · {total} min (target {targetMinutes})
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p>{map.sequence_rationale}</p>
        <ol className="space-y-3">
          {map.sequence.map((id, i) => {
            const c = byId.get(id);
            if (!c) return null;
            return (
              <li key={id} className="border-l-2 pl-3 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground">{i + 1}.</span>
                  <span className="font-medium">{c.title}</span>
                  <Badge variant="outline">{c.est_minutes} min</Badge>
                  <Badge variant="secondary">{c.concept_type}</Badge>
                  <Badge variant="secondary">{c.objective_level}</Badge>
                </div>
                <p>{c.mastery_statement}</p>
                {c.prereqs.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    Needs: {c.prereqs.map((p) => byId.get(p)?.title ?? p).join(", ")}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
        <p className="text-muted-foreground text-xs">
          Next: remove concepts you don’t want, then accept (coming in the next checkpoint).
        </p>
      </CardContent>
    </Card>
  );
}
