"""The LLM client wrapper: structured output, one retry with the errors, every request logged."""

import asyncio
import uuid

import anthropic
import httpx2
import pytest

from agent.llm import (
    CallContext,
    LLMClient,
    LLMError,
    LLMInvalidOutput,
    LLMRefusal,
    estimate_cost_usd,
)
from agent.registry import SkillError, get_registry
from agent.skills.diagnose.schema import (
    AssessInput,
    AssessOutput,
    ProbeInput,
    ProbeOutput,
    ProbeQuestion,
)
from agent.types import CourseConfig, Mission
from tests.llm_fakes import FakeAnthropic, MemorySink, message

PROBE_IN = ProbeInput(
    config=CourseConfig(topic="Redis caching patterns", self_level="intermediate"),
    mission=Mission(goal="Ship a cache layer", expert_means="I can pick an eviction policy"),
)


def question(i: int) -> ProbeQuestion:
    return ProbeQuestion(
        id=f"q{i}",
        prompt=f"Why would a cache-aside read path need step {i}?",
        targets_concept=f"concept {i}",
        level="intermediate",
    )


GOOD_PROBE = ProbeOutput(questions=[question(1), question(2), question(3)])
# Only 2 questions: passes JSON-schema shape, fails ProbeOutput's min_length=3.
SHORT_PROBE = {"questions": [question(1).model_dump(), question(2).model_dump()]}


def make(fake: FakeAnthropic, model: str = "claude-sonnet-5-5") -> tuple[LLMClient, MemorySink]:
    sink = MemorySink()
    return LLMClient(fake.as_client(), get_registry(), sink, model=model), sink


def probe(llm: LLMClient) -> ProbeOutput:
    return asyncio.run(llm.run("diagnose", "probe", PROBE_IN, ProbeOutput, ctx=CallContext()))


def run(fake: FakeAnthropic, *, model: str = "claude-sonnet-5-5"):
    llm, sink = make(fake, model)
    return probe(llm), sink.records


def test_valid_output_first_try() -> None:
    fake = FakeAnthropic(message(GOOD_PROBE))
    result, records = run(fake)

    assert result == GOOD_PROBE
    [req] = fake.requests
    # Structured output: a JSON schema derived from the Pydantic contract (ADR-0013).
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert req["output_config"]["effort"] == "medium"  # from diagnose/SKILL.md
    assert req["max_tokens"] == 8000
    assert "# Task: probe" in req["system"]
    # Server-side refusal fallback is on for models that support it.
    assert req["fallbacks"] == "default"
    assert req["betas"] == ["server-side-fallback-2026-07-01"]

    [rec] = records
    assert rec.status == "ok"
    assert rec.attempt == 1
    assert rec.cache_result == "bypass"  # diagnose is never cached (ADR-0007)
    assert rec.prompt_version.startswith("diagnose@0.2.0+")
    assert (rec.input_tokens, rec.output_tokens) == (1000, 500)
    assert rec.est_cost_usd == pytest.approx(0.007)


