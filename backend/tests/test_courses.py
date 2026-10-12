"""J1 intake → probe through the API, with a fake model behind the real wrapper and DB sink."""

import asyncio
import uuid
from collections.abc import Sequence

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import ConceptProgress, LlmCall, PlanVersion
from tests.llm_fakes import FakeAnthropic, message
from tests.test_llm import GOOD_PROBE, SHORT_PROBE, assessed

INTAKE = {
    "config": {"topic": "Redis caching patterns", "self_level": "intermediate"},
    "mission": {"goal": "Ship a cache layer", "expert_means": "I can pick an eviction policy"},
}


def _login(client, username: str) -> None:
    assert client.post("/api/auth/login", json={"username": username}).status_code == 200


def _llm_calls(course_id: str) -> list[LlmCall]:
    async def fetch() -> list[LlmCall]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    select(LlmCall).where(LlmCall.course_id == uuid.UUID(course_id))
                )
                return list(rows.all())  # type: ignore[arg-type]
        finally:
            await engine.dispose()

    return asyncio.run(fetch())


def test_create_requires_login(client) -> None:
    assert client.post("/api/courses", json=INTAKE).status_code == 401


def test_intake_is_validated(client) -> None:
    _login(client, "kyle")
    bad = {**INTAKE, "config": {**INTAKE["config"], "topic": ""}}
    assert client.post("/api/courses", json=bad).status_code == 422


def test_intake_then_probe(client, fake_llm: FakeAnthropic) -> None:
    _login(client, "kyle")
    created = client.post("/api/courses", json=INTAKE)
    assert created.status_code == 201
    course = created.json()
    assert course["status"] == "draft"
    assert course["questions"] == []
    # Defaults fill the knobs the form didn't send (spec §4.1).
    assert course["config"]["target_hours"] == 3
    assert course["config"]["formats"] == ["reading", "quizzes", "hands_on"]

    fake_llm.reply(message(GOOD_PROBE))
    probed = client.post(f"/api/courses/{course['id']}/probe").json()
    assert probed["status"] == "probed"
    assert [q["id"] for q in probed["questions"]] == ["q1", "q2", "q3"]
    # The learner never sees which concept a question checks: that would be a hint.
    assert set(probed["questions"][0]) == {"id", "prompt"}

    # Idempotent: a second POST (retry, double-click) makes no second LLM call.
    again = client.post(f"/api/courses/{course['id']}/probe").json()
    assert again["questions"] == probed["questions"]
    assert len(fake_llm.requests) == 1
    assert client.get(f"/api/courses/{course['id']}").json()["questions"] == probed["questions"]

    [row] = _llm_calls(course["id"])
    assert (row.skill, row.call, row.status, row.cache_result) == (
        "diagnose",
        "probe",
        "ok",
        "bypass",
    )
    assert row.user_id is not None
    assert row.est_cost_usd > 0


def test_probe_failure_is_retryable_and_logged(client, fake_llm: FakeAnthropic) -> None:
    _login(client, "kyle")
    course = client.post("/api/courses", json=INTAKE).json()

    fake_llm.reply(message(SHORT_PROBE), message(SHORT_PROBE))
    assert client.post(f"/api/courses/{course['id']}/probe").status_code == 502
    assert client.get(f"/api/courses/{course['id']}").json()["status"] == "draft"
    # Both attempts are in the log even though the request failed (own transaction).
    assert [r.status for r in _llm_calls(course["id"])] == ["error", "error"]

    fake_llm.reply(message(GOOD_PROBE))
    assert client.post(f"/api/courses/{course['id']}/probe").json()["status"] == "probed"


def test_other_users_cannot_see_a_course(client) -> None:
    _login(client, "kyle")
    course = client.post("/api/courses", json=INTAKE).json()
    _login(client, "dana")
    assert client.get(f"/api/courses/{course['id']}").status_code == 404
    assert client.post(f"/api/courses/{course['id']}/probe").status_code == 404


def test_probe_without_an_api_key_is_503(client) -> None:
    _login(client, "kyle")
    course = client.post("/api/courses", json=INTAKE).json()
    assert client.post(f"/api/courses/{course['id']}/probe").status_code == 503


OVERCLAIM = assessed(
    assessed_level="novice",
    confidence=0.8,
    evidence=[
        {"question_id": "q1", "observation": "Would restart before looking", "points_to": "novice"}
    ],
    gaps=["cache invalidation", "TTL choice"],
    adjustment_message="You said intermediate, but your answer to q1 suggests we start earlier.",
)
ANSWERS = {"q1": "Restart it.", "q2": "  ", "q3": "No idea."}


def _probed_course(client, fake_llm: FakeAnthropic) -> str:
    _login(client, "kyle")
    course_id = client.post("/api/courses", json=INTAKE).json()["id"]
    fake_llm.reply(message(GOOD_PROBE))
    client.post(f"/api/courses/{course_id}/probe")
    return course_id


