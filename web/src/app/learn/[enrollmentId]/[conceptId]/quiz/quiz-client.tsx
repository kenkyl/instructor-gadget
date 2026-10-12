"use client";

// The zero-hint quiz (spec §4.6) and its result (§4.7–4.8). The server never sends answer keys,
// distractor tags or the rubric before submission; the result reveals them. A graded result is
// addressable (?attempt=…) so a reload shows it again without re-grading.
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PlanDiffView } from "@/components/plan-diff";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";

type QuizView = Schemas["QuizView"];
type QuizResult = Schemas["QuizResult"];

export default function QuizPage() {
  const { enrollmentId, conceptId } = useParams<{ enrollmentId: string; conceptId: string }>();
  const attemptParam = useSearchParams().get("attempt");
  const router = useRouter();
  const [quiz, setQuiz] = useState<QuizView | null>(null);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const fail = (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    };
    if (attemptParam) {
      apiGet<QuizResult>(`/enrollments/${enrollmentId}/quiz-attempts/${attemptParam}`).then(setResult, fail);
    } else {
      apiPost<QuizView>(`/enrollments/${enrollmentId}/concepts/${conceptId}/quiz`).then(setQuiz, fail);
    }
  }, [enrollmentId, conceptId, attemptParam, router]);

  const submit = async () => {
    if (!quiz) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiPost<QuizResult>(
        `/enrollments/${enrollmentId}/quiz-attempts/${quiz.attempt_id}/submit`,
        { answers },
      );
      setResult(r);
      router.replace(`/learn/${enrollmentId}/${conceptId}/quiz?attempt=${r.attempt_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const back = (
    <Link href={`/learn/${enrollmentId}`} className="text-muted-foreground text-sm hover:underline">
      ← Plan
    </Link>
  );

  if (result) return <ResultView result={result} enrollmentId={enrollmentId} back={back} />;
  if (!quiz) {
    return (
      <main className="mx-auto max-w-2xl p-10 space-y-4">
        {back}
        <p className="text-muted-foreground">{error ?? "Writing your quiz (new situations, no hints)…"}</p>
      </main>
    );
  }
  const complete = quiz.questions.every((q) => answers[q.id]) && (answers.explain ?? "").trim();

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-8">
      <header className="space-y-1">
        {back}
        <h1 className="text-2xl font-semibold">Quiz: {quiz.concept_title}</h1>
        <p className="text-muted-foreground text-sm">
          Round {quiz.round}. No hints, and only your first answers count.
        </p>
      </header>
      {quiz.questions.map((q, i) => (
        <fieldset key={q.id} className="space-y-2">
          <legend className="font-medium">
            {i + 1}. {q.prompt}
          </legend>
          {q.options.map((o) => (
            <label key={o.id} className="flex items-start gap-2 rounded border p-2 text-sm has-[:checked]:border-primary">
              <input
                type="radio"
                name={q.id}
                value={o.id}
                checked={answers[q.id] === o.id}
                onChange={() => setAnswers((a) => ({ ...a, [q.id]: o.id }))}
                className="mt-1"
              />
              <span>{o.text}</span>
            </label>
          ))}
        </fieldset>
      ))}
      <section className="space-y-2">
        <p className="font-medium">5. {quiz.explain_prompt}</p>
        <Textarea
          rows={6}
          value={answers.explain ?? ""}
          onChange={(e) => setAnswers((a) => ({ ...a, explain: e.target.value }))}
          placeholder="In your own words…"
        />
      </section>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button disabled={!complete || busy} onClick={submit}>
        {busy ? "Grading…" : "Submit answers"}
      </Button>
    </main>
  );
}

function ResultView({
  result: r,
  enrollmentId,
  back,
}: {
  result: QuizResult;
  enrollmentId: string;
  back: React.ReactNode;
}) {
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titles: Record<string, string> = Object.fromEntries([
    [r.concept_id, r.concept_title],
    ...(r.diff?.added ?? []).map((c) => [c.id, c.title]),
    ...r.unlocked.map((u) => [u.concept_id, u.title]),
  ]);
  const testOut = async () => {
    if (!r.test_out_offer) return;
    try {
      await apiPost(`/enrollments/${enrollmentId}/concepts/${r.test_out_offer.concept_id}/test-out`);
      setAccepted(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <main className="mx-auto max-w-2xl p-10 space-y-8">
      <header className="space-y-2">
        {back}
        <h1 className="text-2xl font-semibold">Result: {r.concept_title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge className="text-base">Score {r.score} / 4</Badge>
          <Badge variant="outline">
            multiple choice {r.mcq_correct}/4 → {r.mcq_score}
          </Badge>
          <Badge variant="outline">explanation {r.short_score ?? "—"}</Badge>
          <Badge variant="secondary">
            {r.band} · mastery {Math.round(r.mastery * 100)}%
          </Badge>
          <span className="text-muted-foreground">
            review due {new Date(r.due).toLocaleDateString()}
          </span>
        </div>
        <p className="text-muted-foreground text-xs">The score is the lower of the two parts: we&apos;d rather under-claim mastery.</p>
      </header>

      <section className="space-y-3 rounded border p-4">
        <h2 className="font-semibold">
          What happens next <Badge variant="outline">{r.rule.replaceAll("_", " ")}</Badge>
          {r.plan_version && <Badge className="ml-2">plan v{r.plan_version}</Badge>}
        </h2>
        <p>{r.why}</p>
        {r.diff && <PlanDiffView diff={r.diff} titles={titles} />}
        {r.misconceptions_named.length > 0 && (
          <div className="space-y-1 text-sm">
            <p className="font-medium">Misconceptions logged (your next quizzes will test them):</p>
            <ul className="list-disc pl-5">
              {r.misconceptions_named.map((m) => (
                <li key={m.label}>
                  <span className="font-medium">{m.label}</span>: {m.note}
                </li>
              ))}
            </ul>
          </div>
        )}
        {r.unlocked.length > 0 && (
          <p className="text-sm">Unlocked: {r.unlocked.map((u) => u.title).join(", ")}</p>
        )}
        {r.course_complete && <p className="font-semibold">🎓 Course complete: every concept is solid.</p>}
        <div className="flex flex-wrap gap-2">
          {r.test_out_offer && !accepted && (
            <Button variant="outline" onClick={testOut}>
              Test out of “{r.test_out_offer.title}” (skip its lesson)
            </Button>
          )}
          {r.test_out_offer && accepted && (
            <Link
              href={`/learn/${enrollmentId}/${r.test_out_offer.concept_id}/quiz`}
              className={buttonVariants()}
            >
              Take the “{r.test_out_offer.title}” quiz →
            </Link>
          )}
          {r.rule === "retake" ? (
            <Link href={`/learn/${enrollmentId}/${r.concept_id}`} className={buttonVariants({ variant: "outline" })}>
              Re-read, then retake →
            </Link>
          ) : (
            r.next_concept && (
              <Link href={`/learn/${enrollmentId}/${r.next_concept.concept_id}`} className={buttonVariants()}>
                Next: {r.next_concept.title} →
              </Link>
            )
          )}
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
      </section>

      <section className="space-y-4">
        <h2 className="font-semibold">Your answers</h2>
        {r.questions.map((q, i) => (
          <div key={q.id} className="space-y-1 text-sm">
            <p className="font-medium">
              {i + 1}. {q.prompt} {q.correct ? "✓" : "✗"}
            </p>
            <ul className="space-y-1">
              {q.options.map((o) => (
                <li
                  key={o.id}
                  className={
                    o.id === q.answer
                      ? "rounded bg-green-50 p-1 dark:bg-green-950"
                      : o.id === q.chosen
                        ? "rounded bg-red-50 p-1 dark:bg-red-950"
                        : "p-1 text-muted-foreground"
                  }
                >
                  {o.id === q.chosen ? "→ " : ""}
                  {o.text}
                </li>
              ))}
            </ul>
            {!q.correct && q.misconception && (
              <p className="text-muted-foreground">
                Your pick reflects “{q.misconception.label}”: {q.misconception.note}
              </p>
            )}
          </div>
        ))}
        <div className="space-y-1 text-sm">
          <p className="font-medium">5. {r.explain.prompt}</p>
          <p className="rounded bg-muted p-2 whitespace-pre-wrap">{r.explain.answer || "(blank)"}</p>
          {r.explain.feedback && (
            <p>
              <Badge variant="outline">{r.explain.score}/4</Badge>{" "}
              {r.explain.transfer_handled ? "Handled the transfer case. " : ""}
              {r.explain.feedback}
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
