"""PC3.2 eval: semantic-cache threshold sweep and intake-guard re-check, on the real MiniLM model.

Run: `make eval-cache` (needs `make up` and `make models`; no API key, no model calls).

Both checks go through the production code paths, not a re-implementation: `SemanticTier` (store
+ bucket-filtered range query) and `IntakeGuard` (RedisVL `SemanticRouter`, min aggregation),
each on a throwaway `test:` index on DB 0 (ADR-0019) that is dropped afterwards. Each index is
built with the widest threshold, so every pair's real distance is recorded once; the sweep then
applies each candidate threshold to those distances (RedisVL's comparisons: cache `<=`, router `<`).

Cache pairs are isolated from each other by a per-pair `doc_set_hash`, so a request can only
match its own stored lesson: the question per pair is "does this one hit?".

Siblings: if the dev DB holds concept maps, every pair of core concepts *within one course* is a
should-miss by construction (map-concepts makes each concept distinct), and a course's concepts
share one bucket, so these are the false hits a real learner would meet: the next lesson in their
own course served from the previous one.
"""

import asyncio
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from redisvl.utils.vectorize import BaseVectorizer, HFTextVectorizer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from agent.guard import THRESHOLD as GUARD_THRESHOLD
from agent.guard import IntakeGuard
from agent.semantic import DEFAULT_DISTANCE_THRESHOLD, MODEL, SemanticKey, SemanticTier, bucket
from agent.types import ConceptMap, CourseConfig
from app.config import get_settings
from app.models import Course

HERE = Path(__file__).parent
DB0 = get_settings().redis_url.rsplit("/", 1)[0] + "/0"
CACHE_SWEEP = [round(0.06 + 0.02 * i, 3) for i in range(13)]  # 0.06 … 0.30
GUARD_SWEEP = [round(0.30 + 0.025 * i, 3) for i in range(9)]  # 0.30 … 0.50
BASE = {
    "org_id": None,
    "target_level": "intermediate",
    "formats": ["reading", "quizzes", "hands_on"],
    "analogy_domain": None,
}


# --- labelled sets ---------------------------------------------------------------------------
class Pair(BaseModel):
    id: str
    label: Literal["hit", "miss"]
    source: Literal["dev-db", "synthetic"]
    stored: str
    request: str
    request_bucket: dict[str, str] = {}
    note: str | None = None


class BlockCase(BaseModel):
    text: str
    known_miss: bool = False


class GuardSet(BaseModel):
    allow: list[str]
    block: list[BlockCase]


def load_pairs() -> list[Pair]:
    raw = yaml.safe_load((HERE / "semantic_cache.yaml").read_text())
    return [Pair.model_validate(p) for p in raw["pairs"]]


def load_guard_set() -> GuardSet:
    return GuardSet.model_validate(yaml.safe_load((HERE / "intake_guard.yaml").read_text()))


# --- semantic cache --------------------------------------------------------------------------
@dataclass
class PairResult:
    pair: Pair
    distance: float | None  # through the bucket filter; None = the bucket excluded it
    text_distance: float  # the two texts' distance, ignoring the bucket

    def hit_at(self, t: float) -> bool:
        return self.distance is not None and self.distance <= t


def _bucket(pair: Pair, overrides: dict[str, str]) -> dict[str, str]:
    key = SemanticKey(text="", doc_set_hash=f"eval-{pair.id}", **(BASE | overrides))  # pyright: ignore[reportArgumentType]
    return bucket("teach-concept", "teach", "eval-model", "eval", key)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine distance, as the index computes it (for pairs the bucket keeps apart)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return 1 - dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def measure_cache(pairs: list[Pair], vectorizer: BaseVectorizer) -> list[PairResult]:
    tier = await asyncio.to_thread(
        SemanticTier.build,
        DB0,
        name=f"test:idx:llm_semantic:eval-{uuid.uuid4().hex[:8]}",
        vectorizer=vectorizer,
        distance_threshold=2.0,
    )
    results = []
    try:
        for p in pairs:
            stored, request = await tier.embed(p.stored), await tier.embed(p.request)
            await tier.store(
                p.stored, stored, _bucket(p, {}), {"eval": p.id}, cost_usd=0, latency_ms=0
            )
            hit = await tier.check(request, _bucket(p, p.request_bucket), distance_threshold=2.0)
            results.append(PairResult(p, hit.distance if hit else None, _cosine(stored, request)))
    finally:
        await tier.drop()
        await tier.cache.adisconnect()
    return results


def _t(t: float) -> str:
    return f"{t:.2f} (default)" if t == DEFAULT_DISTANCE_THRESHOLD else f"{t:.2f}"