def test_invalid_output_is_retried_once_with_the_errors() -> None:
    fake = FakeAnthropic(message(SHORT_PROBE), message(GOOD_PROBE))
    result, records = run(fake)

    assert result == GOOD_PROBE
    assert [r.status for r in records] == ["error", "ok"]
    assert "questions" in (records[0].error or "")

    retry = fake.requests[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    # The model's reply goes back unchanged, thinking block included.
    assert [b.type for b in retry[1]["content"]] == ["thinking", "text"]
    assert "did not pass validation" in retry[2]["content"]  # _shared/retry.md
    assert "- questions:" in retry[2]["content"]


def test_invalid_twice_raises_and_logs_both() -> None:
    fake = FakeAnthropic(message(SHORT_PROBE), message("not json"))
    llm, sink = make(fake)
    with pytest.raises(LLMInvalidOutput):
        probe(llm)
    assert [(r.attempt, r.status) for r in sink.records] == [(1, "error"), (2, "error")]


def test_model_validator_errors_drive_the_retry() -> None:
    """Spec §4.3 lives in AssessOutput's validator; the wrapper makes it enforceable."""
    silent_relevel = {
        "claimed_level": "intermediate",
        "assessed_level": "novice",
        "confidence": 0.8,
        "evidence": [{"question_id": "q1", "observation": "restarts first", "points_to": "novice"}],
        "gaps": ["saturation"],
        "adjustment_message": None,
    }
    explained = {**silent_relevel, "adjustment_message": "You said intermediate, but…"}
    fake = FakeAnthropic(message(silent_relevel), message(explained))
    llm, sink = make(fake)
    payload = AssessInput(
        config=PROBE_IN.config, mission=PROBE_IN.mission, probe=GOOD_PROBE, answers=[]
    )

    result = asyncio.run(llm.run("diagnose", "assess", payload, AssessOutput, ctx=CallContext()))

    assert result.adjustment_message == "You said intermediate, but…"
    assert "adjustment_message is required" in (sink.records[0].error or "")


def test_refusal_is_not_retried() -> None:
    fake = FakeAnthropic(message("", stop_reason="refusal", refusal_category="cyber"))
    llm, sink = make(fake)
    with pytest.raises(LLMRefusal):
        probe(llm)
    assert len(fake.requests) == 1
    assert sink.records[0].error == "refusal (cyber)"


def test_truncated_output_is_not_retried() -> None:
    fake = FakeAnthropic(message('{"questions": [', stop_reason="max_tokens"))
    with pytest.raises(LLMError, match="max_tokens"):
        run(fake)
    assert len(fake.requests) == 1


def test_api_error_is_logged_with_zero_tokens() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    llm, sink = make(FakeAnthropic(anthropic.APIConnectionError(request=request)))
    with pytest.raises(LLMError, match="APIConnectionError"):
        probe(llm)

    [rec] = sink.records
    assert (rec.status, rec.input_tokens, rec.est_cost_usd) == ("error", 0, 0)


def test_no_fallback_param_for_models_without_it() -> None:
    fake = FakeAnthropic(message(GOOD_PROBE, model="claude-haiku-5-5"))
    run(fake, model="claude-haiku-5-5")
    assert fake.requests[0]["fallbacks"] is anthropic.omit


def test_served_by_model_is_logged_after_a_fallback() -> None:
    fake = FakeAnthropic(message(GOOD_PROBE, model="claude-sonnet-5"))
    _, [rec] = run(fake)
    assert rec.model == "claude-sonnet-5"


def test_output_type_must_match_the_registered_contract() -> None:
    llm, _ = make(FakeAnthropic())
    with pytest.raises(SkillError):
        asyncio.run(llm.run("diagnose", "probe", PROBE_IN, AssessOutput, ctx=CallContext()))


def test_estimate_cost() -> None:
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0) == 2.0
    assert estimate_cost_usd("claude-sonnet-5-5", 2_000, 1_000) == pytest.approx(0.014)
    assert estimate_cost_usd("claude-opus-5-5", 1_000, 1_000) == pytest.approx(0.024)
    assert estimate_cost_usd("some-future-model", 1_000, 1_000) == 0.0


ASSESS_IN = AssessInput(
    config=PROBE_IN.config, mission=PROBE_IN.mission, probe=GOOD_PROBE, answers=[]
)


def assessed(**overrides) -> dict:
    out = {
        "claimed_level": "intermediate",
        "assessed_level": "intermediate",
        "confidence": 0.7,
        "evidence": [{"question_id": "q1", "observation": "solid", "points_to": "intermediate"}],
        "gaps": [],
        "adjustment_message": None,
    }
    return {**out, **overrides}


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        # Echoing the wrong claim would let a re-level skip its explanation.
        (assessed(claimed_level="novice", assessed_level="novice"), "claimed_level must be"),
        (
            assessed(evidence=[{"question_id": "q9", "observation": "x", "points_to": "novice"}]),
            "unknown question ids ['q9']",
        ),
    ],
)
def test_assess_output_is_checked_against_its_input(bad: dict, error: str) -> None:
    fake = FakeAnthropic(message(bad), message(assessed()))
    llm, sink = make(fake)

    asyncio.run(llm.run("diagnose", "assess", ASSESS_IN, AssessOutput, ctx=CallContext()))

    assert error in (sink.records[0].error or "")
    assert [r.status for r in sink.records] == ["error", "ok"]


def test_stored_results_validate_without_context() -> None:
    # Reading JSONB back has no input to compare against; only the self-contained rules run.
    AssessOutput.model_validate(assessed(claimed_level="novice", assessed_level="novice"))


# --- streaming + the exact cache (PC2.2) -------------------------------------------------------
from redis.asyncio import Redis  # noqa: E402

from agent.cache import ExactCache  # noqa: E402
from agent.llm import Done, Restart, TextDelta  # noqa: E402
from agent.types import Concept, LessonOutput, TeachInput  # noqa: E402
from app.config import get_settings  # noqa: E402

