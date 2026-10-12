"""Semantic cache tier (PC3.1): the bucket, the filter, and the wrapper's lookup order.

Real Redis + a real vector index on DB 0 under a throwaway `test:` name (ADR-0019), with a
deterministic vectorizer (fixed 3-d vectors per text) so distances are exact and no model is
downloaded. The real MiniLM threshold is chosen by the PC3.2 eval, not here.
"""

import asyncio
import math
import uuid

import pytest
from redisvl.utils.vectorize import CustomVectorizer

from agent.llm import CallContext, Done, LLMClient
from agent.registry import get_registry
from agent.semantic import BUCKET_FIELDS, SemanticKey, SemanticTier, bucket, bucket_filter
from agent.types import LessonOutput
from app.config import get_settings
from tests.llm_fakes import FakeAnthropic, MemorySink, message
from tests.test_llm import GOOD_LESSON, teach_in

DB0 = get_settings().redis_url.rsplit("/", 1)[0] + "/0"
POOL = "Pooling\nPool exhaustion\nYou can diagnose pool exhaustion."
POOL_REWORDED = "Pooling\nConnection pool exhaustion\nYou can diagnose an exhausted pool."
THREADS = "Concurrency\nThread pool exhaustion\nYou can size a thread pool."


def _unit(*v: float) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


VECTORS = {
    POOL: _unit(1, 0, 0),
    POOL_REWORDED: _unit(1, 0.1, 0),  # cosine distance ≈ 0.005: a paraphrase
    THREADS: _unit(1, 1, 0),  # cosine distance ≈ 0.29: related, but a different concept
    "dimension check": _unit(0, 0, 1),
}
fake_vectorizer = CustomVectorizer(embed=lambda text: VECTORS.get(text, _unit(0, 0, 1)))


def key(text: str = POOL, **kw) -> SemanticKey:
    base = {
        "text": text,
        "org_id": None,
        "target_level": "intermediate",
        "formats": ["reading", "quizzes", "hands_on"],
        "analogy_domain": "Restaurants",
        "doc_set_hash": None,
    }
    return SemanticKey(**(base | kw))


def B(k: SemanticKey) -> dict[str, str]:  # noqa: N802 - reads as "the bucket of"
    return bucket("teach-concept", "teach", "claude-sonnet-5-5", "teach-concept@0.1.0+abc", k)


# --- the bucket (pure) -------------------------------------------------------------------------
def test_bucket_normalises_equal_preferences_to_equal_tags() -> None:
    a = B(key(formats=["reading", "quizzes", "hands_on"], analogy_domain="Restaurants!"))
    b = B(key(formats=["hands_on", "reading", "quizzes"], analogy_domain=" restaurants "))
    assert a == b
    assert a["formats_key"] == "hands-on+quizzes+reading"  # "+": a comma would split the tag
    assert a["org_id"] == "public" and a["doc_set_hash"] == "none"
    assert B(key(analogy_domain=None))["analogy_key"] == "none"
    assert set(a) == set(BUCKET_FIELDS)


def test_filter_requires_every_bucket_field() -> None:
    query = str(bucket_filter(B(key())))
    for field in BUCKET_FIELDS:
        assert f"@{field}:" in query


# --- the tier against real Redis ---------------------------------------------------------------
def with_tier(fn, threshold: float = 0.1):
    """Run `fn(tier)` in one event loop against a fresh `test:` index on DB 0, then drop it."""

    async def go():
        tier = await asyncio.to_thread(
            SemanticTier.build,
            DB0,
            name=f"test:llmcache_semantic:{uuid.uuid4().hex[:8]}",
            vectorizer=fake_vectorizer,
            distance_threshold=threshold,
        )
        try:
            return await fn(tier)
        finally:
            await tier.drop()
            await tier.cache.adisconnect()

    return asyncio.run(go())


async def _store(tier: SemanticTier, k: SemanticKey) -> str | None:
    vec = await tier.embed(k.text)
    return await tier.store(k.text, vec, B(k), GOOD_LESSON, cost_usd=0.02, latency_ms=12000)


