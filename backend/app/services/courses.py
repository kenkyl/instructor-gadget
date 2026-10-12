"""Course creation (J1, J3): intake → [probe → assessment] → concept map → edit → accept → [assign].

A personal course goes through the diagnostic probe and is accepted by its learner. An org course
is a template (ADR-0004): the admin builds a grounded map with no probe, accepts it, and assigns it,
and each learner's enrollment starts from a copy of it.

Surface-neutral: the web router calls these, and a future MCP surface can too. Ownership is
checked here, so every surface gets the same rule.
"""

import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent import pedagogy, plan, sources
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
    EnrollmentStatus,
    Membership,
    Org,
    OrgDoc,
    PlanTrigger,
    PlanVersion,
    Role,
    User,
)
from app.services import org_docs
from app.services.dashboard import invalidate_dashboard


class CourseIntake(BaseModel):
    """The intake form (spec §4.1). Defaults live in CourseConfig/Mission and the form."""

    config: CourseConfig
    mission: Mission
    # An org course (admins only) is built as a template and grounded in the org's docs
    # (ADR-0004, ADR-0028). Absent, it's a personal course.
    org_slug: str | None = None
    doc_slugs: list[str] = Field(default_factory=list, max_length=20)


class CourseDocRef(BaseModel):
    """A doc a course is grounded in, as the course page lists it."""

    slug: str
    title: str
    section_count: int


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
    scope: CourseScope
    org_name: str | None = None  # org courses only
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
    # Org courses: the docs it is grounded in (in the order chosen) and their set hash, which
    # is part of the semantic-cache bucket (ADR-0007).
    docs: list[CourseDocRef] = Field(default_factory=list)
    doc_set_hash: str | None = None


async def create_course(db: AsyncSession, user: CurrentUser, intake: CourseIntake) -> Course:
    course = Course(
        created_by=user.id,
        title=intake.config.topic,
        config=intake.config.model_dump(mode="json"),
        mission=intake.mission.model_dump(mode="json"),
        status=CourseStatus.draft,
    )
    if intake.org_slug is None:
        if intake.doc_slugs:
            raise HTTPException(422, "Docs can only ground an org course.")
        course.scope = CourseScope.personal
        course.owner_user_id = user.id
    else:
        org, role = await org_docs.member_org(db, user, intake.org_slug)
        org_docs.require_admin(role)
        docs = await org_docs.resolve_doc_set(db, org.id, intake.doc_slugs)
        course.scope = CourseScope.org
        course.org_id = org.id
        course.doc_ids = [str(d.id) for d in docs]
        # Pinned now: docs are immutable (ADR-0028), so the set can't drift under the course.
        course.doc_set_hash = sources.doc_set_hash((d.slug, d.content_hash) for d in docs)
    db.add(course)
    await db.commit()
    # No dashboard invalidation: the dashboard lists enrollments, and none exists until the
    # learner accepts the map (PC1.4).
    return course


async def get_owned_course(db: AsyncSession, user: CurrentUser, course_id: uuid.UUID) -> Course:
    """A personal course's owner, or an admin of the org that owns an org course (learners reach
    an org course through their enrollment, not through this)."""
    course = await db.get(Course, course_id)
    allowed = False
    if course is not None:
        if course.scope == CourseScope.org:
            allowed = (
                await db.scalar(
                    select(Membership.role).where(
                        Membership.org_id == course.org_id,
                        Membership.user_id == user.id,
                        Membership.role == Role.admin,
                    )
                )
                is not None
            )
        else:
            allowed = course.owner_user_id == user.id
    # 404, not 403, for someone else's course: don't confirm that the id exists.
    if course is None or not allowed:
        raise HTTPException(404, "course not found")
    return course