def test_assess_relevels_with_an_explanation(client, fake_llm: FakeAnthropic) -> None:
    course_id = _probed_course(client, fake_llm)
    fake_llm.reply(message(OVERCLAIM))

    detail = client.post(f"/api/courses/{course_id}/assess", json={"answers": ANSWERS}).json()

    assert detail["status"] == "assessed"
    assert detail["assessment"]["assessed_level"] == "novice"
    assert detail["assessment"]["adjustment_message"].startswith("You said intermediate")
    # Stored trimmed, in question order; blank stays blank ("I don't know").
    assert detail["answers"] == {"q1": "Restart it.", "q2": "", "q3": "No idea."}
    sent = fake_llm.requests[-1]["messages"][0]["content"]
    assert '"question_id": "q2"' in sent


def test_assessment_is_locked_once_made(client, fake_llm: FakeAnthropic) -> None:
    course_id = _probed_course(client, fake_llm)
    fake_llm.reply(message(OVERCLAIM))
    client.post(f"/api/courses/{course_id}/assess", json={"answers": ANSWERS})

    better = {k: "A much better answer." for k in ANSWERS}
    again = client.post(f"/api/courses/{course_id}/assess", json={"answers": better}).json()

    assert again["assessment"]["assessed_level"] == "novice"
    assert again["answers"]["q1"] == "Restart it."
    assert len(fake_llm.requests) == 2  # probe + one assess; no re-roll


def test_assess_needs_one_answer_per_question(client, fake_llm: FakeAnthropic) -> None:
    course_id = _probed_course(client, fake_llm)
    resp = client.post(f"/api/courses/{course_id}/assess", json={"answers": {"q1": "x"}})
    assert resp.status_code == 422
    assert len(fake_llm.requests) == 1  # rejected before any model call


def test_assess_before_probe_is_409(client, fake_llm: FakeAnthropic) -> None:
    _login(client, "kyle")
    course_id = client.post("/api/courses", json=INTAKE).json()["id"]
    resp = client.post(f"/api/courses/{course_id}/assess", json={"answers": ANSWERS})
    assert resp.status_code == 409


def concept(cid: str, prereqs: list[str], minutes: int = 30) -> dict:
    return {
        "id": cid,
        "title": cid.replace("-", " ").title(),
        "mastery_statement": f"You can explain {cid} and apply it to a new case.",
        "objective_level": "apply",
        "prereqs": prereqs,
        "est_minutes": minutes,
        "concept_type": "systems",
    }


IDS = ["cache-aside", "ttls", "eviction", "invalidation", "stampedes", "write-through"]
# 6 concepts x 30 min = 180 = the intake's default 3 h target.
GOOD_MAP = {
    "concepts": [concept(c, [IDS[i - 1]] if i else []) for i, c in enumerate(IDS)],
    "sequence": IDS,
    "sequence_rationale": "You start with cache-aside because your answers showed gaps there.",
}


def _assessed_course(client, fake_llm: FakeAnthropic) -> str:
    course_id = _probed_course(client, fake_llm)
    fake_llm.reply(message(OVERCLAIM))
    client.post(f"/api/courses/{course_id}/assess", json={"answers": ANSWERS})
    return course_id


def test_map_is_generated_from_the_assessment(client, fake_llm: FakeAnthropic) -> None:
    course_id = _assessed_course(client, fake_llm)
    fake_llm.reply(message(GOOD_MAP))

    detail = client.post(f"/api/courses/{course_id}/map").json()

    assert detail["status"] == "mapped"
    assert detail["concept_map"]["sequence"] == IDS
    sent = fake_llm.requests[-1]["messages"][0]["content"]
    assert '"assessed_level": "novice"' in sent  # the demonstrated level, not the claim
    assert '"target_minutes": 180' in sent  # computed in code
    # Idempotent, like probe and assess.
    client.post(f"/api/courses/{course_id}/map")
    assert len(fake_llm.requests) == 3


def test_map_over_time_budget_is_re_asked(client, fake_llm: FakeAnthropic) -> None:
    course_id = _assessed_course(client, fake_llm)
    too_long = {**GOOD_MAP, "concepts": [concept(c, []) | {"est_minutes": 60} for c in IDS]}
    fake_llm.reply(message(too_long), message(GOOD_MAP))

    assert client.post(f"/api/courses/{course_id}/map").json()["status"] == "mapped"
    retry = fake_llm.requests[-1]["messages"][-1]["content"]
    assert "est_minutes add up to 360" in retry


def test_map_with_unknown_prereq_is_re_asked(client, fake_llm: FakeAnthropic) -> None:
    """★ PC1.3: passes once find_unknown_prereqs is implemented (agent/plan.py)."""
    course_id = _assessed_course(client, fake_llm)
    bad = {
        **GOOD_MAP,
        "concepts": [*GOOD_MAP["concepts"][:-1], concept("write-through", ["ghost"])],
    }
    fake_llm.reply(message(bad), message(GOOD_MAP))

    assert client.post(f"/api/courses/{course_id}/map").json()["status"] == "mapped"
    retry = fake_llm.requests[-1]["messages"][-1]["content"]
    assert "'write-through' lists unknown prereq 'ghost'" in retry


