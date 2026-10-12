"use client";

// J1 after intake, on one page (spec §4.2–4.4):
//   draft    → write the diagnostic questions
//   probed   → answer them all on one screen
//   assessed → the demonstrated level, why, and the gaps. If it differs from the claim the
//              instructor says so plainly (no silent re-levelling). Answers are then locked.
//   mapped   → the concept map: a dependency-ordered list with the reasoning for the order.
//              The learner can cut concepts (warned about dependents), then accept.
//   active   → accepted: an enrollment exists and the course is on the dashboard.
// An org course (an admin's template, grounded in docs) skips all of that: it has no probe
// (ADR-0004), so its draft shows the docs it is pinned to instead.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { BackLink, Page, PageMessage } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiDelete, apiGet, apiPost, type Schemas } from "@/lib/api";

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

  async function post(path: string, label: string, body?: unknown, method: "POST" | "DELETE" = "POST") {
    setBusy(label);
    setError(null);
    try {
      const url = `/courses/${id}/${path}`;
      setCourse(await (method === "POST" ? apiPost<CourseDetail>(url, body) : apiDelete<CourseDetail>(url)));
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

  if (!course) return <PageMessage error={error}>Loading your course…</PageMessage>;

  const questions = course.questions ?? [];
  const assessment = course.assessment ?? null;
  const conceptMap = course.concept_map ?? null;
  const { config, mission } = course;
  const isOrg = course.scope === "org";

  return (
    <Page className="space-y-8">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <h1>{course.title}</h1>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {(
            [
              ["Time", `${config.target_hours} h`],
              ["Mode", mission.mode],
              ["Target", config.target_level],
              [isOrg ? "Learners start" : "You said", config.self_level],
              ["Stage", course.status],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-2">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="text-strong first-letter:uppercase">{v}</dd>
            </div>
          ))}
        </dl>
      </header>

      {isOrg ? (
        <OrgTemplateCard course={course} />
      ) : questions.length === 0 ? (
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
            <ConceptMapCard
              map={conceptMap}
              targetMinutes={Math.round(config.target_hours * 60)}
              editable={course.status === "mapped"}
              enrollmentId={course.enrollment_id ?? null}
              busy={busy}
              error={error}
              onRemove={(cid) =>
                post(`map/concepts/${encodeURIComponent(cid)}`, "Removing…", undefined, "DELETE")
              }
              onAccept={() => post("accept", "Accepting…")}
            />
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
              <div className="space-y-1">
                <h2>Where are you really?</h2>
                <p className="text-muted-foreground max-w-[68ch]">
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
                    <CardTitle className="flex gap-3 font-medium">
                      <span className="num text-muted-foreground">{i + 1}</span>
                      {q.prompt}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Label htmlFor={q.id} className="sr-only">
                      Your answer to question {i + 1}
                    </Label>
                    {assessment ? (
                      <p className="border-rail border-l-2 pl-3 whitespace-pre-wrap">
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
                        <Badge variant="blue" className="mr-2">
                          Points to {evidence.points_to}
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
    </Page>
  );
}

function AssessmentCard({ assessment: a }: { assessment: Assessment }) {
  const adjusted = a.assessed_level !== a.claimed_level;
  return (
    <Card className={adjusted ? "border-l-yellow border-l-2" : "border-l-green border-l-2"}>
      <CardHeader>
        <CardTitle>
          We’ll start at <span className="capitalize">{a.assessed_level}</span>
        </CardTitle>
        <CardDescription className="flex flex-wrap gap-x-5">
          <span>You said {a.claimed_level}</span>
          <span>
            Confidence <span className="num text-foreground">{Math.round(a.confidence * 100)}%</span>
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="max-w-[68ch] space-y-3">
        {/* The instructor's own words: what changed, which answer drove it, and why. */}
        {adjusted && a.adjustment_message && <p>{a.adjustment_message}</p>}
        {!adjusted && <p>Your answers match the level you gave.</p>}
        {a.gaps.length > 0 && (
          <div>
            <p className="text-strong font-semibold">Gaps the course will cover first</p>
            <ul className="mt-1 list-disc space-y-1 pl-5">
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

function ConceptMapCard({
  map,
  targetMinutes,
  editable,
  enrollmentId,
  busy,
  error,
  onRemove,
  onAccept,
}: {
  map: ConceptMap;
  targetMinutes: number;
  editable: boolean;
  enrollmentId: string | null;
  busy: string | null;
  error: string | null;
  onRemove: (conceptId: string) => void;
  onAccept: () => void;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const byId = new Map(map.concepts.map((c) => [c.id, c]));
  const total = map.concepts.reduce((sum, c) => sum + c.est_minutes, 0);
  // Display only: the server does the rewiring (plan.remove_concept, ADR-0017).
  const dependentsOf = (cid: string) => map.concepts.filter((c) => c.prereqs.includes(cid));

  function remove(cid: string) {
    if (dependentsOf(cid).length > 0 && confirming !== cid) return setConfirming(cid);
    setConfirming(null);
    onRemove(cid);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your concept map</CardTitle>
        <CardDescription className="flex flex-wrap gap-x-5">
          <span>
            <span className="num text-foreground">{map.concepts.length}</span> concepts
          </span>
          <span>
            <span className="num text-foreground">{total}</span> min of a{" "}
            <span className="num text-foreground">{targetMinutes}</span> min target
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <p className="max-w-[68ch]">{map.sequence_rationale}</p>
        <ol className="space-y-3">
          {map.sequence.map((cid, i) => {
            const c = byId.get(cid);
            if (!c) return null;
            const deps = dependentsOf(cid);
            return (
              <li key={cid} className="border-rail space-y-1 border-l-2 pl-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="num text-muted-foreground">{i + 1}</span>
                  <span className="text-strong font-semibold">{c.title}</span>
                  <Badge variant="outline" className="num">
                    {c.est_minutes} min
                  </Badge>
                  <Badge variant="secondary">{c.concept_type}</Badge>
                  <Badge variant="secondary">{c.objective_level}</Badge>
                  {editable && map.concepts.length > 1 && confirming !== cid && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={() => remove(cid)}
                      disabled={busy !== null}
                    >
                      Remove
                    </Button>
                  )}
                </div>
                <p className="text-muted-foreground max-w-[68ch] text-sm">{c.mastery_statement}</p>
                {c.prereqs.length > 0 && (
                  <p className="text-muted-foreground text-xs">
                    Needs: {c.prereqs.map((p) => byId.get(p)?.title ?? p).join(", ")}
                  </p>
                )}
                {confirming === cid && (
                  <div className="border-yellow bg-yellow/10 space-y-3 rounded-r-md border-l-2 p-3 text-sm">
                    <p>
                      {deps.map((d) => d.title).join(", ")} {deps.length === 1 ? "builds" : "build"}{" "}
                      on {c.title}. If you remove it, the course won’t teach it, and{" "}
                      {deps.length === 1 ? "that concept" : "those concepts"} will start without it.
                    </p>
                    <div className="flex gap-2">
                      <Button size="sm" variant="destructive" onClick={() => remove(cid)}>
                        Remove anyway
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setConfirming(null)}>
                        Keep it
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        {editable ? (
          <div className="flex items-center gap-3">
            <Button onClick={onAccept} disabled={busy !== null}>
              {busy ?? "Accept this map"}
            </Button>
            {error && <span className="text-destructive text-sm">{error}</span>}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-4">
            {enrollmentId && (
              <Link href={`/learn/${enrollmentId}`} className={buttonVariants()}>
                Start learning
              </Link>
            )}
            <p className="text-muted-foreground">
              Accepted. It’s on your{" "}
              <Link href="/" className="text-blue-ink underline underline-offset-4">
                courses
              </Link>{" "}
              page.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function OrgTemplateCard({ course }: { course: CourseDetail }) {
  const docs = course.docs ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {course.org_name} course, grounded in {docs.length} {docs.length === 1 ? "doc" : "docs"}
        </CardTitle>
        <CardDescription>
          Lessons cite the section they draw from, and say so when these docs don&apos;t cover
          something.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="divide-y border-y">
          {docs.map((d) => (
            <li
              key={d.slug}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2 text-sm"
            >
              <span className="text-strong">{d.title}</span>
              <span className="text-muted-foreground font-mono text-xs">
                {d.slug} · {d.section_count} sections
              </span>
            </li>
          ))}
        </ul>
        {course.doc_set_hash && (
          <p className="text-muted-foreground text-sm">
            Doc set{" "}
            <span className="text-cyan-ink font-mono" title={course.doc_set_hash}>
              {course.doc_set_hash.slice(0, 12)}
            </span>
            . Lessons are only ever shared with courses grounded in exactly this set.
          </p>
        )}
        <p className="text-sm">
          Org courses have no diagnostic probe: you build the template, and each learner&apos;s plan
          starts from a copy of it. The template builder isn&apos;t available yet.
        </p>
      </CardContent>
    </Card>
  );
}
