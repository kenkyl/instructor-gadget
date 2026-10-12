"use client";

// Round 1, intake (spec §4.1): one form, every knob pre-filled with a recommended default so
// most learners only type a topic. Submitting saves the course, then asks the instructor for
// the diagnostic questions (round 2) and opens the course page to answer them.
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { BackLink, Page } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiPost, type Schemas } from "@/lib/api";

type Intake = Schemas["CourseIntake"];
type CourseDetail = Schemas["CourseDetail"];
type Mode = Schemas["Mission"]["mode"];
type SelfLevel = Schemas["CourseConfig"]["self_level"];
type TargetLevel = Schemas["CourseConfig"]["target_level"];

// Phase 1 implements these three; the rest are stored and labelled "coming soon" (spec §6).
const FORMATS = [
  { id: "reading", label: "Reading", ready: true },
  { id: "quizzes", label: "Quizzes and tests", ready: true },
  { id: "hands_on", label: "Hands-on building", ready: true },
  { id: "visual", label: "Visual", ready: false },
  { id: "writing", label: "Writing", ready: false },
  { id: "audio", label: "Audio", ready: false },
];

const SELF_LEVELS: { value: SelfLevel; label: string }[] = [
  { value: "novice", label: "Novice: new to this" },
  { value: "intermediate", label: "Intermediate: I use it, with gaps" },
  { value: "strong", label: "Strong: I use it confidently" },
  { value: "expert", label: "Expert: I could teach it" },
];

const TARGET_LEVELS: { value: TargetLevel; label: string }[] = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
  { value: "expert", label: "Expert" },
];

export default function NewCoursePage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [expertMeans, setExpertMeans] = useState(
    "I can apply it confidently at work and explain the tradeoffs to a colleague.",
  );
  const [mode, setMode] = useState<Mode>("foundation");
  const [deadline, setDeadline] = useState("");
  const [hours, setHours] = useState(3);
  const [targetLevel, setTargetLevel] = useState<TargetLevel>("intermediate");
  const [selfLevel, setSelfLevel] = useState<SelfLevel>("intermediate");
  const [analogy, setAnalogy] = useState("");
  const [formats, setFormats] = useState(["reading", "quizzes", "hands_on"]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggleFormat(id: string, on: boolean) {
    setFormats((f) => (on ? [...f, id] : f.filter((x) => x !== id)));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const intake: Intake = {
      config: {
        topic: topic.trim(),
        target_hours: hours,
        target_level: targetLevel,
        self_level: selfLevel,
        formats,
      },
      mission: {
        goal: goal.trim() || topic.trim(),
        expert_means: expertMeans.trim(),
        mode,
        deadline: deadline || null,
        analogy_domain: analogy.trim() || null,
      },
    };
    let course: CourseDetail;
    try {
      setBusy("Saving…");
      course = await apiPost<CourseDetail>("/courses", intake);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return router.replace("/login");
      setError((err as Error).message);
      return setBusy(null);
    }
    try {
      // Called from the submit handler, not an effect, so React dev mode can't fire it twice.
      setBusy("Writing your diagnostic questions…");
      await apiPost<CourseDetail>(`/courses/${course.id}/probe`);
    } catch {
      // The course is saved; its page shows the error state and a retry button.
    }
    // Next 16 keeps this page alive (hidden in <Activity>) after we navigate, and Back restores
    // its state. Reset before leaving, or Back shows a stuck "Writing…" button and the old draft.
    setBusy(null);
    setTopic("");
    setGoal("");
    router.push(`/courses/${course.id}`);
  }

  return (
    <Page className="space-y-8">
      <header className="space-y-3">
        <BackLink href="/">Courses</BackLink>
        <h1>New course</h1>
        <p className="text-muted-foreground max-w-[60ch]">
          Tell the instructor what you want to learn. The defaults suit most courses, so a topic is
          often enough.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4">
            <Field label="What do you want to learn?" htmlFor="topic">
              <Input
                id="topic"
                required
                minLength={2}
                maxLength={300}
                placeholder="e.g. Redis caching patterns"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
              />
            </Field>
            <Field label="Why? What do you want to be able to do?" htmlFor="goal" hint="Optional">
              <Input
                id="goal"
                placeholder="e.g. Design the cache layer for our inference gateway"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
              />
            </Field>
            <Field label="What does “expert” mean to you?" htmlFor="expert">
              <Textarea
                id="expert"
                required
                rows={2}
                value={expertMeans}
                onChange={(e) => setExpertMeans(e.target.value)}
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field label="Your current level" htmlFor="self-level" hint="We'll check it">
              <NativeSelect
                id="self-level"
                className="w-full"
                value={selfLevel}
                onChange={(e) => setSelfLevel(e.target.value as SelfLevel)}
              >
                {SELF_LEVELS.map((l) => (
                  <NativeSelectOption key={l.value} value={l.value}>
                    {l.label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Target level" htmlFor="target-level">
              <NativeSelect
                id="target-level"
                className="w-full"
                value={targetLevel}
                onChange={(e) => setTargetLevel(e.target.value as TargetLevel)}
              >
                {TARGET_LEVELS.map((l) => (
                  <NativeSelectOption key={l.value} value={l.value}>
                    {l.label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Mode" htmlFor="mode">
              <NativeSelect
                id="mode"
                className="w-full"
                value={mode}
                onChange={(e) => setMode(e.target.value as Mode)}
              >
                <NativeSelectOption value="foundation">
                  Foundation: full map, spaced review
                </NativeSelectOption>
                <NativeSelectOption value="cram">Cram: deadline soon, must-knows first</NativeSelectOption>
              </NativeSelect>
            </Field>
            <Field label="Deadline" htmlFor="deadline" hint="Optional">
              <Input
                id="deadline"
                type="date"
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
              />
            </Field>
            <Field label="Time you can spend (hours)" htmlFor="hours">
              <Input
                id="hours"
                type="number"
                min={0.5}
                max={40}
                step={0.5}
                required
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
              />
            </Field>
            <Field label="Explain things using analogies from" htmlFor="analogy" hint="Optional">
              <Input
                id="analogy"
                placeholder="e.g. cooking, football, music"
                value={analogy}
                onChange={(e) => setAnalogy(e.target.value)}
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-3">
            <p className="text-strong text-sm font-semibold">Formats you prefer</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {FORMATS.map((f) => (
                <label key={f.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={formats.includes(f.id)}
                    onCheckedChange={(on) => toggleFormat(f.id, on)}
                  />
                  {f.label}
                  {!f.ready && <span className="text-muted-foreground text-xs">Coming soon</span>}
                </label>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">
              Every course still includes quizzes that make you apply what you learned, whatever
              formats you pick.
            </p>
          </CardContent>
        </Card>

        {error && <p className="text-destructive text-sm">{error}</p>}
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy !== null}>
            {busy ?? "Create course"}
          </Button>
          <Button type="button" variant="outline" onClick={() => router.push("/")} disabled={busy !== null}>
            Cancel
          </Button>
        </div>
      </form>
    </Page>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>
        {label}
        {hint && <span className="text-muted-foreground font-normal">({hint.toLowerCase()})</span>}
      </Label>
      {children}
    </div>
  );
}
