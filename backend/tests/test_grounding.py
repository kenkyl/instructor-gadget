"""Grounded generation (PC4.2, ADR-0029): docs composed into the prompt, citations checked
against them by code, and the doc set in every cache key."""

import asyncio
import dataclasses
import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from agent import sources
from agent.cache import exact_key
from agent.llm import CallContext, LLMClient
from agent.registry import SkillError, get_registry
from agent.semantic import SemanticKey
from agent.sources import Grounding, SourceDoc
from agent.types import Concept, LessonOutput, QuizOutput, TeachInput
from app.config import get_settings
from app.models import Course, CourseScope, CourseStatus, Org, OrgDoc
from app.services.org_docs import course_grounding
from tests.llm_fakes import FakeAnthropic, MemorySink, message
from tests.test_quiz_types import base_input
from tests.test_quiz_types import quiz as base_quiz

RUNBOOK = """# On-call runbook

Who does what when a page fires.

## Paging

The primary acknowledges within **5 minutes**. If not, the page goes to the secondary.

### Severity

| Level | Meaning |
|---|---|
| SEV1 | Customers can't use inference |
"""
SHIP = """# How we ship

## Rollback

Roll back first, debug second: `deploy rollback` takes about 2 minutes.
"""
DOCS = [
    SourceDoc("on-call-runbook", 'On-call "runbook"', RUNBOOK),
    SourceDoc("how-we-ship", "How we ship", SHIP),
]
ORG = str(uuid.uuid4())
GROUNDING = sources.compose(ORG, DOCS)


# --- composing the docs ------------------------------------------------------------------------
def test_sections_run_to_the_next_heading_of_any_level() -> None:
    preamble, parts = sources.split_sections(
        "Intro line.\n\n# T\n\nlead\n\n## A\n\na\n\n### B\n\nb\n"
    )
    assert preamble == "Intro line."
    assert [(s.anchor, text) for s, text in parts] == [
        ("t", "# T\n\nlead"),
        ("a", "## A\n\na"),  # its subsection's text isn't in it
        ("b", "### B\n\nb"),
    ]


def test_compose_is_order_independent_and_hashes_what_it_rendered() -> None:
    again = sources.compose(ORG, reversed(DOCS))
    assert again.text == GROUNDING.text  # same set → same bytes, whatever the order
    assert GROUNDING.text.index('slug="how-we-ship"') < GROUNDING.text.index(
        'slug="on-call-runbook"'
    )
    # The same hash a course pins at creation, computed from the rendered docs' content.
    pinned = sources.doc_set_hash((d.slug, sources.content_hash(d.content_md)) for d in DOCS)
    assert GROUNDING.doc_set_hash == pinned
    assert sources.compose(ORG, DOCS[:1]).doc_set_hash != pinned
    edited = [DOCS[0], dataclasses.replace(DOCS[1], content_md=SHIP.replace("2", "3"))]
    assert sources.compose(ORG, edited).doc_set_hash != pinned


def test_every_section_is_tagged_with_its_anchor() -> None:
    assert '<section anchor="paging">\n## Paging\n' in GROUNDING.text
    assert 'title="On-call &quot;runbook&quot;"' in GROUNDING.text  # attributes are escaped
    assert set(GROUNDING.sections["on-call-runbook"]) == {"on-call-runbook", "paging", "severity"}
    assert GROUNDING.section_text("how-we-ship", "nope") is None


def test_the_seeded_docs_compose_within_budget() -> None:
    from seed.seed import load_org_docs

    docs = [
        SourceDoc(str(v["slug"]), str(v["title"]), str(v["content_md"])) for _, v in load_org_docs()
    ]
    g = sources.compose(ORG, docs)
    assert len(g.text) < sources.MAX_SET_CHARS * 1.1  # tags add a little
    text = g.section_text("postmortem-pool-exhaustion", "how-the-pool-failed")
    assert text and sources.quote_in(
        "Each model-router pod has a pool of 10 database connections", text
    )


# --- quotes and markers ------------------------------------------------------------------------
@pytest.mark.parametrize(
    "quote",
    [
        "The primary acknowledges within 5 minutes.",  # bold dropped
        "the PRIMARY acknowledges   within 5 minutes",  # case and spacing
        "SEV1 Customers can't use inference",  # table cells
        "SEV1 | Customers can’t use inference",  # curly apostrophe
    ],
)
def test_a_quote_matches_the_words_not_the_typesetting(quote: str) -> None:
    assert sources.quote_in(
        quote,
        GROUNDING.sections["on-call-runbook"][
            ("paging" if "primary" in quote.lower() else "severity")
        ],
    )


def test_a_quote_must_really_be_there() -> None:
    paging = GROUNDING.sections["on-call-runbook"]["paging"]
    assert not sources.quote_in("The primary acknowledges within 10 minutes", paging)
    assert not sources.quote_in("5 min", paging)  # too short to mean anything


