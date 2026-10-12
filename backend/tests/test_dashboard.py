import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from agent.types import Band
from app.config import get_settings
from app.models import ConceptProgress, ConceptStatus
from app.services.dashboard import dash_key, invalidate_dashboard
from tests.test_learning import _enrollment


def _login(client, username: str) -> uuid.UUID:
    resp = client.post("/api/auth/login", json={"username": username})
    assert resp.status_code == 200
    return uuid.UUID(resp.json()["id"])


def test_dashboard_requires_login(client) -> None:
    assert client.get("/api/dashboard").status_code == 401


def test_cache_aside(client) -> None:
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    user_id = _login(client, "kyle")  # login warms the cache
    key = dash_key(user_id)

    # Stored as native JSON with a TTL (ADR-0011).
    assert r.type(key) == "ReJSON-RL"
    assert 0 < r.ttl(key) <= 10 * 60
    assert client.get("/api/dashboard").json()["served_from"] == "cache"

    # Simulate expiry: the next read misses, rebuilds from Postgres, and refills Redis.
    r.delete(key)
    body = client.get("/api/dashboard").json()
    assert body["served_from"] == "db"
    assert body["user"]["username"] == "kyle"
    assert r.exists(key)


def test_invalidate(client) -> None:
    """★ PC0.5: passes once invalidate_dashboard is implemented."""
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    user_id = _login(client, "priya")
    assert r.exists(dash_key(user_id))

    async def run() -> None:
        async_r = AsyncRedis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            await invalidate_dashboard(async_r, user_id)
        finally:
            await async_r.aclose()

    asyncio.run(run())

    assert not r.exists(dash_key(user_id))
    assert client.get("/api/dashboard").json()["served_from"] == "db"


def test_the_dashboard_shows_bands_and_due_in_plan_order(client, fake_llm) -> None:
    eid = uuid.UUID(_enrollment(client, fake_llm))
    plan = client.get(f"/api/enrollments/{eid}").json()["progress"]
    first, second = plan[0]["concept_id"], plan[1]["concept_id"]

    async def seed_progress() -> None:
        engine = create_async_engine(get_settings().database_url)
        past = datetime.now(UTC) - timedelta(days=1)
        async with engine.begin() as conn:
            for cid, values in (
                (first, {"band": Band.solid, "status": ConceptStatus.complete, "due": past}),
                (second, {"band": Band.shaky}),
            ):
                await conn.execute(
                    update(ConceptProgress)
                    .where(ConceptProgress.enrollment_id == eid, ConceptProgress.concept_id == cid)
                    .values(**values)
                )
        await engine.dispose()

    asyncio.run(seed_progress())
    me = client.get("/api/dashboard").json()["user"]["id"]
    redis.Redis.from_url(get_settings().redis_url).delete(dash_key(uuid.UUID(me)))

    course = client.get("/api/dashboard").json()["courses"][0]
    assert (course["due_count"], course["concepts_complete"]) == (1, 1)
    assert (course["bands"]["solid"], course["bands"]["shaky"]) == (1, 1)
    assert course["bands"]["not_started"] == course["concepts_total"] - 2
    assert [c["concept_id"] for c in course["concepts"]][:2] == [first, second]
    assert course["concepts"][0]["due"] and course["concepts"][0]["title"]
