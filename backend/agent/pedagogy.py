"""Deterministic pedagogy rules (CLAUDE.md: "skills do language; code does decisions").

Pure functions, no I/O: scoring (spec §4.7), mastery and bands (§4.9), the unlock gate (§4.8)
and FSRS review scheduling (§4.10). Services read state, call these, and write the results.
Adaptation rules (the `adapt` branch table) land in PC2.5.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from fsrs import Card, Rating, Scheduler
from fsrs.card import CardDict
from pydantic import TypeAdapter

from agent.plan import Graph
from agent.types import Band

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