GOOD_LESSON = {
    "explanation_md": "A pool's max isn't a target, it's a ceiling.",
    "example_md": "Set max=10 and send 50 concurrent requests: 40 wait.",
    "diagram_mermaid": "flowchart LR\n  R[Requests] --> P[Pool max 10] --> D[(DB)]",
}


def teach_in(topic: str = "Database connection pooling") -> TeachInput:
    return TeachInput(
        topic=topic,
        target_level="intermediate",
        analogy_domain="restaurants",
        formats=["quizzes", "reading"],
        concept=Concept(
            id="pool-exhaustion",
            title="Pool exhaustion",
            mastery_statement="You can diagnose a timeout caused by pool exhaustion.",
            objective_level="analyze",
            prereqs=[],
            est_minutes=20,
            concept_type="systems",
        ),
        prereq_titles=[],
    )


async def acollect(llm: LLMClient, payload: TeachInput) -> list:
    events = llm.stream("teach-concept", "teach", payload, LessonOutput, ctx=CallContext())
    return [e async for e in events]


def collect(llm: LLMClient, payload: TeachInput) -> list:
    return asyncio.run(acollect(llm, payload))


def with_cached_llm(fake: FakeAnthropic, fn):
    """Run `fn(llm, sink)` in one event loop, with a real exact cache on the test Redis DB."""

    async def go():
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        sink = MemorySink()
        llm = LLMClient(
            fake.as_client(),
            get_registry(),
            sink,
            model="claude-sonnet-5-5",
            cache=ExactCache(redis),
        )
        try:
            return await fn(llm, sink)
        finally:
            await redis.aclose()

    return asyncio.run(go())


def test_stream_yields_the_json_then_done() -> None:
    llm, sink = make(FakeAnthropic(message(GOOD_LESSON)))
    events = collect(llm, teach_in())
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert len(events) > 3 and isinstance(events[-1], Done)
    assert LessonOutput.model_validate_json(text) == events[-1].output
    assert events[-1].cache_result == "miss"  # cacheable call, no cache configured
    assert [r.status for r in sink.records] == ["ok"]


def test_stream_restarts_after_invalid_output() -> None:
    bad = GOOD_LESSON | {"diagram_mermaid": "```mermaid\nflowchart LR\n  A --> B\n```"}
    fake = FakeAnthropic(message(bad), message(GOOD_LESSON))
    llm, sink = make(fake)
    events = collect(llm, teach_in())
    [restart] = [e for e in events if isinstance(e, Restart)]
    assert "fences" in restart.errors
    assert isinstance(events[-1], Done) and len(fake.requests) == 2
    assert [r.status for r in sink.records] == ["error", "ok"]


def test_cache_miss_stores_then_hit_skips_the_model() -> None:
    fake = FakeAnthropic(message(GOOD_LESSON, input_tokens=2000, output_tokens=1000))
    payload = teach_in(topic=f"pooling {uuid.uuid4().hex}")  # a fresh key

    async def go(llm: LLMClient, sink: MemorySink):
        first = (await acollect(llm, payload))[-1]
        second = await acollect(llm, payload)  # no reply left: a model call would fail
        return first, second, sink.records

    first, second, records = with_cached_llm(fake, go)
    assert first.cache_result == "miss" and first.cache_key.startswith("llm:exact:")
    assert len(second) == 1 and second[0].cache_result == "exact_hit"
    assert second[0].output == first.output and len(fake.requests) == 1
    miss, hit = records
    assert (miss.cache_result, miss.cache_key) == ("miss", first.cache_key)
    assert (hit.cache_result, hit.input_tokens, hit.est_cost_usd) == ("exact_hit", 0, 0.0)
    assert hit.saved_cost_usd == miss.est_cost_usd > 0  # measured, not estimated


def test_never_cached_calls_skip_the_cache() -> None:
    fake = FakeAnthropic(message(GOOD_PROBE), message(GOOD_PROBE))

    async def go(llm: LLMClient, sink: MemorySink):
        for _ in range(2):
            await llm.run("diagnose", "probe", PROBE_IN, ProbeOutput, ctx=CallContext())
        return sink.records

    records = with_cached_llm(fake, go)
    assert len(fake.requests) == 2  # diagnose is never cached (ADR-0007)
    assert {(r.cache_result, r.cache_key) for r in records} == {("bypass", None)}
