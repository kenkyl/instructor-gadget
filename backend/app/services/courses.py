"""Course creation (J1): intake → diagnostic probe → assessment. Map and accept: PC1.3–1.4.

Surface-neutral: the web router calls these, and a future MCP surface can too. Ownership is
checked here, so every surface gets the same rule.
"""

import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.llm import CallContext, LLMClient
from agent.skills.diagnose.schema import (
    AssessInput,
    AssessOutput,
    ProbeAnswer,
    ProbeInput,
    ProbeOutput,
)
from agent.types import CourseConfig, Mission
from app.auth import CurrentUser
from app.models import Assessment, Course, CourseScope, CourseStatus


class CourseIntake(BaseModel):
    """The intake form (spec §4.1). Defaults live in CourseConfig/Mission and the form."""

    config: CourseConfig
    mission: Mission


class ProbeQuestionView(BaseModel):
    """What the learner sees. `targets_concept` stays server-side: naming the concept being
    checked is a hint (spec §4.2: no hints)."""

    id: str
    prompt: str


class AnswersIn(BaseModel):
    """{question_id: answer}. Blank is allowed and counts as "I don't know" (assess.md)."""

    answers: dict[str, Annotated[str, Field(max_length=4000)]]


class CourseDetail(BaseModel):
    id: uuid.UUID
    title: str
    status: CourseStatus
    config: CourseConfig
    mission: Mission
    questions: list[ProbeQuestionView] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    # Shown to the learner in full: level, evidence, gaps and the adjustment message
    # (transparency over smoothness, spec §4.3).
    assessment: AssessOutput | None = None


async def create_course(db: AsyncSession, user: CurrentUser, intake: CourseIntake) -> Course:
    course = Course(
        scope=CourseScope.personal,
        owner_user_id=user.id,
        created_by=user.id,
        title=intake.config.topic,
        config=intake.config.model_dump(mode="json"),
        mission=intake.mission.model_dump(mode="json"),
        status=CourseStatus.draft,
    )
    db.add(course)
    await db.commit()
    # No dashboard invalidation: the dashboard lists enrollments, and none exists until the
    # learner accepts the map (PC1.4).
    return course


async def get_owned_course(db: AsyncSession, user: CurrentUser, course_id: uuid.UUID) -> Course:
    course = await db.get(Course, course_id)
    # 404, not 403, for someone else's course: don't confirm that the id exists.
    if course is None or course.owner_user_id != user.id:
        raise HTTPException(404, "course not found")
    return course


async def latest_assessment(
    db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID
) -> Assessment | None:
    return await db.scalar(
        select(Assessment)
        .where(Assessment.course_id == course_id, Assessment.user_id == user_id)
        .order_by(Assessment.created_at.desc())
        .limit(1)
    )


async def run_probe(
    db: AsyncSession, llm: LLMClient, user: CurrentUser, course: Course
) -> Assessment:
    """Generate the diagnostic questions once. Calling it again returns the same probe, so a
    retry or double-click doesn't spend a second LLM call or change the questions."""
    existing = await latest_assessment(db, course.id, user.id)
    if existing is not None:
        return existing

    probe = await llm.run(
        "diagnose",
        "probe",
        ProbeInput(
            config=CourseConfig.model_validate(course.config),
            mission=Mission.model_validate(course.mission),
        ),
        ProbeOutput,
        ctx=CallContext(user_id=user.id, course_id=course.id),
    )
    assessment = Assessment(
        course_id=course.id, user_id=user.id, probe=probe.model_dump(mode="json")
    )
    db.add(assessment)
    course.status = CourseStatus.probed
    await db.commit()
    return assessment


async def run_assess(
    db: AsyncSession, llm: LLMClient, user: CurrentUser, course: Course, answers: dict[str, str]
) -> Assessment:
    """Assess the answers once. After that the result is locked: resubmitting returns it
    unchanged, so a learner can't re-roll answers until the level comes out higher."""
    assessment = await latest_assessment(db, course.id, user.id)
    if assessment is None:
        raise HTTPException(409, "Write the diagnostic questions first.")
    if assessment.result is not None:
        return assessment

    probe = ProbeOutput.model_validate(assessment.probe)
    ids = [q.id for q in probe.questions]
    if set(answers) != set(ids):
        raise HTTPException(422, f"Send one answer per question: {ids}")
    clean = {qid: answers[qid].strip() for qid in ids}  # question order, not request order

    result = await llm.run(
        "diagnose",
        "assess",
        AssessInput(
            config=CourseConfig.model_validate(course.config),
            mission=Mission.model_validate(course.mission),
            probe=probe,
            answers=[ProbeAnswer(question_id=qid, answer=clean[qid]) for qid in ids],
        ),
        AssessOutput,
        ctx=CallContext(user_id=user.id, course_id=course.id),
    )
    assessment.answers = clean
    assessment.result = result.model_dump(mode="json")
    assessment.assessed_level = result.assessed_level
    assessment.confidence = result.confidence
    course.status = CourseStatus.assessed
    await db.commit()
    return assessment


async def course_detail(db: AsyncSession, user: CurrentUser, course: Course) -> CourseDetail:
    assessment = await latest_assessment(db, course.id, user.id)
    questions: list[ProbeQuestionView] = []
    answers: dict[str, str] = {}
    result: AssessOutput | None = None
    if assessment is not None:
        # JSONB: validate on the way out, don't trust the stored shape.
        probe = ProbeOutput.model_validate(assessment.probe)
        questions = [ProbeQuestionView(id=q.id, prompt=q.prompt) for q in probe.questions]
        answers = assessment.answers or {}
        if assessment.result is not None:
            result = AssessOutput.model_validate(assessment.result)
    return CourseDetail(
        id=course.id,
        title=course.title,
        status=course.status,
        config=CourseConfig.model_validate(course.config),
        mission=Mission.model_validate(course.mission),
        questions=questions,
        answers=answers,
        assessment=result,
    )
