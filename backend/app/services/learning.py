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
from agent.types import Band, ConceptMap, CourseConfig, LessonOutput, Mission, TeachInput
from app.auth import CurrentUser
from app.models import (
    CacheResult,
    ConceptProgress,
    ConceptStatus,
    Course,
    Enrollment,
    Lesson,
    LessonKind,
    PlanVersion,
)
from app.services.dashboard import invalidate_dashboard

# The LessonOutput string fields streamed to the learner, in the order the model writes them.
STREAMED_FIELDS = ("explanation_md", "example_md", "diagram_mermaid")


class ProgressView(BaseModel):
    concept_id: str
    status: ConceptStatus
    mastery: float | None
    band: Band | None
    due: datetime | None


class EnrollmentDetail(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    plan_version: int
    concept_map: ConceptMap
    progress: list[ProgressView]  # in the plan's sequence order


class LessonView(BaseModel):
    concept_id: str
    kind: LessonKind
    content: LessonOutput
    cache_result: CacheResult


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
    payload: TeachInput


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


async def enrollment_detail(db: AsyncSession, enrollment: Enrollment) -> EnrollmentDetail:
    course = await db.get(Course, enrollment.course_id)
    assert course is not None
    cmap = await current_plan(db, enrollment)
    rows = {
        p.concept_id: p
        for p in await db.scalars(
            select(ConceptProgress).where(ConceptProgress.enrollment_id == enrollment.id)
        )
    }
    return EnrollmentDetail(
        id=enrollment.id,
        course_id=course.id,
        title=course.title,
        plan_version=enrollment.current_plan_version,
        concept_map=cmap,
        progress=[
            ProgressView(
                concept_id=cid,
                status=rows[cid].status,
                mastery=rows[cid].mastery,
                band=rows[cid].band,
                due=rows[cid].due,
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
        .where(
            Lesson.enrollment_id == enrollment_id,
            Lesson.concept_id == concept_id,
            Lesson.kind == LessonKind.core,
        )
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
        # The override (open anyway, with a warning) arrives in PC2.6.
        raise HTTPException(409, "This concept is locked until its prerequisites are solid.")

    existing = await latest_lesson(db, enrollment.id, concept_id)
    if existing is not None:
        return existing

    course = await db.get(Course, enrollment.course_id)
    assert course is not None
    config = CourseConfig.model_validate(course.config)
    return LessonJob(
        user_id=user.id,
        course_id=course.id,
        enrollment_id=enrollment.id,
        concept_id=concept_id,
        plan_version=enrollment.current_plan_version,
        payload=TeachInput(
            topic=config.topic,
            target_level=config.target_level,
            analogy_domain=Mission.model_validate(course.mission).analogy_domain,
            formats=sorted(config.formats),
            concept=concept,
            prereq_titles=[concepts[p].title for p in concept.prereqs if p in concepts],
        ),
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
    async for event in llm.stream("teach-concept", "teach", job.payload, LessonOutput, ctx=ctx):
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
                kind=LessonKind.core,
                content=output.model_dump(mode="json"),
                cache_result=cache_result,
                cache_key=cache_key,
            )
        )
        progress = await db.get(ConceptProgress, (job.enrollment_id, job.concept_id))
        if progress is not None and progress.status == ConceptStatus.unlocked:
            progress.status = ConceptStatus.in_progress
        await db.commit()
    await invalidate_dashboard(redis, job.user_id)  # progress changed (after the commit)
    return LessonView(
        concept_id=job.concept_id, kind=LessonKind.core, content=output, cache_result=cache_result
    )
