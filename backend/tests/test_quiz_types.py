"""Quiz and grade output validators (spec §4.6–4.7): the re-ask triggers for the model."""

import pytest
from pydantic import ValidationError

from agent.types import (
    Concept,
    GradeOutput,
    Misbelief,
    QuizInput,
    QuizOutput,
    TargetedQuizInput,
)

CONCEPT = Concept(
    id="pool-exhaustion",
    title="Pool exhaustion",
    mastery_statement="You can diagnose pool exhaustion.",
    objective_level="analyze",
    prereqs=[],
    est_minutes=20,
    concept_type="systems",
)
BELIEF = {"label": "bigger pool always helps", "note": "Thinks more connections always help."}


def mcq(qid: str, answer: str = "a", level: str = "analyze", targets: str | None = None) -> dict:
    return {
        "id": qid,
        "prompt": f"Question {qid}?",
        "options": [
            {"id": o, "text": f"Option {o}", "misconception": None if o == answer else BELIEF}
            for o in "abcd"
        ],
        "answer": answer,
        "transfer_situation": "a thread pool in a job runner",
        "objective_level": level,
        "targets_logged_misconception": targets,
    }


def quiz(**overrides: object) -> dict:
    return {
        "questions": [mcq("q1"), mcq("q2", "b"), mcq("q3", "c"), mcq("q4", "d")],
        "explain_item": {
            "prompt": "Explain it for a worker pool.",
            "transfer_situation": "worker pool",
            "rubric": {"score_1": "a", "score_2": "b", "score_3": "c", "score_4": "d"},
        },
        **overrides,
    }


def base_input(**kw: object) -> QuizInput:
    return QuizInput(
        topic="Pools", target_level="intermediate", concept=CONCEPT, lesson=None, round=1, **kw
    )  # type: ignore[arg-type]


def test_good_quiz_validates() -> None:
    QuizOutput.model_validate(quiz(), context={"input": base_input()})


def test_exactly_the_answer_has_no_misconception() -> None:
    bad = mcq("q1", "a")
    bad["options"][1]["misconception"] = None  # two "correct" options
    with pytest.raises(ValidationError, match="exactly the answer option"):
        QuizOutput.model_validate(quiz(questions=[bad, mcq("q2"), mcq("q3"), mcq("q4")]))


def test_needs_a_question_at_the_objective_level() -> None:
    low = [mcq(f"q{i}", level="remember") for i in range(1, 5)]
    with pytest.raises(ValidationError, match="objective level 'analyze'"):
        QuizOutput.model_validate(quiz(questions=low), context={"input": base_input()})


def test_targeted_quiz_must_target_a_logged_belief() -> None:
    inp = TargetedQuizInput(
        **base_input().model_dump(), misconceptions=[Misbelief.model_validate(BELIEF)]
    )
    with pytest.raises(ValidationError, match="must target"):
        QuizOutput.model_validate(quiz(), context={"input": inp})
    targeted = quiz(questions=[mcq("q1", targets=BELIEF["label"]), mcq("q2"), mcq("q3"), mcq("q4")])
    QuizOutput.model_validate(targeted, context={"input": inp})


def test_a_4_requires_transfer() -> None:
    with pytest.raises(ValidationError, match="requires transfer"):
        GradeOutput.model_validate(
            {"transfer_handled": False, "score": 4, "feedback": "f", "misconception": None}
        )
    GradeOutput.model_validate(
        {"transfer_handled": False, "score": 3, "feedback": "f", "misconception": None}
    )
