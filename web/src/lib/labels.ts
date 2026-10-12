// One vocabulary for learning state across every page: what each state is called, and which
// semantic tone (globals.css) it wears.
import type { Schemas } from "@/lib/api";

export type Tone = "green" | "yellow" | "orange" | "red" | "violet" | "cyan" | "blue" | "magenta";

type Band = Schemas["Band"];
type Status = Schemas["ConceptStatus"];
type Trigger = Schemas["PlanTrigger"];

export const BAND_TONE: Record<Band, Tone> = {
  shaky: "red",
  learning: "yellow",
  solid: "green",
  mastered: "green",
};

export const STATUS_LABEL: Record<Status, string> = {
  locked: "Locked",
  unlocked: "Ready",
  in_progress: "In progress",
  complete: "Complete",
};

export const TRIGGER_LABEL: Record<Trigger, string> = {
  diagnosis: "Planned from your diagnostic",
  assignment: "Assigned",
  quiz_result: "Re-planned after a quiz",
  prereq_override: "You opened a concept early",
  user_request: "You changed the plan",
};

export const RULE_LABEL: Record<string, string> = {
  offer_test_out: "Offer test-out",
  advance: "Advance",
  retake: "Retake",
  insert_remediation: "Insert remediation",
};

export const CACHE_LABEL: Record<Schemas["CacheResult"], string> = {
  miss: "Written for you",
  exact_hit: "Exact cache hit",
  semantic_hit: "Semantic cache hit",
  bypass: "Cache bypassed",
};

export const pct = (x: number | null | undefined) => `${Math.round((x ?? 0) * 100)}%`;

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
