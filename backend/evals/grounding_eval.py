"""PC4.2 check: grounded lessons against the seeded Acme AI docs, on the live model.

Run: `make eval-grounding` (needs ANTHROPIC_API_KEY; 2 lessons and a template map, ~$0.15).
No DB, no cache: every run generates fresh, through the production wrapper (`LLMClient` with a
`Grounding`), so the deterministic checks (real sections, verbatim quotes, markers) have
already passed, with at most one retry, by the time a lesson is printed. What's left to eyeball,
and what CP5's LLM judge will score, are the case assertions printed under each lesson.

Cases live with the skill: `agent/skills/ground-in-sources/evals/cases.yaml`.
"""

import asyncio
import time
from pathlib import Path
from typing import Any

import yaml
from anthropic import AsyncAnthropic

from agent import sources
from agent.llm import CallContext, CallRecord, LLMClient
from agent.registry import get_registry
from agent.types import LessonOutput, MapInput, MapOutput, TeachInput
from app.config import get_settings
from seed.seed import load_org_docs

CASES = Path(__file__).parents[1] / "agent/skills/ground-in-sources/evals/cases.yaml"


class PrintSink:
    """Every request, one line: the retry (if any) is visible, with its reason."""

    async def record(self, rec: CallRecord) -> None:
        status = rec.status if rec.error is None else f"error: {rec.error.splitlines()[-1]}"
        print(
            f"    attempt {rec.attempt}: {rec.input_tokens} in / {rec.output_tokens} out, "
            f"{rec.latency_ms / 1000:.1f} s, ${rec.est_cost_usd:.4f}, {status}"
        )


def grounding_for(refs: list[str]) -> sources.Grounding:
    wanted = {tuple(r.split("/", 1)) for r in refs}  # "acme/on-call-runbook"
    docs = [
        sources.SourceDoc(str(v["slug"]), str(v["title"]), str(v["content_md"]))
        for org, v in load_org_docs()
        if (org, v["slug"]) in wanted
    ]
    assert len(docs) == len(wanted), f"unknown docs in {refs}"
    return sources.compose("eval-org", docs)


def show(lesson: LessonOutput, case: dict[str, Any]) -> None:
    print("\n  explanation (first 600 chars):")
    print("    " + lesson.explanation_md[:600].replace("\n", "\n    "))
    print(f"\n  citations ({len(lesson.citations)}):")
    for n, c in enumerate(lesson.citations, start=1):
        print(f"    [{n}] {c.doc} › {c.section}: “{c.quote}”")
    print(f"\n  not in your docs ({len(lesson.not_in_docs)}):")
    for gap in lesson.not_in_docs:
        print(f"    - {gap.point}" + (" (+ general knowledge)" if gap.general_knowledge else ""))
    print("\n  check by eye (CP5's judge scores these):")
    for a in case["assert"]:
        print(f"    · {a}")


def show_map(cmap: MapOutput, case: dict[str, Any]) -> None:
    by_id = {c.id: c for c in cmap.concepts}
    print(f"\n  {len(cmap.concepts)} concepts, {cmap.total_minutes()} min:")
    for n, cid in enumerate(cmap.sequence, start=1):
        c = by_id[cid]
        needs = f"  needs: {', '.join(c.prereqs)}" if c.prereqs else ""
        print(f"    {n:>2}. {c.title} ({c.est_minutes} min){needs}")
        print(f"        {c.mastery_statement}")
    print(f"\n  rationale: {cmap.sequence_rationale}")
    print("\n  check by eye (CP5's judge scores these):")
    for a in case["assert"]:
        print(f"    · {a}")


async def main() -> None:
    settings = get_settings()
    key = settings.anthropic_api_key
    if key is None or not key.get_secret_value():
        raise SystemExit("ANTHROPIC_API_KEY is not set (see .env.example)")
    client = AsyncAnthropic(
        api_key=key.get_secret_value(), timeout=settings.anthropic_timeout_seconds
    )
    llm = LLMClient(client, get_registry(), PrintSink(), model=settings.anthropic_model)
    suite = yaml.safe_load(CASES.read_text())
    try:
        for case in suite["grounded_teach"]:
            grounding = grounding_for(case["docs"])
            print(
                f"\n=== {case['id']} ({len(grounding.text):,} chars of docs, "
                f"doc set {grounding.doc_set_hash[:12]})"
            )
            started = time.perf_counter()
            lesson = await llm.run(
                "teach-concept",
                "teach",
                TeachInput.model_validate(case["input"]),
                LessonOutput,
                ctx=CallContext(),
                grounding=grounding,
            )
            print(f"  valid after {time.perf_counter() - started:.1f} s")
            show(lesson, case)
        for case in suite["grounded_map"]:
            grounding = grounding_for(case["docs"])
            print(f"\n=== {case['id']} (template map, doc set {grounding.doc_set_hash[:12]})")
            started = time.perf_counter()
            cmap = await llm.run(
                "map-concepts",
                "map",
                MapInput.model_validate(case["input"]),
                MapOutput,
                ctx=CallContext(),
                grounding=grounding,
            )
            print(f"  valid after {time.perf_counter() - started:.1f} s")
            show_map(cmap, case)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
