"""The learning loop (J2), starting with lessons: open a concept → stream its lesson → store it.

Surface-neutral: the web router turns `LessonEvent`s into SSE; an MCP surface could return the
final lesson only. Ownership and the unlock gate are checked here, for every surface.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.llm import CallContext, Done, LLMClient, Restart, TextDelta
from agent.partial import FieldDeltas
from agent.semantic import SemanticKey
from agent.sources import Grounding
from agent.types import (
    Band,
    ConceptMap,
    CourseConfig,
    LessonOutput,
    Mission,
    RemediationLessonInput,
    TeachInput,
)
from app.auth import CurrentUser
from app.models import (
    CacheResult,
    ConceptProgress,
    ConceptStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    Lesson,
    LessonKind,
    PlanVersion,
    PrereqOverride,
)
from app.services.dashboard import invalidate_dashboard
from app.services.org_docs import course_grounding
from app.services.prototypes import PrototypeView, prototype_for, prototype_view

# The LessonOutput string fields streamed to the learner, in the order the model writes them.
STREAMED_FIELDS = ("explanation_md", "example_md", "diagram_mermaid")


class ProgressView(BaseModel):
    concept_id: str
    kind: LessonKind  # remediation concepts are inserted by the adapt rules (PC2.5)
    status: ConceptStatus
    mastery: float | None
    band: Band | None
    last_score: int | None
    attempts: int
    due: datetime | None
    has_lesson: bool
    test_out: bool  # the learner chose to skip the lesson and go straight to the quiz
    overridden: bool  # opened past the prerequisite gate (PC2.6)


class EnrollmentDetail(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    status: EnrollmentStatus
    completed_at: datetime | None
    plan_version: int
    concept_map: ConceptMap
    progress: list[ProgressView]  # in the plan's sequence order


class LessonView(BaseModel):
    concept_id: str
    kind: LessonKind
    content: LessonOutput
    cache_result: CacheResult
    prototype: PrototypeView | None = None


# --- events the lesson stream yields (the router maps them to SSE) ----------------------------
class FieldDeltaEvent(BaseModel):
    field: str
    text: str
    replace: bool = False


class RestartEvent(BaseModel):
    """The first draft failed validation; clear what was shown, a retry is streaming."""


class DoneEvent(BaseModel):
    lesson: LessonView


type LessonEvent = FieldDeltaEvent | RestartEvent | DoneEvent


@dataclass(frozen=True)
class LessonJob:
    """Everything needed to generate and store a lesson, read up front so no DB connection is
    held during the ~20 s of streaming."""

    user_id: uuid.UUID
    course_id: uuid.UUID
    enrollment_id: uuid.UUID
    concept_id: str
    plan_version: int
    kind: LessonKind
    # core: teach-concept.teach (shareable, cached); remediation: remediate.lesson (never cached)
    payload: TeachInput | RemediationLessonInput
    prototype_id: uuid.UUID | None
    semantic: SemanticKey | None = None  # core lessons only; remediation is never cached
    grounding: Grounding | None = None  # org courses: the docs every lesson is taught from


async def get_owned_enrollment(
    db: AsyncSession, user: CurrentUser, enrollment_id: uuid.UUID
) -> Enrollment:
    enrollment = await db.get(Enrollment, enrollment_id)
    # 404, not 403: don't confirm that someone else's enrollment exists.
    if enrollment is None or enrollment.user_id != user.id:
        raise HTTPException(404, "enrollment not found")
    return enrollment


async def current_plan(db: AsyncSession, enrollment: Enrollment) -> ConceptMap:
    plan = await db.scalar(
        select(PlanVersion.plan).where(
            PlanVersion.enrollment_id == enrollment.id,
            PlanVersion.version == enrollment.current_plan_version,
        )
    )
    if plan is None:
        raise HTTPException(500, "enrollment has no current plan")
    return ConceptMap.model_validate(plan)  # JSONB: validate on the way out


async def progress_rows(db: AsyncSession, enrollment_id: uuid.UUID) -> dict[str, ConceptProgress]:
    rows = await db.scalars(
        select(ConceptProgress).where(ConceptProgress.enrollment_id == enrollment_id)
    )
    return {p.concept_id: p for p in rows}


async def overridden_concepts(db: AsyncSession, enrollment_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(
        select(PrereqOverride.concept_id).where(PrereqOverride.enrollment_id == enrollment_id)
    )
    return set(rows)


async def lessoned_concepts(db: AsyncSession, enrollment_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(select(Lesson.concept_id).where(Lesson.enrollment_id == enrollment_id))
    return set(rows)


async def enrollment_detail(db: AsyncSession, enrollment: Enrollment) -> EnrollmentDetail:
    course = await db.get(Course, enrollment.course_id)
    assert course is not None
    cmap = await current_plan(db, enrollment)
    rows = await progress_rows(db, enrollment.id)
    lessoned = await lessoned_concepts(db, enrollment.id)
    overridden = await overridden_concepts(db, enrollment.id)
    concepts = {c.id: c for c in cmap.concepts}
    return EnrollmentDetail(
        id=enrollment.id,
        course_id=course.id,
        title=course.title,
        status=enrollment.status,
        completed_at=enrollment.completed_at,
        plan_version=enrollment.current_plan_version,
        concept_map=cmap,
        progress=[
            ProgressView(
                concept_id=cid,
                kind=LessonKind.remediation if concepts[cid].is_remediation else LessonKind.core,
                status=rows[cid].status,
                mastery=rows[cid].mastery,
                band=rows[cid].band,
                last_score=rows[cid].last_score,
                attempts=rows[cid].attempts,
                due=rows[cid].due,
                has_lesson=cid in lessoned,
                test_out=cid in cmap.test_out,
                overridden=cid in overridden,
            )
            for cid in cmap.sequence
            if cid in rows
        ],
    )


async def latest_lesson(
    db: AsyncSession, enrollment_id: uuid.UUID, concept_id: str
) -> LessonView | None:
    lesson = await db.scalar(
        select(Lesson)
        .where(Lesson.enrollment_id == enrollment_id, Lesson.concept_id == concept_id)
        .order_by(Lesson.created_at.desc())
        .limit(1)
    )
    if lesson is None:
        return None
    return LessonView(
        concept_id=lesson.concept_id,
        kind=lesson.kind,
        content=LessonOutput.model_validate(lesson.content),
        cache_result=lesson.cache_result,
        prototype=await prototype_view(db, lesson.prototype_id),
    )


async def prepare_lesson(
    db: AsyncSession, user: CurrentUser, enrollment_id: uuid.UUID, concept_id: str
) -> LessonView | LessonJob:
    """The stored lesson if there is one (reopening never regenerates), else a job to generate
    it. Raises 404 for an unknown concept and 409 for a locked one (the gate, spec §4.8)."""
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    cmap = await current_plan(db, enrollment)
    concepts = {c.id: c for c in cmap.concepts}
    concept = concepts.get(concept_id)
    if concept is None:
        raise HTTPException(404, "concept not in your plan")
    progress = await db.get(ConceptProgress, (enrollment.id, concept_id))
    if progress is None or progress.status == ConceptStatus.locked:
        # The learner can open it anyway after a specific warning: POST …/override (PC2.6).
        raise HTTPException(409, "This concept is locked until its prerequisites are solid.")

    existing = await latest_lesson(db, enrollment.id, concept_id)
    if existing is not None:
        return existing

    course = await db.get(Course, enrollment.course_id)
    assert course is not None
    config = CourseConfig.model_validate(course.config)
    analogy = Mission.model_validate(course.mission).analogy_domain
    if concept.remedy is not None:
        original = concepts.get(concept.remedy.for_concept)
        first = await latest_lesson(db, enrollment.id, concept.remedy.for_concept)
        payload: TeachInput | RemediationLessonInput = RemediationLessonInput(
            topic=config.topic,
            target_level=config.target_level,
            analogy_domain=analogy,
            concept=concept,
            original_concept_title=original.title if original else concept.remedy.for_concept,
            original_explanation=first.content.explanation_md if first else None,
        )
        kind = LessonKind.remediation
    else:
        payload = TeachInput(
            topic=config.topic,
            target_level=config.target_level,
            analogy_domain=analogy,
            formats=sorted(config.formats),
            concept=concept,
            prereq_titles=[concepts[p].title for p in concept.prereqs if p in concepts],
        )
        kind = LessonKind.core
    semantic = semantic_key(payload, course.org_id) if isinstance(payload, TeachInput) else None
    return LessonJob(
        user_id=user.id,
        course_id=course.id,
        enrollment_id=enrollment.id,
        concept_id=concept_id,
        plan_version=enrollment.current_plan_version,
        kind=kind,
        payload=payload,
        prototype_id=await prototype_for(db, concept, config.formats),
        semantic=semantic,
        grounding=await course_grounding(db, course),
    )


def semantic_key(payload: TeachInput, org_id: uuid.UUID | None) -> SemanticKey:
    """The lesson's semantic-cache key (ADR-0007, data-model §6.4).

    Embedded: the topic, then the concept's title and mastery statement. The topic is there
    because a concept title alone is ambiguous across courses ("Pool exhaustion" in a database
    course vs a thread-pool course). Everything that must match exactly goes in the bucket.
    The doc-set hash is left to the LLM wrapper, which takes it from the docs actually in the
    prompt (ADR-0029).
    """
    c = payload.concept
    return SemanticKey(
        text=f"{payload.topic}\n{c.title}\n{c.mastery_statement}",
        org_id=str(org_id) if org_id else None,
        target_level=payload.target_level,
        formats=payload.formats,
        analogy_domain=payload.analogy_domain,
        doc_set_hash=None,
    )


async def stream_lesson(
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    llm: LLMClient,
    job: LessonJob,
) -> AsyncIterator[LessonEvent]:
    """Generate the lesson, yielding field deltas as the model writes, then store it."""
    deltas = FieldDeltas(STREAMED_FIELDS)
    ctx = CallContext(user_id=job.user_id, course_id=job.course_id, enrollment_id=job.enrollment_id)
    if isinstance(job.payload, TeachInput):
        events = llm.stream(
            "teach-concept",
            "teach",
            job.payload,
            LessonOutput,
            ctx=ctx,
            semantic=job.semantic,
            grounding=job.grounding,
        )
    else:
        events = llm.stream(
            "remediate", "lesson", job.payload, LessonOutput, ctx=ctx, grounding=job.grounding
        )
    async for event in events:
        match event:
            case TextDelta(text=text):
                for d in deltas.feed(text):
                    yield FieldDeltaEvent(field=d.field, text=d.text, replace=d.replace)
            case Restart():
                deltas.reset()
                yield RestartEvent()
            case Done(output=output, cache_result=cache_result, cache_key=cache_key):
                view = await _store_lesson(
                    sessionmaker, redis, job, output, CacheResult(cache_result), cache_key
                )
                yield DoneEvent(lesson=view)


async def _store_lesson(
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
    job: LessonJob,
    output: LessonOutput,
    cache_result: CacheResult,
    cache_key: str | None,
) -> LessonView:
    async with sessionmaker() as db:
        # Two tabs opening the same concept both generate; the first one stored wins, so the
        # learner always sees one lesson per concept.
        existing = await latest_lesson(db, job.enrollment_id, job.concept_id)
        if existing is not None:
            return existing
        db.add(
            Lesson(
                enrollment_id=job.enrollment_id,
                concept_id=job.concept_id,
                plan_version=job.plan_version,
                kind=job.kind,
                content=output.model_dump(mode="json"),
                prototype_id=job.prototype_id,
                cache_result=cache_result,
                cache_key=cache_key,
            )
        )
        progress = await db.get(ConceptProgress, (job.enrollment_id, job.concept_id))
        if progress is not None and progress.status == ConceptStatus.unlocked:
            progress.status = ConceptStatus.in_progress
        await db.commit()
        prototype = await prototype_view(db, job.prototype_id)
    await invalidate_dashboard(redis, job.user_id)  # progress changed (after the commit)
    return LessonView(
        concept_id=job.concept_id,
        kind=job.kind,
        content=output,
        cache_result=cache_result,
        prototype=prototype,
    )
