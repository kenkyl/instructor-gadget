import asyncio
import uuid

import redis
from redis.asyncio import Redis as AsyncRedis

from app.config import get_settings
from app.services.dashboard import dash_key, invalidate_dashboard


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