def test_map_before_assessment_is_409(client, fake_llm: FakeAnthropic) -> None:
    course_id = _probed_course(client, fake_llm)
    assert client.post(f"/api/courses/{course_id}/map").status_code == 409


def _mapped_course(client, fake_llm: FakeAnthropic) -> str:
    course_id = _assessed_course(client, fake_llm)
    fake_llm.reply(message(GOOD_MAP))
    client.post(f"/api/courses/{course_id}/map")
    return course_id


def _concepts(detail: dict) -> dict[str, list[str]]:
    return {c["id"]: c["prereqs"] for c in detail["concept_map"]["concepts"]}


def test_removing_a_concept_rewires_its_dependents(client, fake_llm: FakeAnthropic) -> None:
    course_id = _mapped_course(client, fake_llm)
    # GOOD_MAP is a chain: ... ttls <- eviction <- invalidation ...
    detail = client.delete(f"/api/courses/{course_id}/map/concepts/eviction").json()

    assert "eviction" not in _concepts(detail)
    assert _concepts(detail)["invalidation"] == ["ttls"]  # inherited eviction's prereq
    assert "eviction" not in detail["concept_map"]["sequence"]
    # Persisted, not just returned.
    assert _concepts(client.get(f"/api/courses/{course_id}").json())["invalidation"] == ["ttls"]


def test_remove_rejects_unknown_and_last_concepts(client, fake_llm: FakeAnthropic) -> None:
    course_id = _mapped_course(client, fake_llm)
    assert client.delete(f"/api/courses/{course_id}/map/concepts/nope").status_code == 404
    for cid in IDS[:-1]:
        assert client.delete(f"/api/courses/{course_id}/map/concepts/{cid}").status_code == 200
    assert client.delete(f"/api/courses/{course_id}/map/concepts/{IDS[-1]}").status_code == 422


def test_accept_creates_the_enrollment_plan_and_progress(client, fake_llm: FakeAnthropic) -> None:
    course_id = _mapped_course(client, fake_llm)
    client.delete(f"/api/courses/{course_id}/map/concepts/write-through")

    def cards() -> list[dict]:
        dash = client.get("/api/dashboard").json()
        return [c for c in dash["courses"] if c["course_id"] == course_id]

    assert cards() == []  # not on the dashboard until accepted

    detail = client.post(f"/api/courses/{course_id}/accept").json()

    assert detail["status"] == "active"
    assert detail["enrollment_id"] is not None
    rows = _progress(detail["enrollment_id"])
    assert rows == {
        "cache-aside": "unlocked",  # the only concept without prereqs
        "ttls": "locked",
        "eviction": "locked",
        "invalidation": "locked",
        "stampedes": "locked",
    }
    version, trigger, n_concepts = _plan_v1(detail["enrollment_id"])
    assert (version, trigger, n_concepts) == (1, "diagnosis", 5)  # the edited map, copied

    # The dashboard cache was invalidated, so the new course shows up immediately.
    assert client.get("/api/dashboard").json()["served_from"] == "db"
    [card] = cards()
    assert (card["title"], card["concepts_total"]) == ("Redis caching patterns", 5)


def test_accept_is_idempotent_and_locks_the_map(client, fake_llm: FakeAnthropic) -> None:
    course_id = _mapped_course(client, fake_llm)
    first = client.post(f"/api/courses/{course_id}/accept").json()
    again = client.post(f"/api/courses/{course_id}/accept").json()
    assert again["enrollment_id"] == first["enrollment_id"]
    # After accept, changes are plan versions (CP2), not edits to the base map.
    assert client.delete(f"/api/courses/{course_id}/map/concepts/ttls").status_code == 409


def test_accept_before_map_is_409(client, fake_llm: FakeAnthropic) -> None:
    course_id = _assessed_course(client, fake_llm)
    assert client.post(f"/api/courses/{course_id}/accept").status_code == 409


def _db[*Ts](query: Select[*Ts]) -> Sequence[Row[*Ts]]:
    async def run() -> Sequence[Row[*Ts]]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(query)).all()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _progress(enrollment_id: str) -> dict[str, str]:
    rows = _db(
        select(ConceptProgress.concept_id, ConceptProgress.status).where(
            ConceptProgress.enrollment_id == uuid.UUID(enrollment_id)
        )
    )
    return {row[0]: str(row[1]) for row in rows}


def _plan_v1(enrollment_id: str) -> tuple[int, str, int]:
    rows = _db(
        select(PlanVersion.version, PlanVersion.trigger, PlanVersion.plan).where(
            PlanVersion.enrollment_id == uuid.UUID(enrollment_id)
        )
    )
    assert len(rows) == 1
    row = rows[0]
    return row[0], str(row[1]), len(row[2]["concepts"])
