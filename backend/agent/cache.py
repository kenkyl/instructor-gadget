"""Exact-match LLM cache (tier 1): `llm:exact:{sha256}` native JSON documents + `idx:llm_exact`.

The key is a hash of everything that shapes the output: skill, call, model, prompt_version and
the call's input. The input of a cacheable call carries no learner ids or misconceptions by
design (ADR-0007), so a hit can be served to any learner who sends the same input. A new prompt
version produces new keys; old entries age out by TTL (data-model §6.3).

A cache failure never fails the call: Redis errors are treated as a miss (or a skipped write).
The semantic tier (RedisVL, CP3) sits behind this one.
"""

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from redis.commands.search.field import NumericField, TagField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.exceptions import RedisError, ResponseError

log = logging.getLogger(__name__)

PREFIX = "llm:exact:"
INDEX = "idx:llm_exact"
TTL_SECONDS = 7 * 24 * 60 * 60


class ExactEntry(BaseModel):
    """The stored document. `cost_usd` and `latency_ms` are what generating it took, so a later
    hit can record the cost and time it saved (llm_calls.saved_*)."""

    skill: str
    call: str
    prompt_version: str
    model: str
    cost_usd: float
    latency_ms: int
    created_at: int  # unix seconds
    hits: int = 0
    output: dict[str, Any]


def exact_key(skill: str, call: str, model: str, prompt_version: str, payload: BaseModel) -> str:
    """Canonical JSON (sorted keys, no whitespace), so equal inputs always hash the same."""
    canonical = json.dumps(
        {
            "skill": skill,
            "call": call,
            "model": model,
            "prompt_version": prompt_version,
            "input": payload.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return PREFIX + hashlib.sha256(canonical.encode()).hexdigest()


class ExactCache:
    def __init__(self, redis: Redis, *, ttl_seconds: int = TTL_SECONDS) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> ExactEntry | None:
        try:
            raw = await self.redis.json().get(key)
            if raw is None:
                return None
            entry = ExactEntry.model_validate(raw)  # don't trust the stored shape
            # Atomic on the server: no read-modify-write race between concurrent hits.
            await self.redis.json().numincrby(key, "$.hits", 1)
            return entry
        except ValidationError:
            log.warning("exact cache: malformed entry %s, treating as a miss", key)
            return None
        except RedisError:
            log.warning("exact cache: lookup failed for %s, treating as a miss", key, exc_info=True)
            return None

    async def put(self, key: str, entry: ExactEntry) -> None:
        try:
            # One MULTI/EXEC: an entry never exists without its TTL.
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.json().set(key, "$", entry.model_dump(mode="json"))
                pipe.expire(key, self.ttl_seconds)
                await pipe.execute()
        except RedisError:
            log.warning("exact cache: write failed for %s", key, exc_info=True)


async def ensure_index(redis: Redis, *, index: str = INDEX, prefix: str = PREFIX) -> bool:
    """Create the index if it doesn't exist (called at startup; idempotent).

    The Query Engine only indexes logical DB 0 ("Cannot create index on db != 0"), so on any
    other DB (the tests use 15) this skips and returns False: the cache still works, only the
    inventory index is missing (ADR-0019).
    """
    if redis.connection_pool.connection_kwargs.get("db", 0) != 0:
        log.warning("%s not created: search indexes need Redis DB 0 (ADR-0019)", index)
        return False
    try:
        await redis.ft(index).info()
        return True
    except ResponseError:
        pass  # unknown index
    await redis.ft(index).create_index(
        [
            TagField("$.skill", as_name="skill"),
            TagField("$.call", as_name="call"),
            TagField("$.prompt_version", as_name="prompt_version"),
            TagField("$.model", as_name="model"),
            NumericField("$.cost_usd", as_name="cost_usd"),
            NumericField("$.latency_ms", as_name="latency_ms"),
            NumericField("$.hits", as_name="hits"),
            NumericField("$.created_at", as_name="created_at"),
        ],
        definition=IndexDefinition(prefix=[prefix], index_type=IndexType.JSON),
    )
    return True
