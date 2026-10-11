"""J2 quiz → grade → adapt through the API (PC2.4–2.6), with the model faked."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import ConceptProgress, LlmCall, Misconception, PrereqOverride
from tests.llm_fakes import FakeAnthropic, message
from tests.test_courses import GOOD_MAP, _assessed_course, concept
from tests.test_learning import _enrollment, _events, _open
from tests.test_llm import GOOD_LESSON
from tests.test_quiz_types import BELIEF, mcq

QUIZ = {
    "questions": [mcq("q1", "a", level="apply"), mcq("q2", "b"), mcq("q3", "c"), mcq("q4", "d")],
    "explain_item": {
        "prompt": "Explain it for a worker pool.",
        "transfer_situation": "worker pool",
        "rubric": {"score_1": "a", "score_2": "b", "score_3": "c", "score_4": "d"},
    },
}
# A quiz for a learner with logged beliefs must target one (design_targeted).
TARGETED = {
    **QUIZ,
    "questions": [mcq("q1", targets=BELIEF["label"], level="apply"), *QUIZ["questions"][1:]],
}
RIGHT = {"q1": "a", "q2": "b", "q3": "c", "q4": "d"}
WRONG = {"q1": "b", "q2": "a", "q3": "c", "q4": "a"}  # 1/4 → MCQ score 1


def grade(score: int, transfer: bool = False, belief: dict | None = None) -> dict:
    return {
        "transfer_handled": transfer,
        "score": score,
        "feedback": "You said X. It actually does Y. The underlying belief is Z.",
        "misconception": belief,
    }


EXPLAIN = {
    "why": "You scored 1 on Cache Aside. You believe a bigger pool always helps. Added a short "
    "concept that attacks that before you retake the quiz.",
    "remediation_concept": {
        "title": "Why more connections can make it worse",
        "mastery_statement": "You can predict when adding connections won't help.",
        "angle": "A numbers-first trace instead of an analogy.",
    },
}


def _db(query):
    async def run():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(query)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _learned(client, fake_llm: FakeAnthropic) -> str:
    """An enrollment whose first concept's lesson has been read."""
    eid = _enrollment(client, fake_llm)
    fake_llm.reply(message(GOOD_LESSON))
    assert _events(_open(client, eid, "cache-aside").text)[-1][0] == "done"
    return eid


def _quiz(client, eid: str, cid: str = "cache-aside"):
    return client.post(f"/api/enrollments/{eid}/concepts/{cid}/quiz")


def _submit(client, eid: str, attempt_id: str, answers: dict, explain: str = "My answer."):
    url = f"/api/enrollments/{eid}/quiz-attempts/{attempt_id}/submit"
    return client.post(url, json={"answers": {**answers, "explain": explain}})


