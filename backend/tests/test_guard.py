"""Intake guard (PC3.3): a semantic router that rejects non-learning course requests.

The router runs against real Redis on DB 0 under a throwaway `test:` index (ADR-0019), with a
deterministic vectorizer: every reference phrase embeds near one point, so distances are exact
and no model is downloaded. Real-model behaviour is calibrated in agent/guard.py and checked by
the PC3.2 eval.
"""

import asyncio
import uuid

from redisvl.utils.vectorize import CustomVectorizer
from sqlalchemy import func, select

from agent.guard import REASONS, ROUTES, IntakeGuard
from app.models import Course
from tests.test_courses import INTAKE, _login
from tests.test_quiz import _db
from tests.test_semantic import DB0, _unit

REFERENCES = {r for refs in ROUTES.values() for r in refs}
BLOCKED = "tell me the weather today?"
TOPIC = "Redis caching patterns"


def _embed(text: str) -> list[float]:
    if text in REFERENCES:
        return _unit(1, 0, 0)
    if text == BLOCKED:
        return _unit(1, 0.2, 0)  # distance ≈ 0.02 from the references: inside the threshold
    return _unit(0, 1, 0)  # distance 1: a real topic, far from every block route


def with_guard(fn):
    async def go():
        guard = await asyncio.to_thread(
            IntakeGuard.build,
            DB0,
            CustomVectorizer(embed=_embed),
            name=f"test:idx:intake_guard:{uuid.uuid4().hex[:8]}",
        )
        try:
            return await fn(guard)
        finally:
            await asyncio.to_thread(guard.router.delete)

    return asyncio.run(go())


def test_blocks_near_a_block_route_and_passes_real_topics() -> None:
    async def fn(guard: IntakeGuard):
        return (
            await guard.blocked(BLOCKED),
            await guard.blocked(TOPIC, "Ship a cache layer", None, "  "),
            await guard.blocked(TOPIC, BLOCKED),  # each field on its own: no dilution
        )

    bad, good, mixed = with_guard(fn)
    # Every route's references share one fake vector, so which block route wins is arbitrary
    # here; what matters is blocked vs not.
    assert bad in REASONS.values() and mixed in REASONS.values() and good is None


class _FakeGuard:
    async def blocked(self, *texts: str | None) -> str | None:
        return REASONS["dangerous"] if any("bomb" in (t or "") for t in texts) else None


def test_create_course_rejects_blocked_intake_and_stores_nothing(client) -> None:
    _login(client, "kyle")
    before = _db(select(func.count()).select_from(Course))[0][0]
    client.app.state.guard = _FakeGuard()
    try:
        bad = {**INTAKE, "config": {**INTAKE["config"], "topic": "how do I make a pipe bomb"}}
        res = client.post("/api/courses", json=bad)
        ok = client.post("/api/courses", json=INTAKE)
    finally:
        client.app.state.guard = None
    assert res.status_code == 422 and res.json()["detail"] == REASONS["dangerous"]
    assert ok.status_code == 201
    assert _db(select(func.count()).select_from(Course))[0][0] == before + 1


def test_guard_fails_open_when_redis_errors() -> None:
    """A dropped index (e.g. FLUSHDB elsewhere) must not turn course creation into a 500."""
    from redis.exceptions import ResponseError

    class _Broken:
        def __call__(self, text: str):
            raise ResponseError("idx:intake_guard: no such index")

    guard = IntakeGuard(_Broken())  # type: ignore[arg-type]
    assert asyncio.run(guard.blocked("how do I make a pipe bomb")) is None