def _require_personal(course: Course) -> None:
    """The diagnostic probe and its assessment are a personal course's path. An org course has no
    probe: the admin builds a template, and each learner's plan starts from a copy (ADR-0004)."""
    if course.scope == CourseScope.org:
        raise HTTPException(
            409,
            "Org courses have no diagnostic probe: an admin builds the template, and each "
            "learner's plan starts from a copy of it.",
        )


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
    _require_personal(course)
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
    _require_personal(course)
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
    """Generate the concept map once. Stored as the course's base map (`template_plan`), which
    accept copies into the learner's plan v1 (personal) or into every assigned learner's (org).

    A personal map comes from the intake and the learner's assessment. An org template has no
    assessment (ADR-0004): it starts at the cohort's level, and the org's docs are where its
    concepts come from (ADR-0030)."""
    if course.template_plan is not None:
        return course
    config = CourseConfig.model_validate(course.config)
    grounding = await org_docs.course_grounding(db, course)  # None for a personal course
    if grounding is None:
        assessment = await latest_assessment(db, course.id, user.id)
        if assessment is None or assessment.result is None:
            raise HTTPException(409, "Submit your diagnostic answers first.")
        result = AssessOutput.model_validate(assessment.result)
        level, gaps = result.assessed_level, result.gaps
    else:
        level, gaps = config.self_level, []
    cmap = await llm.run(
        "map-concepts",
        "map",
        MapInput(
            config=config,
            mission=Mission.model_validate(course.mission),
            assessed_level=level,
            gaps=gaps,
            target_minutes=round(config.target_hours * 60),
        ),
        MapOutput,
        ctx=CallContext(user_id=user.id, course_id=course.id),
        grounding=grounding,
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


async def _start_enrollment(
    db: AsyncSession,
    course: Course,
    cmap: ConceptMap,
    user_id: uuid.UUID,
    *,
    source: EnrollmentSource,
    trigger: PlanTrigger,
    assigned_by: uuid.UUID | None = None,
) -> Enrollment:
    """One learner's enrollment: plan v1 (a copy of the base map, ADR-0016) and one progress row
    per concept. Adds to the session; the caller commits, so a batch is one transaction."""
    enrollment = Enrollment(
        course_id=course.id,
        user_id=user_id,
        source=source,
        assigned_by=assigned_by,
        current_plan_version=1,
    )
    db.add(enrollment)
    await db.flush()  # assigns enrollment.id for the rows below
    db.add(
        PlanVersion(
            enrollment_id=enrollment.id,
            version=1,
            plan=cmap.model_dump(mode="json"),
            trigger=trigger,
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
    return enrollment


async def accept_map(db: AsyncSession, redis: Redis, user: CurrentUser, course: Course) -> Course:
    """Accept the map. A personal course becomes this learner's: one transaction creates the
    enrollment, plan v1 and the progress rows. An org course becomes an assignable template and
    enrolls nobody, least of all the admin who built it (ADR-0004)."""
    if course.status == CourseStatus.active:
        return course  # already accepted
    cmap = _editable_map(course)
    if course.scope == CourseScope.org:
        course.status = CourseStatus.active
        await db.commit()
        # No dashboard invalidation: nobody's enrollments changed (assignment does that).
        return course

    await _start_enrollment(
        db,
        course,
        cmap,
        user.id,
        source=EnrollmentSource.owner,
        trigger=PlanTrigger.diagnosis,
    )
    course.status = CourseStatus.active
    await db.commit()
    # After the commit: delete, don't patch (cache-aside). The next dashboard read rebuilds.
    await invalidate_dashboard(redis, user.id)
    return course


class AssigneeView(BaseModel):
    """An org member, and where they are in this course if it was assigned to them."""

    user_id: uuid.UUID
    username: str
    display_name: str
    role: Role
    enrollment_id: uuid.UUID | None = None  # None: not assigned
    status: EnrollmentStatus | None = None
    concepts_total: int = 0
    concepts_complete: int = 0


class Assignments(BaseModel):
    course_id: uuid.UUID
    assignable: bool  # the template is accepted
    members: list[AssigneeView]


class AssignIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


def _require_org_course(course: Course) -> None:
    if course.scope != CourseScope.org:
        raise HTTPException(409, "Only an org course can be assigned.")


async def list_assignments(db: AsyncSession, course: Course) -> Assignments:
    """Every member of the course's org, with their enrollment in it (if any). Counts only: an
    admin sees how far a learner is, never their answers."""
    _require_org_course(course)
    rows = await db.execute(
        select(
            User.id,
            User.username,
            User.display_name,
            Membership.role,
            Enrollment.id,
            Enrollment.status,
            func.count(ConceptProgress.concept_id),
            func.count(case((ConceptProgress.status == ConceptStatus.complete, 1))),
        )
        .select_from(Membership)
        .join(User, User.id == Membership.user_id)
        .outerjoin(
            Enrollment, and_(Enrollment.user_id == User.id, Enrollment.course_id == course.id)
        )
        .outerjoin(ConceptProgress, ConceptProgress.enrollment_id == Enrollment.id)
        .where(Membership.org_id == course.org_id)
        .group_by(User.id, User.username, User.display_name, Membership.role, Enrollment.id)
        .order_by(User.display_name)
    )
    return Assignments(
        course_id=course.id,
        assignable=course.status == CourseStatus.active,
        members=[
            AssigneeView(
                user_id=uid,
                username=name,
                display_name=display,
                role=role,
                enrollment_id=enr_id,
                status=status,
                concepts_total=total,
                concepts_complete=done,
            )
            for uid, name, display, role, enr_id, status, total, done in rows.all()
        ],
    )


async def assign_course(
    db: AsyncSession, redis: Redis, admin: CurrentUser, course: Course, user_ids: list[uuid.UUID]
) -> Assignments:
    """Enroll org members in an accepted template: each gets their own enrollment, whose plan
    v1 is a copy of the template (ADR-0004). Assigning someone twice changes nothing."""
    _require_org_course(course)
    if course.status != CourseStatus.active or course.template_plan is None:
        raise HTTPException(409, "Accept the course template before assigning it.")
    wanted = list(dict.fromkeys(user_ids))
    members = set(
        await db.scalars(
            select(Membership.user_id).where(
                Membership.org_id == course.org_id, Membership.user_id.in_(wanted)
            )
        )
    )
    outsiders = [u for u in wanted if u not in members]
    if outsiders:
        raise HTTPException(422, "Only members of this org can be assigned the course.")
    enrolled = set(
        await db.scalars(
            select(Enrollment.user_id).where(
                Enrollment.course_id == course.id, Enrollment.user_id.in_(wanted)
            )
        )
    )
    cmap = ConceptMap.model_validate(course.template_plan)
    new = [u for u in wanted if u not in enrolled]
    for user_id in new:
        await _start_enrollment(
            db,
            course,
            cmap,
            user_id,
            source=EnrollmentSource.assigned,
            trigger=PlanTrigger.assignment,
            assigned_by=admin.id,
        )
    try:
        await db.commit()
    except IntegrityError as err:  # a concurrent assignment of the same learner won the race
        await db.rollback()
        raise HTTPException(409, "Someone just assigned this course. Refresh and check.") from err
    for user_id in new:
        await invalidate_dashboard(redis, user_id)  # after the commit; their next read rebuilds
    return await list_assignments(db, course)


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
    docs: list[CourseDocRef] = []
    if course.doc_ids:
        by_id = {
            str(d.id): d
            for d in await db.scalars(
                select(OrgDoc).where(OrgDoc.id.in_([uuid.UUID(i) for i in course.doc_ids]))
            )
        }
        docs = [
            CourseDocRef(slug=d.slug, title=d.title, section_count=len(d.sections))
            for i in course.doc_ids
            if (d := by_id.get(str(i))) is not None
        ]
    org_name = await db.scalar(select(Org.name).where(Org.id == course.org_id))
    return CourseDetail(
        id=course.id,
        title=course.title,
        scope=course.scope,
        org_name=org_name,
        docs=docs,
        doc_set_hash=course.doc_set_hash,
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
