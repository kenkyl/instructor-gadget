"""Semantic LLM cache (tier 2, behind the exact tier): RedisVL `SemanticCache` + local MiniLM.

A lesson request is embedded (`SemanticKey.text`) and matched against stored lessons by cosine
distance, but **only inside its bucket** (ADR-0007): the same skill/call, model, prompt
version, org (or public), target level, formats, analogy domain and doc set. The bucket is a
set of TAG fields filtered *before* the vector search, so a lesson can never be served across
orgs or to a learner with different preferences, however close the vectors are.

The threshold is cosine distance (0 = identical, 2 = opposite). A false hit is worse than a
miss (it teaches the wrong concept), so the default is strict until the PC3.2 eval chooses it.

Like the exact tier, a failure never fails the call: Redis errors are a miss or a skipped write.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.query.filter import FilterExpression, Tag
from redisvl.utils.vectorize import BaseVectorizer

log = logging.getLogger(__name__)

INDEX_NAME = "idx:llm_semantic"  # RedisVL also uses it as the key prefix: idx:llm_semantic:{id}
MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384 dims, runs locally on CPU
TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_DISTANCE_THRESHOLD = 0.15  # provisional: PC3.2's eval picks the real default

# The bucket: every field a hit must match exactly (ADR-0007).
BUCKET_FIELDS = (
    "skill_call",
    "model",
    "prompt_version",
    "org_id",
    "target_level",
    "formats_key",
    "analogy_key",
    "doc_set_hash",
)
NONE = "none"


@dataclass(frozen=True)
class SemanticKey:
    """What the service supplies for a semantic-cacheable call: the text to embed, and the
    learner-independent parts of the bucket. The wrapper adds skill/call, model and version."""

    text: str
    org_id: str | None  # None: a personal course, shared in the "public" bucket
    target_level: str
    formats: list[str]
    analogy_domain: str | None
    doc_set_hash: str | None


def _slug(value: str | None) -> str:
    """A tag-safe, case- and punctuation-insensitive form ("Restaurants!" == "restaurants")."""
    if not value or not value.strip():
        return NONE
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or NONE


def bucket(
    skill: str, call: str, model: str, prompt_version: str, key: SemanticKey
) -> dict[str, str]:
    """The exact-match part of a semantic lookup (ADR-0007).

    Values are normalised so equal preferences always produce equal tags: formats are sorted
    and joined with "+" (a comma is RedisVL's tag separator and would split the value), the
    analogy domain is slugged, and missing values become "none" rather than an absent tag
    (an absent tag would match nothing, or worse, a filter that skips it would match anything).
    """
    return {
        "skill_call": f"{skill}.{call}",
        "model": model,
        "prompt_version": prompt_version,
        "org_id": key.org_id or "public",
        "target_level": key.target_level,
        "formats_key": "+".join(sorted({_slug(f) for f in key.formats})) or NONE,
        "analogy_key": _slug(key.analogy_domain),
        "doc_set_hash": key.doc_set_hash or NONE,
    }


def bucket_filter(b: dict[str, str]) -> FilterExpression:
    """Every bucket field must match: AND of TAG equalities, applied before the KNN/range search."""
    expr: FilterExpression | None = None
    for field in BUCKET_FIELDS:
        term = Tag(field) == b[field]
        expr = term if expr is None else expr & term
    assert expr is not None
    return expr


class SemanticEntry(BaseModel):
    """What a stored entry's metadata holds, so a hit can record what it saved."""

    cost_usd: float
    latency_ms: int
    created_at: int


@dataclass(frozen=True)
class SemanticHit:
    key: str  # the Redis key of the entry (stored as lessons.cache_key / llm_calls.cache_key)
    distance: float
    output: dict[str, Any]
    prompt: str  # the text the entry was stored under: what this request matched
    entry: SemanticEntry

    @property
    def similarity(self) -> float:
        return round(1 - self.distance, 4)


class SemanticTier:
    def __init__(self, cache: SemanticCache, vectorizer: BaseVectorizer) -> None:
        self.cache = cache
        self.vectorizer = vectorizer

    @classmethod
    def build(
        cls,
        redis_url: str,
        *,
        distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
        name: str = INDEX_NAME,
        vectorizer: BaseVectorizer | None = None,
        ttl_seconds: int = TTL_SECONDS,
    ) -> "SemanticTier":
        """Synchronous: loads the model and runs FT.INFO/FT.CREATE. Call it via asyncio.to_thread
        at startup. Needs Redis DB 0 (ADR-0019)."""
        if vectorizer is None:
            from redisvl.utils.vectorize import HFTextVectorizer

            vectorizer = HFTextVectorizer(model=MODEL)
        cache = SemanticCache(
            name=name,
            distance_threshold=distance_threshold,
            ttl=ttl_seconds,
            vectorizer=vectorizer,
            filterable_fields=[{"name": f, "type": "tag"} for f in BUCKET_FIELDS],
            redis_url=redis_url,
        )
        return cls(cache, vectorizer)

    @property
    def distance_threshold(self) -> float:
        return self.cache.distance_threshold

    async def embed(self, text: str) -> list[float]:
        # The HF vectorizer has no real async embed (it falls back to a blocking call), so run
        # it in a worker thread: ~10 ms of CPU must not stall the event loop.
        return await asyncio.to_thread(self.vectorizer.embed, text)  # type: ignore[arg-type]

    async def check(
        self, vector: list[float], b: dict[str, str], *, distance_threshold: float | None = None
    ) -> SemanticHit | None:
        try:
            hits = await self.cache.acheck(
                vector=vector,
                num_results=1,
                filter_expression=bucket_filter(b),
                distance_threshold=distance_threshold,
            )
        except RedisError:
            log.warning("semantic cache: lookup failed, treating as a miss", exc_info=True)
            return None
        if not hits:
            return None
        hit = hits[0]
        try:
            # Data read back from Redis: validate its shape before trusting it.
            return SemanticHit(
                key=hit["key"],
                distance=float(hit["vector_distance"]),
                output=json.loads(hit["response"]),
                prompt=hit["prompt"],
                entry=SemanticEntry.model_validate(hit.get("metadata") or {}),
            )
        except (KeyError, ValueError, ValidationError):
            log.warning("semantic cache: malformed entry %s, treating as a miss", hit.get("key"))
            return None

    async def store(
        self,
        text: str,
        vector: list[float],
        b: dict[str, str],
        output: dict[str, Any],
        *,
        cost_usd: float,
        latency_ms: int,
    ) -> str | None:
        meta = SemanticEntry(cost_usd=cost_usd, latency_ms=latency_ms, created_at=int(time.time()))
        try:
            return await self.cache.astore(
                prompt=text,
                response=json.dumps(output),
                vector=vector,
                metadata=meta.model_dump(),
                filters=b,
            )
        except RedisError:
            log.warning("semantic cache: write failed", exc_info=True)
            return None

    async def drop(self) -> None:
        """Delete the index and its entries (tests; a reset)."""
        await self.cache.adelete()
