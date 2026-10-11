"""agent/cache.py: the exact-match tier (`llm:exact:*` native JSON + `idx:llm_exact`)."""

import asyncio
import uuid

import pytest
from redis.asyncio import Redis
from redis.commands.search.result import Result

from agent.cache import ExactCache, ExactEntry, ensure_index, exact_key
from agent.skills.diagnose.schema import ProbeInput
from agent.types import CourseConfig, Mission
from app.config import get_settings

PAYLOAD = ProbeInput(
    config=CourseConfig(topic="Redis caching patterns"),
    mission=Mission(goal="Ship a cache layer", expert_means="I can pick an eviction policy"),
)


def entry(**overrides) -> ExactEntry:
    fields = dict(
        skill="teach-concept",
        call="teach",
        prompt_version="teach-concept@0.1.0+abcd1234",
        model="claude-sonnet-5-5",
        cost_usd=0.027,
        latency_ms=21400,
        created_at=1791709200,
        output={"explanation_md": "x"},
    )
    return ExactEntry.model_validate(fields | overrides)


def with_redis(fn, url: str | None = None):
    async def go():
        r = Redis.from_url(url or get_settings().redis_url, decode_responses=True)
        try:
            return await fn(r)
        finally:
            await r.aclose()

    return asyncio.run(go())


def test_key_is_stable_and_covers_every_input() -> None:
    k = exact_key("s", "c", "m", "v1", PAYLOAD)
    assert k == exact_key("s", "c", "m", "v1", PAYLOAD.model_copy(deep=True))
    assert k.startswith("llm:exact:") and len(k) == len("llm:exact:") + 64
    other_topic = PAYLOAD.model_copy(update={"config": CourseConfig(topic="Postgres indexes")})
    assert (
        len(
            {
                k,
                exact_key("s", "c", "m", "v2", PAYLOAD),  # new prompt version → new key
                exact_key("s", "c", "other-model", "v1", PAYLOAD),
                exact_key("s", "c", "m", "v1", other_topic),
            }
        )
        == 4
    )


def test_put_then_get_counts_hits_and_sets_a_ttl() -> None:
    key = f"llm:exact:test-{uuid.uuid4().hex}"

    async def go(r: Redis):
        cache = ExactCache(r)
        assert await cache.get(key) is None
        await cache.put(key, entry())
        first = await cache.get(key)
        await cache.get(key)
        return first, await r.json().get(key, "$.hits"), await r.ttl(key)

    first, hits, ttl = with_redis(go)
    assert first is not None and first.output == {"explanation_md": "x"}
    assert hits == [2]  # incremented on the server, once per hit
    assert 0 < ttl <= 7 * 24 * 3600


def test_malformed_entry_is_a_miss() -> None:
    key = f"llm:exact:test-{uuid.uuid4().hex}"

    async def go(r: Redis):
        await r.json().set(key, "$", {"skill": "teach-concept"})  # missing fields
        return await ExactCache(r).get(key)

    assert with_redis(go) is None


def test_index_is_skipped_off_db_0() -> None:
    # The Query Engine refuses indexes on DB != 0 (ADR-0019); the tests use DB 15.
    assert with_redis(ensure_index) is False


def test_index_on_db_0_finds_entries_by_tag() -> None:
    db0 = get_settings().redis_url.rsplit("/", 1)[0] + "/0"
    run = uuid.uuid4().hex[:8]
    index, prefix = f"test:idx:llm_exact:{run}", f"test:{run}:llm:exact:"

    async def go(r: Redis):
        try:
            assert await ensure_index(r, index=index, prefix=prefix)
            assert await ensure_index(r, index=index, prefix=prefix)  # idempotent
            await ExactCache(r).put(prefix + "a", entry())
            await ExactCache(r).put(prefix + "b", entry(skill="design-assessment"))
            for _ in range(50):  # indexing is asynchronous
                res = await r.ft(index).search("@skill:{teach\\-concept}")
                assert isinstance(res, Result)
                if res.total:
                    return res.total
                await asyncio.sleep(0.02)
            return 0
        finally:
            await r.ft(index).dropindex(delete_documents=True)

    assert with_redis(go, db0) == 1


@pytest.mark.parametrize("bad_url", ["redis://localhost:1/15"])
def test_redis_down_is_a_miss_not_an_error(bad_url: str) -> None:
    async def go(r: Redis):
        cache = ExactCache(r)
        await cache.put("llm:exact:x", entry())  # logged and skipped
        return await cache.get("llm:exact:x")

    assert with_redis(go, bad_url) is None
