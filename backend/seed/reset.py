"""`make reset`: back to a known state for a walkthrough. Wipes every app table (not the schema),
re-seeds, and loads the sample learner state (seed/sample.py).

Redis: deletes only the keys that point at the wiped rows, sessions (`sess:*`) and dashboards
(`dash:*`). It never runs FLUSHDB: on Redis 8 that also drops every search index (ADR-0019).
The LLM caches stay, because their keys hold no user or course ids: a lesson generated before
the reset is still the right lesson after it, so `make warm-cache` is mostly exact hits.
"""

import asyncio

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.models import Base
from seed import sample
from seed.seed import seed

STALE_KEYS = ("sess:*", "dash:*")


async def wipe_redis(redis: Redis) -> int:
    n = 0
    for pattern in STALE_KEYS:
        batch = [k async for k in redis.scan_iter(match=pattern, count=500)]
        if batch:
            n += await redis.delete(*batch)
    return n


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        print(f"Wiped {len(Base.metadata.sorted_tables)} tables; {await wipe_redis(redis)} keys.")
        await seed(engine)
        print("Seeded the org, users, docs and prototype. Sample state:")
        async with AsyncSession(engine, expire_on_commit=False) as db:
            for what, id_ in (await sample.sample(db, redis)).items():
                print(f"  {what}: {id_}")
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