def test_markers_skip_code_and_links() -> None:
    md = "Pools cap work [1], and [2].\n\n```py\nrows[1]\n```\n\nSee `a[3]` and [4](http://x)."
    assert sources.citation_markers(md) == [1, 2]


# --- the output contracts (validation context, ADR-0015) ----------------------------------------
def cite(doc: str, section: str, quote: str) -> dict[str, str]:
    return {"doc": doc, "section": section, "quote": quote}


LESSON: dict[str, Any] = {
    "explanation_md": "Acknowledge a page within 5 minutes [1]. After a bad deploy, roll back [2].",
    "example_md": "A page fires at 03:00; you acknowledge at 03:02 [1].",
    "diagram_mermaid": "flowchart LR\n  P[Page] --> A[Ack]",
    "citations": [
        cite("on-call-runbook", "paging", "The primary acknowledges within 5 minutes."),
        cite("how-we-ship", "rollback", "Roll back first, debug second"),
    ],
    "not_in_docs": [{"point": "Who pays for on-call", "general_knowledge": None}],
}
TEACH_IN = TeachInput(
    topic="Technical readiness at Acme AI",
    target_level="intermediate",
    analogy_domain=None,
    formats=["quizzes", "reading"],
    concept=Concept(
        id="paging",
        title="Paging",
        mastery_statement="You can acknowledge and escalate a page.",
        objective_level="apply",
        prereqs=[],
        est_minutes=20,
        concept_type="conceptual",
    ),
    prereq_titles=[],
)


def validate(output: dict[str, Any], grounding: Grounding | None) -> LessonOutput:
    return LessonOutput.model_validate(output, context={"input": TEACH_IN, "grounding": grounding})


def test_a_grounded_lesson_with_real_citations_is_valid() -> None:
    lesson = validate(LESSON, GROUNDING)
    assert [c.section for c in lesson.citations] == ["paging", "rollback"]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (
            {
                "citations": [
                    cite("on-call-runbook", "escalation", "x" * 10),
                    LESSON["citations"][1],
                ]
            },
            "isn't a section",
        ),
        (
            {
                "citations": [
                    cite("on-call-runbook", "paging", "within 10 minutes"),
                    LESSON["citations"][1],
                ]
            },
            "quote isn't in",
        ),
        (
            {
                "citations": [
                    cite("how-we-ship", "paging", "The primary acknowledges"),
                    LESSON["citations"][1],
                ]
            },
            "isn't a section",
        ),
        ({"example_md": "Then [3]."}, "markers [3] have no citation"),
        (
            {"citations": [*LESSON["citations"], LESSON["citations"][0]]},
            "citations [3] are never referenced",
        ),
        (
            {"citations": [], "not_in_docs": [], "explanation_md": "x", "example_md": "y"},
            "cites the source documents",
        ),
    ],
)
def test_a_grounded_lesson_is_held_to_its_docs(change: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error.replace("[", r"\[").replace("]", r"\]")):
        validate(LESSON | change, GROUNDING)


def test_an_ungrounded_lesson_cites_nothing_but_stored_ones_load() -> None:
    with pytest.raises(ValidationError, match="must be empty"):
        validate(LESSON, None)
    assert LessonOutput.model_validate(LESSON).citations  # read back from JSONB: no context


def quiz(**sources_by_item: dict[str, str] | None) -> dict[str, Any]:
    q = base_quiz()
    for item in q["questions"]:
        item["source"] = sources_by_item.get(item["id"])
    q["explain_item"]["source"] = sources_by_item.get("explain")
    return q


QUIZ_IN = base_input()


def validate_quiz(q: dict[str, Any], grounding: Grounding | None) -> QuizOutput:
    return QuizOutput.model_validate(q, context={"input": QUIZ_IN, "grounding": grounding})


def test_a_grounded_quiz_cites_where_its_answers_come_from() -> None:
    ok = quiz(q1=cite("on-call-runbook", "paging", "the page goes to the secondary"))
    assert validate_quiz(ok, GROUNDING).questions[0].source is not None
    with pytest.raises(ValidationError, match="at least one question must test the docs"):
        validate_quiz(quiz(), GROUNDING)
    with pytest.raises(ValidationError, match="q2's quote isn't in"):
        validate_quiz(
            ok
            | quiz(
                q1=ok["questions"][0]["source"],
                q2=cite("how-we-ship", "rollback", "takes 10 minutes"),
            ),
            GROUNDING,
        )
    with pytest.raises(ValidationError, match="must be null"):
        validate_quiz(ok, None)


# --- the wrapper -------------------------------------------------------------------------------
class FakeTier:
    """Records the bucket a lookup and a store used; never hits."""

    def __init__(self) -> None:
        self.buckets: list[dict[str, str]] = []

    async def embed(self, text: str) -> list[float]:
        return [0.0]

    async def check(self, vector: list[float], b: dict[str, str]) -> None:
        self.buckets.append(b)

    async def store(self, text, vector, b, output, **kw) -> None:  # noqa: ANN001, ANN003
        self.buckets.append(b)


