"""Course creation (J1): intake → diagnostic probe → assessment → concept map → edit → accept.

Surface-neutral: the web router calls these, and a future MCP surface can too. Ownership is
checked here, so every surface gets the same rule.
"""

import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import pedagogy, plan
from agent.llm import CallContext, LLMClient
from agent.skills.diagnose.schema import (
    AssessInput,
    AssessOutput,
    ProbeAnswer,
    ProbeInput,
    ProbeOutput,
)
from agent.types import ConceptMap, CourseConfig, MapInput, MapOutput, Mission
from app.auth import CurrentUser
from app.models import (
    Assessment,
    ConceptProgress,
    ConceptStatus,
    Course,
    CourseScope,
    CourseStatus,
    Enrollment,
    EnrollmentSource,
    PlanTrigger,
    PlanVersion,
)
from app.services.dashboard import invalidate_dashboard


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
    concept_map: ConceptMap | None = None  # proposed while `mapped`; final once `active`
    enrollment_id: uuid.UUID | None = None  # set once the learner accepts the map


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


async def run_map(db: AsyncSession, llm: LLMClient, user: CurrentUser, course: Course) -> Course:
    """Generate the concept map once, from the intake and the assessment. Stored as the
    course's base map (`template_plan`), which accept copies into the learner's plan v1."""
    if course.template_plan is not None:
        return course
    assessment = await latest_assessment(db, course.id, user.id)
    if assessment is None or assessment.result is None:
        raise HTTPException(409, "Submit your diagnostic answers first.")

    config = CourseConfig.model_validate(course.config)
    result = AssessOutput.model_validate(assessment.result)
    cmap = await llm.run(
        "map-concepts",
        "map",
        MapInput(
            config=config,
            mission=Mission.model_validate(course.mission),
            assessed_level=result.assessed_level,
            gaps=result.gaps,
            target_minutes=round(config.target_hours * 60),
        ),
        MapOutput,
        ctx=CallContext(user_id=user.id, course_id=course.id),
    )
    # Store as the general ConceptMap shape (no generation-only bounds) so later edits validate.
    course.template_plan = ConceptMap.model_validate(cmap.model_dump()).model_dump(mode="json")
    course.status = CourseStatus.mapped
    await db.commit()
    return course


def _editable_map(course: Course) -> ConceptMap:
    if course.status != CourseStatus.mapped or course.template_plan is None:
        raise HTTPException(409, "The map can only be edited before you accept it.")
    return ConceptMap.model_validate(course.template_plan)


async def remove_concept(db: AsyncSession, course: Course, concept_id: str) -> Course:
    """Cut a concept before accept. Its dependents inherit its prereqs (ADR-0017), so the map
    stays a valid DAG and the old order minus this concept is still a valid order."""
    cmap = _editable_map(course)
    if concept_id not in {c.id for c in cmap.concepts}:
        raise HTTPException(404, "concept not in this map")
    if len(cmap.concepts) == 1:
        raise HTTPException(422, "A course needs at least one concept.")

    graph = plan.remove_concept(cmap.graph(), concept_id)
    edited = ConceptMap(
        concepts=[
            c.model_copy(update={"prereqs": graph[c.id]}) for c in cmap.concepts if c.id in graph
        ],
        sequence=[c for c in cmap.sequence if c != concept_id],
        sequence_rationale=cmap.sequence_rationale,
    )  # validators re-check the graph rules on the edited map
    course.template_plan = edited.model_dump(mode="json")
    await db.commit()
    return course


async def accept_map(db: AsyncSession, redis: Redis, user: CurrentUser, course: Course) -> Course:
    """Accept the map: the course becomes this learner's. One transaction creates the
    enrollment, plan v1 (a copy of the base map, ADR-0016) and one progress row per concept."""
    if course.status == CourseStatus.active:
        return course  # already accepted
    cmap = _editable_map(course)

    enrollment = Enrollment(
        course_id=course.id,
        user_id=user.id,
        source=EnrollmentSource.owner,
        current_plan_version=1,
    )
    db.add(enrollment)
    await db.flush()  # assigns enrollment.id for the rows below
    db.add(
        PlanVersion(
            enrollment_id=enrollment.id,
            version=1,
            plan=cmap.model_dump(mode="json"),
            trigger=PlanTrigger.diagnosis,
            reason=cmap.sequence_rationale,  # v1's "why" is the instructor's reasoning
        )
    )
    unlocked = pedagogy.initially_unlocked(cmap.graph())
    db.add_all(
        ConceptProgress(
            enrollment_id=enrollment.id,
            concept_id=c.id,
            status=ConceptStatus.unlocked if c.id in unlocked else ConceptStatus.locked,
        )
        for c in cmap.concepts
    )
    course.status = CourseStatus.active
    await db.commit()
    # After the commit: delete, don't patch (cache-aside). The next dashboard read rebuilds.
    await invalidate_dashboard(redis, user.id)
    return course


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
    enrollment_id = await db.scalar(
        select(Enrollment.id).where(
            Enrollment.course_id == course.id, Enrollment.user_id == user.id
        )
    )
    return CourseDetail(
        id=course.id,
        title=course.title,
        status=course.status,
        config=CourseConfig.model_validate(course.config),
        mission=Mission.model_validate(course.mission),
        questions=questions,
        answers=answers,
        assessment=result,
        concept_map=(
            ConceptMap.model_validate(course.template_plan) if course.template_plan else None
        ),
        enrollment_id=enrollment_id,
    )