def report_cache(results: list[PairResult]) -> None:
    hits = [r for r in results if r.pair.label == "hit"]
    misses = [r for r in results if r.pair.label == "miss"]
    print(f"\n## Semantic cache: {len(hits)} should-hit, {len(misses)} should-miss pairs\n")
    print("| distance | label | pair | note |\n|---|---|---|---|")
    for r in sorted(results, key=lambda r: r.text_distance):
        d = f"{r.distance:.3f}" if r.distance is not None else f"({r.text_distance:.3f}) bucket"
        print(f"| {d} | {r.pair.label} | {r.pair.id} | {r.pair.note or ''} |")

    print("\n| threshold | hit rate (should-hit served) | false-hit rate (should-miss served) |")
    print("|---|---|---|")
    for t in CACHE_SWEEP:
        h = sum(r.hit_at(t) for r in hits)
        f = sum(r.hit_at(t) for r in misses)
        hit_rate, false_rate = h / len(hits), f / len(misses)
        print(
            f"| {_t(t)} | {h}/{len(hits)} ({hit_rate:.0%}) | {f}/{len(misses)} ({false_rate:.0%}) |"
        )

    closest_miss = min(r.distance for r in misses if r.distance is not None)
    print(f"\nClosest should-miss through the bucket: {closest_miss:.3f}. Every threshold below it")
    print("serves no wrong lesson on this set; the margin below it is the safety buffer.")


@dataclass
class Sibling:
    distance: float
    course: str
    a: str
    b: str


async def measure_siblings(vectorizer: BaseVectorizer) -> list[Sibling]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(select(Course.config, Course.template_plan))).all()
    finally:
        await engine.dispose()
    out = []
    for config, plan in rows:
        if not plan:
            continue
        topic = CourseConfig.model_validate(config).topic
        concepts = [c for c in ConceptMap.model_validate(plan).concepts if not c.is_remediation]
        texts = [f"{topic}\n{c.title}\n{c.mastery_statement}" for c in concepts]  # semantic_key()
        vecs = await asyncio.to_thread(vectorizer.embed_many, texts)
        for i in range(len(concepts)):
            for j in range(i + 1, len(concepts)):
                d = _cosine(vecs[i], vecs[j])  # pyright: ignore[reportArgumentType]
                out.append(Sibling(d, topic, concepts[i].title, concepts[j].title))
    return sorted(out, key=lambda s: s.distance)


def report_siblings(sibs: list[Sibling]) -> None:
    if not sibs:
        print("\n(No concept maps in the dev DB: sibling check skipped.)")
        return
    courses = len({s.course for s in sibs})
    print(f"\n## Sibling concepts (dev DB): {len(sibs)} should-miss pairs from {courses} courses\n")
    print("Closest five:\n\n| distance | course | concepts |\n|---|---|---|")
    for s in sibs[:5]:
        print(f"| {s.distance:.3f} | {s.course} | {s.a} / {s.b} |")
    print("\n| threshold | sibling false hits |\n|---|---|")
    for t in CACHE_SWEEP:
        print(f"| {_t(t)} | {sum(s.distance <= t for s in sibs)}/{len(sibs)} |")


# --- intake guard ----------------------------------------------------------------------------
async def measure_guard(gs: GuardSet, vectorizer: BaseVectorizer) -> dict[str, tuple[str, float]]:
    guard = await asyncio.to_thread(
        IntakeGuard.build,
        DB0,
        vectorizer,
        name=f"test:idx:intake_guard:eval-{uuid.uuid4().hex[:8]}",
        threshold=2.0,
    )
    out = {}
    try:
        for text in [*gs.allow, *(b.text for b in gs.block)]:
            match = await asyncio.to_thread(guard.router, text)
            assert match.name is not None and match.distance is not None
            out[text] = (match.name, match.distance)
    finally:
        await asyncio.to_thread(guard.router.delete)
    return out


def report_guard(gs: GuardSet, nearest: dict[str, tuple[str, float]]) -> None:
    must_block = [b.text for b in gs.block if not b.known_miss]
    print(f"\n## Intake guard: {len(gs.allow)} allow, {len(gs.block)} block ")
    print(f"({len(gs.block) - len(must_block)} of them known misses, ADR-0024)\n")
    print("| distance | nearest route | label | text |\n|---|---|---|---|")
    labels = {t: "allow" for t in gs.allow} | {
        b.text: "block (known miss)" if b.known_miss else "block" for b in gs.block
    }
    for text, (route, d) in sorted(nearest.items(), key=lambda kv: kv[1][1]):
        print(f"| {d:.3f} | {route} | {labels[text]} | {text} |")

    print("\n| threshold | blocked (of must-block) | legitimate blocked |\n|---|---|---|")
    for t in GUARD_SWEEP:
        caught = sum(nearest[x][1] < t for x in must_block)
        wrong = sum(nearest[x][1] < t for x in gs.allow)
        mark = " (current)" if t == GUARD_THRESHOLD else ""
        print(f"| {t:.3f}{mark} | {caught}/{len(must_block)} | {wrong}/{len(gs.allow)} |")


async def main() -> None:
    vectorizer = await asyncio.to_thread(HFTextVectorizer, model=MODEL)
    pairs, gs = load_pairs(), load_guard_set()
    report_cache(await measure_cache(pairs, vectorizer))
    report_siblings(await measure_siblings(vectorizer))
    report_guard(gs, await measure_guard(gs, vectorizer))


if __name__ == "__main__":
    asyncio.run(main())
