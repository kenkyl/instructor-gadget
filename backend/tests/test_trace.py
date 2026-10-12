"""Instructor trace + cache impact (PC3.4): measured savings, and only the caller's own calls."""

import asyncio
import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import CacheResult, CallStatus, LlmCall, User
from tests.test_courses import INTAKE, _login


def _insert(rows: list[dict]) -> None:
    async def run():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                ids = dict((await conn.execute(select(User.username, User.id))).all())
                for r in rows:
                    user = ids[r.pop("user")]
                    await conn.execute(insert(LlmCall).values(id=uuid.uuid4(), user_id=user, **r))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _call(user: str, course_id: str, result: CacheResult, **kw) -> dict:
    return {
        "user": user,
        "course_id": uuid.UUID(course_id),
        "skill": "teach-concept",
        "call": "teach",
        "model": "claude-sonnet-5-5",
        "prompt_version": "teach-concept@0.1.0+abc",
        "cache_result": result,
        "status": CallStatus.ok,
        "input_tokens": 0,
        "output_tokens": 0,
        "est_cost_usd": 0,
        "saved_cost_usd": 0,
        "saved_latency_ms": 0,
        **kw,
    }


@pytest.fixture
def traced_course(client) -> str:
    _login(client, "kyle")
    course_id = client.post("/api/courses", json=INTAKE).json()["id"]
    _insert(
        [
            _call(
                "kyle",
                course_id,
                CacheResult.miss,
                latency_ms=12_000,
                est_cost_usd=0.02,
                input_tokens=2000,
                output_tokens=1400,
            ),
            _call(
                "kyle",
                course_id,
                CacheResult.exact_hit,
                latency_ms=5,
                saved_cost_usd=0.02,
                saved_latency_ms=12_000,
            ),
            _call(
                "kyle",
                course_id,
                CacheResult.semantic_hit,
                latency_ms=100,
                similarity=0.95,
                saved_cost_usd=0.03,
                saved_latency_ms=13_000,
            ),
            _call(
                "kyle",
                course_id,
                CacheResult.bypass,
                skill="grade",
                call="grade",
                latency_ms=3000,
                est_cost_usd=0.01,
            ),
            # Another learner's call on the same course: never shown to kyle.
            _call(
                "dana",
                course_id,
                CacheResult.miss,
                latency_ms=9000,
                est_cost_usd=0.5,
                prompt_excerpt="dana's answers",
            ),
        ]
    )
    return course_id


def test_impact_is_measured_from_hits(client, traced_course: str) -> None:
    res = client.get("/api/trace", params={"course_id": traced_course})
    assert res.status_code == 200
    body = res.json()
    i = body["impact"]
    assert (i["calls"], i["model_calls"], i["lookups"]) == (4, 2, 3)
    assert (i["exact_hits"], i["semantic_hits"]) == (1, 1)
    assert i["hit_rate"] == pytest.approx(2 / 3)  # bypass isn't a lookup: 2 hits of 3 lookups
    assert i["spent_usd"] == pytest.approx(0.03)
    assert i["saved_usd"] == pytest.approx(0.05)
    assert i["saved_seconds"] == pytest.approx((12_000 - 5 + 13_000 - 100) / 1000)
    semantic = next(c for c in body["calls"] if c["cache_result"] == "semantic_hit")
    assert semantic["similarity"] == 0.95 and semantic["course_title"]


def test_trace_shows_only_the_callers_own_calls(client, traced_course: str) -> None:
    calls = client.get("/api/trace", params={"course_id": traced_course}).json()["calls"]
    assert len(calls) == 4 and all(c["prompt_excerpt"] != "dana's answers" for c in calls)
    _login(client, "dana")
    dana = client.get("/api/trace", params={"course_id": traced_course}).json()
    assert [c["est_cost_usd"] for c in dana["calls"]] == [0.5]


def test_unfiltered_trace_lists_courses_newest_first(client, traced_course: str) -> None:
    body = client.get("/api/trace").json()
    assert body["course_id"] is None
    assert body["courses"][0]["id"] == traced_course and body["courses"][0]["calls"] == 4
    times = [c["created_at"] for c in body["calls"]]
    assert times == sorted(times, reverse=True)


def test_trace_needs_a_session(client) -> None:
    client.cookies.clear()
    assert client.get("/api/trace").status_code == 401
