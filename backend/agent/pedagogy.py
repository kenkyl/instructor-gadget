"""Deterministic pedagogy rules (CLAUDE.md: "skills do language; code does decisions").

Pure functions, no I/O: scoring (spec §4.7), mastery and bands (§4.9), the unlock gate (§4.8)
FSRS review scheduling (§4.10) and the adaptation rules (§4.8). Services read state, call
these, and write the results. The LLM never decides any of this; it only writes the "why" and
the remediation content.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from fsrs import Card, Rating, Scheduler
from fsrs.card import CardDict
from pydantic import TypeAdapter

from agent.plan import Graph
from agent.types import Band, Concept, ConceptMap, Misbelief, PlanDiff, PrereqChange, Remedy

Score = Literal[1, 2, 3, 4]  # the 1–4 rubric (spec §4.7)

# --- Config: every tunable constant lives here (spec §4.9). Tuning against outcomes is P2. ---
MCQ_QUESTIONS = 4
# First-try correct answers → score (§4.7).
MCQ_TO_SCORE: dict[int, Score] = {0: 1, 1: 1, 2: 2, 3: 3, 4: 4}
# Evidence per score (§4.9).
EVIDENCE: dict[Score, float] = {1: 0.20, 2: 0.50, 3: 0.80, 4: 0.95}
# Later attempts: mastery = w × previous + (1 − w) × evidence, w = PREVIOUS_WEIGHT (ADR-0005).
PREVIOUS_WEIGHT = 0.3
# Band floors: shaky < 0.4 ≤ learning < 0.7 ≤ solid < 0.9 ≤ mastered (§4.9).
LEARNING_AT = 0.4
SOLID_AT = 0.7
MASTERED_AT = 0.9
# A concept unlocks when every prereq is at this band or better (§4.8).
UNLOCK_BAND = Band.solid
# The 1–4 score is the FSRS rating (§4.10).
RATING: dict[Score, Rating] = {
    1: Rating.Again,
    2: Rating.Hard,
    3: Rating.Good,
    4: Rating.Easy,
}
# Day-scale scheduling: no minute-scale learning steps, no fuzz (ADR-0018).
SCHEDULER = Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False)

# Remediation concepts per concept before the rules stop inserting more and ask for a retake
# instead (no endless remediation loops).
MAX_REMEDIATIONS = 2
REMEDY_MINUTES = 10

_BAND_ORDER = [Band.shaky, Band.learning, Band.solid, Band.mastered]
_card_dict = TypeAdapter(CardDict)


# --- Scoring (§4.7) -------------------------------------------------------------------------
def mcq_score(correct: int) -> Score:
    """First-try correct answers out of MCQ_QUESTIONS → 1–4: 4 → 4, 3 → 3, 2 → 2, 0–1 → 1.

    Raises ValueError outside 0..MCQ_QUESTIONS.
    """
    if correct not in MCQ_TO_SCORE:
        raise ValueError(f"correct must be 0..{MCQ_QUESTIONS}, got {correct}")
    return MCQ_TO_SCORE[correct]


def combine(mcq: Score, short: Score | None) -> Score:
    """The concept score: the lower of the two when both exist (§4.7: never inflate mastery)."""
    return mcq if short is None else min(mcq, short)


# --- Mastery and bands (§4.9) ---------------------------------------------------------------
def update_mastery(previous: float | None, score: Score) -> float:
    """New mastery after a graded attempt. `previous` is None before the first attempt.

    First attempt: the score's evidence. Later: recency-weighted (ADR-0005).
    """
    evidence = EVIDENCE[score]
    if previous is None:  # not `if not previous`: 0.0 is a real previous value
        return evidence
    return PREVIOUS_WEIGHT * previous + (1 - PREVIOUS_WEIGHT) * evidence


def band(mastery: float) -> Band:
    """The band a mastery value falls in; each floor belongs to the band above it.

    Raises ValueError outside 0..1.
    """
    if not 0 <= mastery <= 1:
        raise ValueError(f"mastery must be 0..1, got {mastery}")
    if mastery >= MASTERED_AT:
        return Band.mastered
    if mastery >= SOLID_AT:
        return Band.solid
    if mastery >= LEARNING_AT:
        return Band.learning
    return Band.shaky


# --- The unlock gate (§4.8) -----------------------------------------------------------------
def at_least(b: Band | None, floor: Band) -> bool:
    """True if band `b` is `floor` or better. No band yet (never graded) is never enough."""
    return b is not None and _BAND_ORDER.index(b) >= _BAND_ORDER.index(floor)


def unlocked(graph: Graph, bands: Mapping[str, Band | None]) -> set[str]:
    """Concepts whose prereqs are all at UNLOCK_BAND or better, given the current bands.

    This is the gate as of now. Whether a concept already opened ever re-locks is the
    service's call (PC2.5); overrides past the gate are logged separately (PC2.6).
    """
    return {
        c
        for c, prereqs in graph.items()
        if all(at_least(bands.get(p), UNLOCK_BAND) for p in prereqs)
    }


def initially_unlocked(graph: Graph) -> set[str]:
    """A new plan: nothing is graded yet, so only concepts without prereqs pass the gate."""
    return unlocked(graph, {})


# --- Spaced review (§4.10) ------------------------------------------------------------------
def schedule_review(card: Card | None, score: Score, at: datetime) -> Card:
    """Record a graded attempt at `at` as an FSRS review; returns the updated card.

    `card` is None on the first graded attempt. Store `card.to_dict()` in
    concept_progress.fsrs_card and `card.due` in concept_progress.due.
    """
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")
    at = at.astimezone(UTC)  # fsrs accepts UTC only; Postgres may hand back another zone
    card = card or Card(due=at)
    reviewed, _log = SCHEDULER.review_card(card, RATING[score], at)
    return reviewed


def load_card(data: Any) -> Card:
    """Validate a stored concept_progress.fsrs_card (JSONB) and rebuild the Card."""
    return Card.from_dict(_card_dict.validate_python(data))


# --- Adaptation (§4.8): the `adapt` branch table ---------------------------------------------
class Rule(StrEnum):
    """Which rule fired after a graded attempt. Stored in plan_versions.rule when it changes the
    plan (insert_remediation, offer_test_out once accepted)."""

    offer_test_out = "offer_test_out"  # a 4 (and solid+): offer to test out of the next concept
    advance = "advance"  # solid or better: continue; dependents unlock
    retake = "retake"  # a 3 (or 4) that isn't solid yet: take the quiz again, no remediation
    insert_remediation = "insert_remediation"  # 1–2: re-teach from a different angle


def adapt(score: Score, new_band: Band, remediations: int) -> Rule:
    """The plan change after a graded attempt. Keyed on the **score**; the band (from mastery)
    decides whether the concept is done (spec §4.8, ADR-0005).

    `remediations` is how many remediation concepts this concept already has. Past
    MAX_REMEDIATIONS a low score asks for a retake instead of inserting yet another one.
    """
    if score <= 2:
        return Rule.insert_remediation if remediations < MAX_REMEDIATIONS else Rule.retake
    if not at_least(new_band, UNLOCK_BAND):
        return Rule.retake  # e.g. a 3 after a 1: mastery 0.62, one more attempt (§4.9)
    return Rule.offer_test_out if score == 4 else Rule.advance


def remediation_id(concept_id: str, n: int) -> str:
    suffix = f"-remedy-{n}"
    return concept_id[: 64 - len(suffix)].rstrip("-") + suffix


def remediation_count(cmap: ConceptMap, concept_id: str) -> int:
    return sum(1 for c in cmap.concepts if c.remedy and c.remedy.for_concept == concept_id)


def insert_remediation(
    cmap: ConceptMap,
    concept_id: str,
    *,
    title: str,
    mastery_statement: str,
    angle: str,
    misconception: Misbelief | None,
) -> tuple[ConceptMap, PlanDiff]:
    """The plan with a remediation concept inserted before `concept_id`, which now requires it.

    The remedy takes the original's prereqs, so it unlocks now, and the original re-locks until
    the remedy is solid; then the learner retakes the original's quiz.
    """
    original = cmap.concept(concept_id)
    if original is None:
        raise ValueError(f"unknown concept {concept_id}")
    remedy = Concept(
        id=remediation_id(concept_id, remediation_count(cmap, concept_id) + 1),
        title=title,
        mastery_statement=mastery_statement,
        objective_level=original.objective_level,
        prereqs=list(original.prereqs),
        est_minutes=REMEDY_MINUTES,
        concept_type=original.concept_type,
        remedy=Remedy(for_concept=concept_id, angle=angle, misconception=misconception),
    )
    concepts: list[Concept] = []
    for c in cmap.concepts:
        if c.id == concept_id:
            concepts += [remedy, c.model_copy(update={"prereqs": [*c.prereqs, remedy.id]})]
        else:
            concepts.append(c)
    i = cmap.sequence.index(concept_id)
    new = ConceptMap(
        concepts=concepts,
        sequence=[*cmap.sequence[:i], remedy.id, *cmap.sequence[i:]],
        sequence_rationale=cmap.sequence_rationale,
        test_out=cmap.test_out,
    )
    diff = PlanDiff(
        added=[remedy], prereq_changes=[PrereqChange(concept_id=concept_id, added=[remedy.id])]
    )
    return new, diff


def course_complete(bands: Mapping[str, Band | None]) -> bool:
    """Every concept in the plan (remediations included) is solid or better (spec J2 step 7)."""
    return all(at_least(b, UNLOCK_BAND) for b in bands.values())


# --- Dashboard summary (spec J2 step 7) -----------------------------------------------------
BandKey = Literal["not_started", "shaky", "learning", "solid", "mastered"]
BAND_KEYS: tuple[BandKey, ...] = ("not_started", "shaky", "learning", "solid", "mastered")
_BAND_KEY: dict[Band, BandKey] = {
    Band.shaky: "shaky",
    Band.learning: "learning",
    Band.solid: "solid",
    Band.mastered: "mastered",
}


def band_counts(bands: Iterable[Band | None]) -> dict[BandKey, int]:
    """How many concepts sit in each band, weakest first. No band yet = not started (never
    quizzed), which is not the same as shaky (quizzed, low evidence)."""
    counts: dict[BandKey, int] = dict.fromkeys(BAND_KEYS, 0)
    for b in bands:
        counts["not_started" if b is None else _BAND_KEY[b]] += 1
    return counts


def is_due(due: datetime | None, now: datetime) -> bool:
    """Due for review: FSRS has scheduled it and the date has passed. Never-quizzed concepts
    have no card, so they're never due (they're simply next)."""
    return due is not None and due <= now
