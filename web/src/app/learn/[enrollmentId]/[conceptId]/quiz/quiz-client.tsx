"use client";

// The zero-hint quiz (spec §4.6) and its result (§4.7–4.8). The server never sends answer keys,
// distractor tags or the rubric before submission; the result reveals them. A graded result is
// addressable (?attempt=…) so a reload shows it again without re-grading.
import { Check, GraduationCap, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BackLink, Page } from "@/components/app-shell";
import { MasteryMeter } from "@/components/mastery-meter";
import { PlanDiffView } from "@/components/plan-diff";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";
import { RULE_LABEL, shortDate } from "@/lib/labels";
import { cn } from "@/lib/utils";

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

  const back = <BackLink href={`/learn/${enrollmentId}`}>Plan</BackLink>;

  if (result) return <ResultView result={result} enrollmentId={enrollmentId} back={back} />;
  if (!quiz) {
    return (
      <Page className="space-y-4">
        {back}
        {error ? (
          <p className="text-destructive">{error}</p>
        ) : (
          <p className="text-blue-ink inline-flex items-center gap-2">
            <span className="bg-blue size-1.5 animate-pulse rounded-full" />
            Writing your quiz: new situations, no hints…
          </p>
        )}
      </Page>
    );
  }
  const total = quiz.questions.length + 1;
  const answered = quiz.questions.filter((q) => answers[q.id]).length + ((answers.explain ?? "").trim() ? 1 : 0);
  const complete = answered === total;

  return (
    <Page className="space-y-10">
      <header className="space-y-3">
        {back}
        <h1>{quiz.concept_title}</h1>
        <p className="text-muted-foreground">
          Quiz round <span className="num text-foreground">{quiz.round}</span>. No hints, and only your
          first answers count.
        </p>
      </header>
      <ol className="space-y-10">
        {quiz.questions.map((q, i) => (
          <li key={q.id}>
            <fieldset className="space-y-3">
              <legend className="text-strong mb-3 flex gap-3 font-medium">
                <span className="num text-muted-foreground">{i + 1}</span>
                <span className="max-w-[68ch]">{q.prompt}</span>
              </legend>
              <div className="space-y-2 pl-7">
                {q.options.map((o) => (
                  <label
                    key={o.id}
                    className="hover:bg-muted/60 has-[:checked]:border-blue has-[:checked]:bg-blue/8 has-[:focus-visible]:outline-ring flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2"
                  >
                    <input
                      type="radio"
                      name={q.id}
                      value={o.id}
                      checked={answers[q.id] === o.id}
                      onChange={() => setAnswers((a) => ({ ...a, [q.id]: o.id }))}
                      className="accent-blue mt-1 outline-none"
                    />
                    <span>{o.text}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </li>
        ))}
        <li className="space-y-3">
          <label htmlFor="explain" className="text-strong flex gap-3 font-medium">
            <span className="num text-muted-foreground">{total}</span>
            <span className="max-w-[68ch]">{quiz.explain_prompt}</span>
          </label>
          <div className="pl-7">
            <Textarea
              id="explain"
              rows={6}
              value={answers.explain ?? ""}
              onChange={(e) => setAnswers((a) => ({ ...a, explain: e.target.value }))}
              placeholder="In your own words…"
            />
          </div>
        </li>
      </ol>
      <div className="flex flex-wrap items-center gap-4 border-t pt-6">
        <Button disabled={!complete || busy} onClick={submit}>
          {busy ? "Grading…" : "Submit answers"}
        </Button>
        <span className="text-muted-foreground text-sm">
          <span className="num text-foreground">
            {answered}/{total}
          </span>{" "}
          answered
        </span>
        {error && <p className="text-destructive text-sm">{error}</p>}
      </div>
    </Page>
  );
}

// 1 = red, 2 = yellow, 3–4 = green: the same reading as the mastery bands.
const SCORE_FILL = ["", "bg-red", "bg-yellow", "bg-green", "bg-green"];
const SCORE_INK = ["", "text-red-ink", "text-yellow-ink", "text-green-ink", "text-green-ink"];

function ScoreScale({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-5">
      <div className="flex gap-1.5" role="img" aria-label={`Score ${score} of 4`}>
        {[1, 2, 3, 4].map((n) => (
          <span
            key={n}
            className={cn(
              "num grid h-12 w-10 place-items-center rounded-md text-lg font-semibold",
              n <= score ? cn(SCORE_FILL[score], "text-(--base03)") : "bg-muted text-muted-foreground",
            )}
          >
            {n}
          </span>
        ))}
      </div>
      <p className={cn("text-2xl font-semibold", SCORE_INK[score])}>
        <span className="num">{score}</span> of 4
      </p>
    </div>
  );
}

function ResultView({
  result: r,
  enrollmentId,
  back,
}: {
  result: QuizResult;
  enrollmentId: string;
  back: ReactNode;
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
    <Page className="space-y-12">
      <header className="space-y-5">
        {back}
        <div className="space-y-1">
          <p className="text-muted-foreground">Quiz result</p>
          <h1>{r.concept_title}</h1>
        </div>
        <ScoreScale score={r.score} />
        <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Multiple choice</dt>
          <dd>
            <span className="num">{r.mcq_correct}/4</span> correct, scores{" "}
            <span className="num">{r.mcq_score}</span>
          </dd>
          <dt className="text-muted-foreground">Explanation</dt>
          <dd>
            scores <span className="num">{r.short_score ?? "–"}</span>
          </dd>
          <dt className="text-muted-foreground">Mastery</dt>
          <dd>
            <MasteryMeter band={r.band} mastery={r.mastery} />
          </dd>
          <dt className="text-muted-foreground">Next review</dt>
          <dd>{shortDate(r.due)}</dd>
        </dl>
        <p className="text-muted-foreground text-sm">
          The score is the lower of the two parts: we&apos;d rather under-claim mastery.
        </p>
      </header>

      <section className="space-y-4 rounded-lg border p-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2>What happens next</h2>
          <Badge variant="violet">{RULE_LABEL[r.rule] ?? r.rule.replaceAll("_", " ")}</Badge>
          {r.plan_version && (
            <span className="num text-violet-ink text-sm font-semibold">plan v{r.plan_version}</span>
          )}
        </div>
        <p className="max-w-[68ch]">{r.why}</p>
        {r.diff && <PlanDiffView diff={r.diff} titles={titles} />}
        {r.misconceptions_named.length > 0 && (
          <div className="space-y-2">
            <p className="font-semibold">Misconceptions logged; your next quizzes will test them</p>
            <ul className="space-y-1.5">
              {r.misconceptions_named.map((m) => (
                <li key={m.label} className="border-magenta border-l-2 pl-3">
                  <span className="text-magenta-ink font-semibold">{m.label}</span>
                  <span className="text-muted-foreground">: {m.note}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {r.unlocked.length > 0 && (
          <p>
            <span className="font-semibold">Unlocked:</span> {r.unlocked.map((u) => u.title).join(", ")}
          </p>
        )}
        {r.course_complete && (
          <p className="bg-green/12 text-green-ink flex items-center gap-2 rounded-md px-3 py-2 font-semibold">
            <GraduationCap className="size-5" />
            Course complete: every concept is solid.
          </p>
        )}
        <div className="flex flex-wrap gap-2 pt-2">
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
              Take the “{r.test_out_offer.title}” quiz
            </Link>
          )}
          {r.rule === "retake" ? (
            <Link href={`/learn/${enrollmentId}/${r.concept_id}`} className={buttonVariants({ variant: "outline" })}>
              Re-read the lesson, then retake
            </Link>
          ) : (
            r.next_concept && (
              <Link href={`/learn/${enrollmentId}/${r.next_concept.concept_id}`} className={buttonVariants()}>
                Next: {r.next_concept.title}
              </Link>
            )
          )}
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
      </section>

      <section className="space-y-8">
        <h2>Your answers</h2>
        <ol className="space-y-8">
          {r.questions.map((q, i) => (
            <li key={q.id} className="space-y-3">
              <p className="text-strong flex gap-3 font-medium">
                <span className="num text-muted-foreground">{i + 1}</span>
                <span className="max-w-[68ch]">{q.prompt}</span>
                <span className="sr-only">{q.correct ? "(correct)" : "(incorrect)"}</span>
              </p>
              <ul className="space-y-1.5 pl-7">
                {q.options.map((o) => {
                  const right = o.id === q.answer;
                  const picked = o.id === q.chosen;
                  return (
                    <li
                      key={o.id}
                      className={cn(
                        "flex items-start gap-2.5 rounded-md border-l-2 px-3 py-2",
                        right && "border-green bg-green/10",
                        picked && !right && "border-red bg-red/10",
                        !right && !picked && "text-muted-foreground border-transparent",
                      )}
                    >
                      <span className="mt-0.5 w-4 shrink-0">
                        {right && <Check className="text-green-ink size-4" />}
                        {picked && !right && <X className="text-red-ink size-4" />}
                      </span>
                      <span>
                        {o.text}
                        {picked && <span className="text-muted-foreground ml-2 text-sm">your answer</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
              {!q.correct && q.misconception && (
                <p className="text-muted-foreground pl-7 text-sm">
                  Your pick reflects <span className="text-magenta-ink font-semibold">{q.misconception.label}</span>:{" "}
                  {q.misconception.note}
                </p>
              )}
            </li>
          ))}
          <li className="space-y-3">
            <p className="text-strong flex gap-3 font-medium">
              <span className="num text-muted-foreground">{r.questions.length + 1}</span>
              <span className="max-w-[68ch]">{r.explain.prompt}</span>
            </p>
            <div className="space-y-3 pl-7">
              <p className="bg-muted rounded-md px-4 py-3 whitespace-pre-wrap">
                {r.explain.answer || <span className="text-muted-foreground">(blank)</span>}
              </p>
              {r.explain.feedback && (
                <div className="flex items-start gap-3">
                  <span className="num shrink-0 font-semibold">{r.explain.score}/4</span>
                  <p className="max-w-[68ch]">
                    {r.explain.transfer_handled ? "Handled the transfer case. " : ""}
                    {r.explain.feedback}
                  </p>
                </div>
              )}
            </div>
          </li>
        </ol>
      </section>
    </Page>
  );
}
