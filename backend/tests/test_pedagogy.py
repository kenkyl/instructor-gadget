"""agent/pedagogy.py: scoring, mastery, bands, the unlock gate and FSRS (spec §4.7–4.10)."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fsrs import Rating, State
from pydantic import ValidationError

from agent.pedagogy import (
    RATING,
    Score,
    band,
    combine,
    initially_unlocked,
    load_card,
    mcq_score,
    schedule_review,
    unlocked,
    update_mastery,
)
from agent.types import Band

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


# --- ★ your turn ---------------------------------------------------------------------------
class TestMcqScore:
    @pytest.mark.parametrize(("correct", "score"), [(4, 4), (3, 3), (2, 2), (1, 1), (0, 1)])
    def test_mapping(self, correct: int, score: int) -> None:
        assert mcq_score(correct) == score

    @pytest.mark.parametrize("correct", [-1, 5])
    def test_out_of_range(self, correct: int) -> None:
        with pytest.raises(ValueError):
            mcq_score(correct)


class TestCombine:
    def test_mcq_only(self) -> None:
        assert combine(4, None) == 4

    @pytest.mark.parametrize(("mcq", "short", "score"), [(4, 2, 2), (2, 4, 2), (3, 3, 3)])
    def test_lower_of_two(self, mcq: Score, short: Score, score: int) -> None:
        assert combine(mcq, short) == score


class TestUpdateMastery:
    @pytest.mark.parametrize(("score", "evidence"), [(1, 0.20), (2, 0.50), (3, 0.80), (4, 0.95)])
    def test_first_attempt_is_the_evidence(self, score: Score, evidence: float) -> None:
        assert update_mastery(None, score) == pytest.approx(evidence)

    def test_recent_evidence_dominates(self) -> None:
        # The ADR-0005 examples.
        assert update_mastery(0.50, 3) == pytest.approx(0.71)  # 2 then 3
        assert update_mastery(0.20, 3) == pytest.approx(0.62)  # 1 then 3

    def test_one_bad_answer_does_not_erase_history(self) -> None:
        assert update_mastery(0.95, 1) == pytest.approx(0.425)

    def test_zero_is_a_previous_value_not_a_first_attempt(self) -> None:
        assert update_mastery(0.0, 4) == pytest.approx(0.665)


class TestBand:
    @pytest.mark.parametrize(
        ("mastery", "expected"),
        [
            (0.0, Band.shaky),
            (0.399, Band.shaky),
            (0.4, Band.learning),
            (0.699, Band.learning),
            (0.7, Band.solid),
            (0.899, Band.solid),
            (0.9, Band.mastered),
            (1.0, Band.mastered),
        ],
    )
    def test_floors_belong_to_the_band_above(self, mastery: float, expected: Band) -> None:
        assert band(mastery) == expected

    @pytest.mark.parametrize("mastery", [-0.01, 1.01])
    def test_out_of_range(self, mastery: float) -> None:
        with pytest.raises(ValueError):
            band(mastery)

    def test_spec_examples(self) -> None:
        # §4.8/§4.9: a 3 after a 2 is solid; a 3 after a 1 needs one more attempt.
        assert band(update_mastery(update_mastery(None, 2), 3)) == Band.solid
        assert band(update_mastery(update_mastery(None, 1), 3)) == Band.learning
        assert band(update_mastery(None, 4)) == Band.mastered


# --- The unlock gate ------------------------------------------------------------------------
GRAPH = {"a": [], "b": ["a"], "c": ["a", "b"]}


class TestUnlocked:
    def test_new_plan_unlocks_only_roots(self) -> None:
        assert initially_unlocked(GRAPH) == {"a"}

    def test_learning_prereq_keeps_dependent_locked(self) -> None:
        assert unlocked(GRAPH, {"a": Band.learning}) == {"a"}

    @pytest.mark.parametrize("b", [Band.solid, Band.mastered])
    def test_solid_or_better_unlocks(self, b: Band) -> None:
        assert unlocked(GRAPH, {"a": b}) == {"a", "b"}

    def test_every_prereq_must_pass(self) -> None:
        assert unlocked(GRAPH, {"a": Band.solid, "b": Band.shaky}) == {"a", "b"}
        assert unlocked(GRAPH, {"a": Band.solid, "b": Band.solid}) == {"a", "b", "c"}

    def test_ungraded_prereq_is_not_enough(self) -> None:
        assert unlocked(GRAPH, {"a": None}) == {"a"}


# --- FSRS -----------------------------------------------------------------------------------
class TestScheduleReview:
    def test_rating_map(self) -> None:
        assert RATING[1] == Rating.Again and RATING[2] == Rating.Hard
        assert RATING[3] == Rating.Good and RATING[4] == Rating.Easy

    def test_first_attempt_is_day_scale_and_ordered_by_score(self) -> None:
        intervals = [schedule_review(None, s, NOW).due - NOW for s in (1, 2, 3, 4)]
        # ADR-0018: no minute-scale learning steps, so nothing comes due the same day.
        assert all(i >= timedelta(days=1) for i in intervals)
        assert intervals == sorted(intervals) and intervals[1] < intervals[2] < intervals[3]

    def test_first_attempt_graduates_to_review(self) -> None:
        card = schedule_review(None, 3, NOW)
        assert card.state == State.Review and card.last_review == NOW

    def test_on_time_good_review_grows_the_interval(self) -> None:
        first = schedule_review(None, 3, NOW)
        second = schedule_review(first, 3, first.due)
        assert second.due - first.due > first.due - NOW

    def test_deterministic(self) -> None:
        assert schedule_review(None, 3, NOW).due == schedule_review(None, 3, NOW).due

    def test_accepts_any_aware_zone(self) -> None:
        chicago = NOW.astimezone(ZoneInfo("America/Chicago"))
        assert schedule_review(None, 3, chicago).due == schedule_review(None, 3, NOW).due

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError):
            schedule_review(None, 3, NOW.replace(tzinfo=None))

    def test_jsonb_round_trip(self) -> None:
        card = schedule_review(None, 3, NOW)
        stored = json.loads(json.dumps(card.to_dict()))  # what Postgres hands back
        assert load_card(stored).to_dict() == card.to_dict()

    def test_load_card_rejects_a_bad_shape(self) -> None:
        with pytest.raises(ValidationError):
            load_card({"state": "review"})