def test_quiz_needs_the_lesson_and_hides_answer_keys(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    assert _quiz(client, eid).status_code == 409  # lesson not read yet
    assert _quiz(client, eid, "ttls").status_code == 409  # locked

    fake_llm.reply(message(GOOD_LESSON))
    _open(client, eid, "cache-aside")
    fake_llm.reply(message(QUIZ))
    view = _quiz(client, eid).json()

    assert view["round"] == 1 and len(view["questions"]) == 4
    text = str(view)
    assert "misconception" not in text and "answer" not in text and "rubric" not in text
    assert view["questions"][0]["options"][0] == {"id": "a", "text": "Option a"}
    # Reopening returns the same quiz without another model call.
    calls = len(fake_llm.requests)
    assert _quiz(client, eid).json()["attempt_id"] == view["attempt_id"]
    assert len(fake_llm.requests) == calls
    # The design input is shareable: the lesson, no learner data (ADR-0007).
    sent = fake_llm.requests[-1]["messages"][0]["content"]
    assert GOOD_LESSON["example_md"] in sent and "misconceptions" not in sent


def test_bad_attempt_inserts_remediation_naming_the_misconception(
    client, fake_llm: FakeAnthropic
) -> None:
    eid = _learned(client, fake_llm)
    fake_llm.reply(message(QUIZ))
    attempt = _quiz(client, eid).json()["attempt_id"]
    fake_llm.reply(message(grade(1, belief=BELIEF)), message(EXPLAIN))

    result = _submit(client, eid, attempt, WRONG).json()

    assert (result["mcq_correct"], result["mcq_score"], result["short_score"]) == (1, 1, 1)
    assert result["score"] == 1 and result["band"] == "shaky" and result["mastery"] == 0.2
    assert result["rule"] == "insert_remediation" and result["plan_version"] == 2
    assert "bigger pool always helps" in result["why"]
    assert result["misconceptions_named"][0]["label"] == BELIEF["label"]
    assert result["questions"][0]["misconception"]["label"] == BELIEF["label"]  # revealed now
    remedy = result["diff"]["added"][0]["id"]
    assert remedy == "cache-aside-remedy-1"
    changes = {(c["concept_id"], c["new"]) for c in result["diff"]["status_changes"]}
    assert changes == {(remedy, "unlocked"), ("cache-aside", "locked")}
    assert result["next_concept"]["concept_id"] == remedy

    # Persisted: progress (mastery, band, FSRS due), misconceptions, plan history.
    [p] = _db(
        select(ConceptProgress).where(
            ConceptProgress.enrollment_id == uuid.UUID(eid),
            ConceptProgress.concept_id == "cache-aside",
        )
    )
    assert (p.mastery, p.band, p.last_score, p.attempts) == (0.2, "shaky", 1, 1)
    assert p.due is not None and p.fsrs_card is not None
    labels = [m.label for m in _db(select(Misconception))]
    assert BELIEF["label"] in labels
    history = client.get(f"/api/enrollments/{eid}/plans").json()
    assert [(v["version"], v["trigger"]) for v in history] == [(2, "quiz_result"), (1, "diagnosis")]
    assert history[0]["rule"] == "insert_remediation" and history[0]["reason"] == EXPLAIN["why"]
    # Reloading the result needs no model call; resubmitting is refused.
    assert client.get(f"/api/enrollments/{eid}/quiz-attempts/{attempt}").json() == result
    assert _submit(client, eid, attempt, WRONG).status_code == 409

    # The remediation lesson is personal (remediate.lesson, never cached) and streams.
    fake_llm.reply(message(GOOD_LESSON))
    done = _events(_open(client, eid, remedy).text)[-1][1]["lesson"]
    assert done["kind"] == "remediation" and done["cache_result"] == "bypass"
    assert "bigger pool always helps" in fake_llm.requests[-1]["messages"][0]["content"]
    # Its quiz targets the logged belief, so it's the never-cached call.
    fake_llm.reply(message(TARGETED))
    assert _quiz(client, eid, remedy).status_code == 200
    calls = [r.call for r in _db(select(LlmCall).where(LlmCall.enrollment_id == uuid.UUID(eid)))]
    assert "design_targeted" in calls


def test_remedy_solid_reopens_the_original(client, fake_llm: FakeAnthropic) -> None:
    eid = _learned(client, fake_llm)
    fake_llm.reply(message(QUIZ))
    attempt = _quiz(client, eid).json()["attempt_id"]
    fake_llm.reply(message(grade(2)), message(EXPLAIN))
    remedy = _submit(client, eid, attempt, WRONG).json()["diff"]["added"][0]["id"]

    fake_llm.reply(message(GOOD_LESSON))
    _open(client, eid, remedy)
    fake_llm.reply(message(TARGETED))  # the picked distractors logged beliefs
    attempt = _quiz(client, eid, remedy).json()["attempt_id"]
    fake_llm.reply(message(grade(3)))
    result = _submit(client, eid, attempt, RIGHT).json()

    assert result["score"] == 3 and result["rule"] == "advance"
    assert [u["concept_id"] for u in result["unlocked"]] == ["cache-aside"]
    assert result["next_concept"]["concept_id"] == "cache-aside"


def test_transfer_answer_scores_4_and_offers_test_out(client, fake_llm: FakeAnthropic) -> None:
    eid = _learned(client, fake_llm)
    fake_llm.reply(message(QUIZ))
    attempt = _quiz(client, eid).json()["attempt_id"]
    fake_llm.reply(message(grade(4, transfer=True)))

    result = _submit(client, eid, attempt, RIGHT).json()

    assert result["score"] == 4 and result["band"] == "mastered"
    assert result["rule"] == "offer_test_out" and result["plan_version"] is None
    assert result["test_out_offer"]["concept_id"] == "ttls"
    assert [u["concept_id"] for u in result["unlocked"]] == ["ttls"]

    # Only the offered concept can be tested out of; accepting is a new plan version.
    assert client.post(f"/api/enrollments/{eid}/concepts/eviction/test-out").status_code == 409
    accepted = client.post(f"/api/enrollments/{eid}/concepts/ttls/test-out").json()
    assert accepted["version"] == 2 and accepted["diff"]["test_out"] == ["ttls"]
    detail = client.get(f"/api/enrollments/{eid}").json()
    ttls = next(p for p in detail["progress"] if p["concept_id"] == "ttls")
    assert ttls["test_out"] and not ttls["has_lesson"]
    # Straight to the quiz, designed without a lesson.
    fake_llm.reply(message(QUIZ))
    assert _quiz(client, eid, "ttls").status_code == 200
    assert '"lesson": null' in fake_llm.requests[-1]["messages"][0]["content"]


def test_blank_explanation_counts_only_the_mcq(client, fake_llm: FakeAnthropic) -> None:
    eid = _learned(client, fake_llm)
    fake_llm.reply(message(QUIZ))
    attempt = _quiz(client, eid).json()["attempt_id"]
    calls = len(fake_llm.requests)

    result = _submit(client, eid, attempt, RIGHT, explain="  ").json()

    assert len(fake_llm.requests) == calls  # no grade call
    assert result["short_score"] is None and result["score"] == 4


def test_override_warns_then_opens_and_is_logged(client, fake_llm: FakeAnthropic) -> None:
    eid = _enrollment(client, fake_llm)
    assert client.get(f"/api/enrollments/{eid}/concepts/cache-aside/override").status_code == 409
    warning = "Without cache-aside you'll misread a stale read as a TTL bug."
    fake_llm.reply(message({"what_will_break": warning}))

    shown = client.get(f"/api/enrollments/{eid}/concepts/ttls/override").json()
    assert shown["warning"] == warning
    assert [u["concept_id"] for u in shown["unmet_prereqs"]] == ["cache-aside"]
    version = client.post(
        f"/api/enrollments/{eid}/concepts/ttls/override", json={"warning": warning}
    ).json()

    assert version["trigger"] == "prereq_override" and version["version"] == 2
    assert warning in version["reason"]
    [o] = _db(select(PrereqOverride).where(PrereqOverride.enrollment_id == uuid.UUID(eid)))
    assert o.unmet_prereqs == ["cache-aside"] and o.warning == warning
    fake_llm.reply(message(GOOD_LESSON))
    assert _events(_open(client, eid, "ttls").text)[-1][0] == "done"


def test_hands_on_pool_lesson_shows_the_seeded_prototype(client, fake_llm: FakeAnthropic) -> None:
    pool = concept("connection-pool-exhaustion", [])
    cmap = {**GOOD_MAP, "concepts": [pool, *GOOD_MAP["concepts"][1:]]}
    cmap["concepts"][1] = {**cmap["concepts"][1], "prereqs": ["connection-pool-exhaustion"]}
    cmap["sequence"] = ["connection-pool-exhaustion", *GOOD_MAP["sequence"][1:]]
    course_id = _assessed_course(client, fake_llm)  # intake formats include hands_on
    fake_llm.reply(message(cmap))
    client.post(f"/api/courses/{course_id}/map")
    eid = client.post(f"/api/courses/{course_id}/accept").json()["enrollment_id"]
    fake_llm.reply(message(GOOD_LESSON))

    done = _events(_open(client, eid, "connection-pool-exhaustion").text)[-1][1]["lesson"]

    assert done["prototype"]["slug"] == "conn-pool-sim"
    assert done["prototype"]["html"].startswith("<!doctype html>")