async def _check(tier: SemanticTier, k: SemanticKey):
    return await tier.check(await tier.embed(k.text), B(k))


def test_paraphrase_hits_inside_its_bucket() -> None:
    async def fn(tier: SemanticTier):
        await _store(tier, key())
        return await _check(tier, key(POOL_REWORDED))

    hit = with_tier(fn)
    assert hit is not None and hit.output == GOOD_LESSON
    assert hit.similarity > 0.99 and hit.prompt == POOL
    assert (hit.entry.cost_usd, hit.entry.latency_ms) == (0.02, 12000)


def test_a_different_concept_beyond_the_threshold_misses() -> None:
    async def fn(tier: SemanticTier):
        await _store(tier, key())
        return await _check(tier, key(THREADS))

    assert with_tier(fn) is None


@pytest.mark.parametrize(
    "other",
    [
        {"org_id": str(uuid.uuid4())},  # another org: never cross-org (ADR-0007)
        {"target_level": "beginner"},
        {"formats": ["reading"]},
        {"analogy_domain": "football"},
        {"doc_set_hash": "abc123"},
    ],
)
def test_identical_text_in_another_bucket_misses(other: dict) -> None:
    async def fn(tier: SemanticTier):
        await _store(tier, key())
        return await _check(tier, key(**other))

    assert with_tier(fn) is None


# --- the wrapper: exact → semantic → model ------------------------------------------------------
def test_wrapper_stores_on_miss_then_serves_a_semantic_hit() -> None:
    fake = FakeAnthropic(message(GOOD_LESSON))

    async def fn(tier: SemanticTier):
        sink = MemorySink()
        llm = LLMClient(
            fake.as_client(), get_registry(), sink, model="claude-sonnet-5-5", semantic=tier
        )

        async def lesson(topic: str, k: SemanticKey) -> Done:
            events = llm.stream(
                "teach-concept",
                "teach",
                teach_in(topic),
                LessonOutput,
                ctx=CallContext(),
                semantic=k,
            )
            return [e async for e in events if isinstance(e, Done)][0]

        first = await lesson("Database connection pooling", key())
        # A different request (so no exact hit is possible) whose meaning is the same.
        second = await lesson("DB connection pools", key(POOL_REWORDED))
        return first, second, sink.records

    first, second, records = with_tier(fn)
    assert first.cache_result == "miss" and second.cache_result == "semantic_hit"
    assert second.output.model_dump() == {**GOOD_LESSON, "citations": [], "not_in_docs": []}
    assert len(fake.requests) == 1  # the second lesson cost no model call
    hit = records[-1]
    assert hit.cache_result == "semantic_hit" and hit.input_tokens == 0
    assert hit.similarity > 0.99 and hit.saved_cost_usd > 0 and hit.cache_key == second.cache_key


def test_never_cached_calls_skip_the_semantic_tier() -> None:
    """The bucket only applies to calls declared `semantic`; a semantic key on another call is
    ignored (no lookup, no store), so a personal call can't leak in by mistake."""
    fake = FakeAnthropic(message({"what_will_break": "x"}), message({"what_will_break": "y"}))

    async def fn(tier: SemanticTier):
        from agent.types import Concept, WarningInput, WarningOutput

        c = Concept(
            id="a",
            title="A",
            mastery_statement="You can a.",
            objective_level="apply",
            prereqs=[],
            est_minutes=10,
            concept_type="systems",
        )
        llm = LLMClient(
            fake.as_client(),
            get_registry(),
            MemorySink(),
            model="claude-sonnet-5-5",
            semantic=tier,
        )
        inp = WarningInput(concept=c, unmet_prereqs=[])
        for _ in range(2):
            await llm.run(
                "remediate", "prereq_warning", inp, WarningOutput, ctx=CallContext(), semantic=key()
            )

    with_tier(fn)
    assert len(fake.requests) == 2  # both went to the model
