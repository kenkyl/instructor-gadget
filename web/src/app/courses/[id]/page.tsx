"use client";

// Round 2, diagnostic probe (spec §4.2): 3–4 questions at the claimed level, all answered on
// one screen. Submitting the answers for assessment arrives in PC1.2.
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, type Schemas } from "@/lib/api";

type CourseDetail = Schemas["CourseDetail"];

export default function CoursePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [probing, setProbing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<CourseDetail>(`/courses/${id}`).then(setCourse, (e: Error) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [id, router]);

  async function generateQuestions() {
    setProbing(true);
    setError(null);
    try {
      setCourse(await apiPost<CourseDetail>(`/courses/${id}/probe`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProbing(false);
    }
  }

  if (!course) {
    return <p className="p-10 text-muted-foreground">{error ?? "Loading…"}</p>;
  }

  const questions = course.questions ?? [];
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
            <Button onClick={generateQuestions} disabled={probing}>
              {probing ? "Writing your diagnostic questions…" : "Write my diagnostic questions"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <section className="space-y-4">
          <div>
            <h2 className="text-lg font-medium">Where are you really?</h2>
            <p className="text-muted-foreground text-sm">
              You said {config.self_level}. Answer in a few sentences each; your answers, not the
              label, decide where the course starts. “I don’t know” is a fine answer.
            </p>
          </div>
          {questions.map((q, i) => (
            <Card key={q.id}>
              <CardHeader>
                <CardTitle className="text-base font-normal">
                  <span className="text-muted-foreground mr-2">{i + 1}.</span>
                  {q.prompt}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Label htmlFor={q.id} className="sr-only">
                  Your answer to question {i + 1}
                </Label>
                <Textarea
                  id={q.id}
                  rows={4}
                  value={answers[q.id] ?? ""}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                />
              </CardContent>
            </Card>
          ))}
          <div className="flex items-center gap-3">
            <Button disabled title="Assessment arrives in the next checkpoint (PC1.2)">
              Submit answers
            </Button>
            <span className="text-muted-foreground text-xs">Assessment is coming next.</span>
          </div>
        </section>
      )}
    </main>
  );
}