def grounded_llm(*replies: Any) -> tuple[LLMClient, FakeAnthropic, MemorySink, FakeTier]:
    fake = FakeAnthropic(*(message(r) for r in replies))
    tier = FakeTier()
    sink = MemorySink()
    llm = LLMClient(
        fake.as_client(),
        get_registry(),
        sink,
        model="claude-sonnet-5-5",
        semantic=tier,  # type: ignore[arg-type]
    )
    return llm, fake, sink, tier


def key(org: str | None) -> SemanticKey:
    return SemanticKey(
        text="t",
        org_id=org,
        target_level="intermediate",
        formats=[],
        analogy_domain=None,
        doc_set_hash=None,
    )


def teach(
    llm: LLMClient, *, semantic: SemanticKey | None = None, grounding: Grounding | None = GROUNDING
):
    return asyncio.run(
        llm.run(
            "teach-concept",
            "teach",
            TEACH_IN,
            LessonOutput,
            ctx=CallContext(),
            semantic=semantic,
            grounding=grounding,
        )
    )


def test_a_grounded_call_sends_the_docs_first_and_the_rules_last() -> None:
    llm, fake, sink, _ = grounded_llm(LESSON)
    teach(llm)
    system = fake.requests[0]["system"]
    assert system.startswith("# Source documents\n\n<documents>")
    assert system.index("# Task: teach") < system.index("# Grounding rules")
    assert "This isn't covered in your docs" in system
    grounded = get_registry().prompt_version("teach-concept", "teach", grounded=True)
    assert (
        sink.records[0].prompt_version
        == grounded
        != get_registry().prompt_version("teach-concept", "teach")
    )


def test_a_bad_citation_earns_the_one_retry_with_the_reason() -> None:
    bad = LESSON | {
        "citations": [cite("on-call-runbook", "paging", "within an hour"), LESSON["citations"][1]]
    }
    llm, fake, sink, _ = grounded_llm(bad, LESSON)
    assert teach(llm).citations[0].quote.startswith("The primary")
    retry = fake.requests[1]["messages"][-1]["content"]
    assert "quote isn't in on-call-runbook#paging" in retry
    assert [r.status for r in sink.records] == ["error", "ok"]


def test_the_doc_set_keys_both_cache_tiers() -> None:
    v = get_registry().prompt_version("teach-concept", "teach", grounded=True)
    k = lambda g: exact_key("teach-concept", "teach", "m", v, TEACH_IN, doc_set_hash=g)  # noqa: E731
    other = sources.compose(ORG, DOCS[:1]).doc_set_hash
    assert len({k(None), k(GROUNDING.doc_set_hash), k(other)}) == 3
    # Ungrounded keys are unchanged by the new parameter.
    assert k(None) == exact_key("teach-concept", "teach", "m", v, TEACH_IN)

    # The bucket's doc set comes from the docs in the prompt, whatever the service passed.
    llm, _, _, tier = grounded_llm(LESSON)
    stale = dataclasses.replace(key(ORG), doc_set_hash="stale-hash-from-the-course-row")
    teach(llm, semantic=stale)
    assert {b["doc_set_hash"] for b in tier.buckets} == {GROUNDING.doc_set_hash}
    assert {b["org_id"] for b in tier.buckets} == {ORG}


@pytest.mark.parametrize("org", [None, str(uuid.uuid4())])
def test_a_grounded_lesson_cant_be_filed_under_another_org(org: str | None) -> None:
    llm, fake, _, _ = grounded_llm(LESSON)
    with pytest.raises(SkillError, match="grounding's org"):
        teach(llm, semantic=key(org))
    assert fake.requests == []  # refused before any model call


# --- the service: a course's docs, as the model will see them ------------------------------------
def test_course_grounding_composes_the_pinned_docs() -> None:
    async def go() -> tuple[Grounding | None, Grounding | None, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                org = await db.scalar(select(Org).where(Org.slug == "acme"))
                assert org is not None
                docs = list(
                    await db.scalars(
                        select(OrgDoc).where(
                            OrgDoc.org_id == org.id, OrgDoc.slug.in_(["service-map", "how-we-ship"])
                        )
                    )
                )
                pinned = sources.doc_set_hash((d.slug, d.content_hash) for d in docs)
                course = Course(
                    scope=CourseScope.org,
                    org_id=org.id,
                    title="t",
                    config={},
                    mission={},
                    status=CourseStatus.draft,
                    doc_ids=[str(d.id) for d in docs],
                    doc_set_hash=pinned,
                )
                personal = Course(
                    scope=CourseScope.personal,
                    title="t",
                    config={},
                    mission={},
                    status=CourseStatus.draft,
                )
                return (
                    await course_grounding(db, course),
                    await course_grounding(db, personal),
                    pinned,
                )
        finally:
            await engine.dispose()

    grounding, none, pinned = asyncio.run(go())
    assert none is None and grounding is not None
    assert grounding.doc_set_hash == pinned  # recomputed, and equal while the docs are unchanged
    assert set(grounding.sections) == {"service-map", "how-we-ship"}
