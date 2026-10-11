"""SQLAlchemy 2.x models: Postgres is the durable source of truth.

Design notes (see docs/decisions.md):
- Per-learner state hangs off an Enrollment (course x user), never off the course (ADR-0004).
- Flexible, evolving shapes (course config, plans, quiz questions) are JSONB validated by Pydantic
  at the service boundary, so new knobs don't need migrations (roadmap: extensibility hooks).
- Enums are stored as short strings and validated in Python, so adding a value is a code
  change, not an ALTER TYPE migration (ADR-0010).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, so Alembic autogenerate produces stable, reviewable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# --- enums --------------------------------------------------------------------------------------
class Role(StrEnum):
    member = "member"
    admin = "admin"


class CourseScope(StrEnum):
    personal = "personal"
    org = "org"


class CourseStatus(StrEnum):
    draft = "draft"  # intake saved
    probed = "probed"  # diagnostic questions generated
    assessed = "assessed"  # level assessed from answers
    mapped = "mapped"  # concept map generated, awaiting accept
    active = "active"  # accepted; learning in progress


class EnrollmentSource(StrEnum):
    owner = "owner"  # personal course creator
    assigned = "assigned"  # org admin assigned it


class EnrollmentStatus(StrEnum):
    active = "active"
    complete = "complete"


class PlanTrigger(StrEnum):
    diagnosis = "diagnosis"
    assignment = "assignment"
    quiz_result = "quiz_result"
    prereq_override = "prereq_override"
    user_request = "user_request"  # P2 instructor chat; present now so the enum doesn't change


class ConceptStatus(StrEnum):
    locked = "locked"
    unlocked = "unlocked"
    in_progress = "in_progress"
    complete = "complete"


class Band(StrEnum):
    shaky = "shaky"
    learning = "learning"
    solid = "solid"
    mastered = "mastered"


class LessonKind(StrEnum):
    core = "core"
    remediation = "remediation"


class CacheResult(StrEnum):
    miss = "miss"
    exact_hit = "exact_hit"
    semantic_hit = "semantic_hit"
    bypass = "bypass"


class CallStatus(StrEnum):
    ok = "ok"
    error = "error"


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Store as VARCHAR (no native PG enum type); SQLAlchemy validates values in Python."""
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


# --- base ---------------------------------------------------------------------------------------
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def fk(target: str, *, nullable: bool = False, index: bool = True) -> Any:
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), nullable=nullable, index=index)


# --- identity -----------------------------------------------------------------------------------
class Org(Base):
    __tablename__ = "orgs"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created_at()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(str_enum(Role))


# --- courses & enrollments ----------------------------------------------------------------------
class Course(Base):
    """The shared definition of a course. Per-learner state lives on Enrollment."""

    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'personal' AND owner_user_id IS NOT NULL AND org_id IS NULL)"
            " OR (scope = 'org' AND org_id IS NOT NULL AND owner_user_id IS NULL)",
            name="scope_owner",
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    scope: Mapped[CourseScope] = mapped_column(str_enum(CourseScope))
    owner_user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    org_id: Mapped[uuid.UUID | None] = fk("orgs.id", nullable=True)
    created_by: Mapped[uuid.UUID] = fk("users.id")
    title: Mapped[str] = mapped_column(String(300))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # CourseConfig (Pydantic)
    mission: Mapped[dict[str, Any]] = mapped_column(default=dict)  # Mission (Pydantic)
    status: Mapped[CourseStatus] = mapped_column(str_enum(CourseStatus), default=CourseStatus.draft)
    # The course's base ConceptMap: proposed until accepted; each enrollment copies it (ADR-0016)
    template_plan: Mapped[dict[str, Any] | None]
    doc_ids: Mapped[list[Any]] = mapped_column(default=list)
    doc_set_hash: Mapped[str | None] = mapped_column(String(64))  # part of the cache bucket
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Enrollment(Base):
    """One learner's journey through one course: plans, progress, lessons all hang off this."""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "user_id"),)
    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = fk("courses.id")
    user_id: Mapped[uuid.UUID] = fk("users.id")
    source: Mapped[EnrollmentSource] = mapped_column(str_enum(EnrollmentSource))
    assigned_by: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, index=False)
    current_plan_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[EnrollmentStatus] = mapped_column(
        str_enum(EnrollmentStatus), default=EnrollmentStatus.active
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # = badge
    created_at: Mapped[datetime] = created_at()


class Assessment(Base):
    """Diagnostic probe + answers + assessed level (spec §4.2-4.3)."""

    __tablename__ = "assessments"
    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = fk("courses.id")
    user_id: Mapped[uuid.UUID] = fk("users.id")
    probe: Mapped[dict[str, Any]]  # ProbeOutput
    answers: Mapped[dict[str, Any] | None]
    result: Mapped[dict[str, Any] | None]  # AssessOutput
    assessed_level: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at()


class PlanVersion(Base):
    """Every plan change is a new version with a trigger, a reason, and a diff (spec §4.8)."""

    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("enrollment_id", "version"),)
    id: Mapped[uuid.UUID] = pk()
    enrollment_id: Mapped[uuid.UUID] = fk("enrollments.id")
    version: Mapped[int] = mapped_column(Integer)
    plan: Mapped[dict[str, Any]]  # ConceptMap + per-concept plan state
    diff: Mapped[dict[str, Any] | None]  # PlanDiff vs. previous version
    trigger: Mapped[PlanTrigger] = mapped_column(str_enum(PlanTrigger))
    reason: Mapped[str] = mapped_column(Text)  # plain-English "why"
    rule: Mapped[str | None] = mapped_column(String(64))  # which pedagogy rule fired
    created_at: Mapped[datetime] = created_at()


# --- learner model ------------------------------------------------------------------------------
class ConceptProgress(Base):
    """The learner model per concept (spec §3)."""

    __tablename__ = "concept_progress"
    __table_args__ = (Index(None, "due"),)  # "N concepts due for review"
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[ConceptStatus] = mapped_column(
        str_enum(ConceptStatus), default=ConceptStatus.locked
    )
    mastery: Mapped[float | None] = mapped_column(Float)
    band: Mapped[Band | None] = mapped_column(str_enum(Band))
    last_score: Mapped[int | None] = mapped_column(SmallInteger)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fsrs_card: Mapped[dict[str, Any] | None]  # serialized fsrs.Card
    due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Misconception(Base):
    __tablename__ = "misconceptions"
    id: Mapped[uuid.UUID] = pk()
    enrollment_id: Mapped[uuid.UUID] = fk("enrollments.id")
    concept_id: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(300))  # short name, e.g. "requests = limits"
    note: Mapped[str] = mapped_column(Text)  # the underlying belief, in plain English
    source_question: Mapped[str | None] = mapped_column(Text)
    quiz_attempt_id: Mapped[uuid.UUID | None] = fk("quiz_attempts.id", nullable=True, index=False)
    created_at: Mapped[datetime] = created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrereqOverride(Base):
    __tablename__ = "prereq_overrides"
    id: Mapped[uuid.UUID] = pk()
    enrollment_id: Mapped[uuid.UUID] = fk("enrollments.id")
    concept_id: Mapped[str] = mapped_column(String(100))
    unmet_prereqs: Mapped[list[Any]]
    warning: Mapped[str] = mapped_column(Text)  # what we told them would break
    created_at: Mapped[datetime] = created_at()


# --- content ------------------------------------------------------------------------------------
class Prototype(Base):
    """Self-contained HTML/JS simulators, rendered only in a sandboxed iframe."""

    __tablename__ = "prototypes"
    id: Mapped[uuid.UUID] = pk()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    concept_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    html: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[uuid.UUID] = pk()
    enrollment_id: Mapped[uuid.UUID] = fk("enrollments.id")
    concept_id: Mapped[str] = mapped_column(String(100))
    plan_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[LessonKind] = mapped_column(str_enum(LessonKind), default=LessonKind.core)
    content: Mapped[dict[str, Any]]  # LessonOutput: surface-neutral markdown/mermaid/citations
    prototype_id: Mapped[uuid.UUID | None] = fk("prototypes.id", nullable=True, index=False)
    cache_result: Mapped[CacheResult] = mapped_column(str_enum(CacheResult))
    cache_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()


class QuizAttempt(Base):
    """Questions are stored with answer keys server-side; the browser never sees the keys."""

    __tablename__ = "quiz_attempts"
    id: Mapped[uuid.UUID] = pk()
    enrollment_id: Mapped[uuid.UUID] = fk("enrollments.id")
    concept_id: Mapped[str] = mapped_column(String(100))
    lesson_id: Mapped[uuid.UUID | None] = fk("lessons.id", nullable=True, index=False)
    questions: Mapped[dict[str, Any]]  # QuizOutput, including answers and rubrics
    answers: Mapped[dict[str, Any] | None]
    mcq_correct: Mapped[int | None] = mapped_column(SmallInteger)
    mcq_score: Mapped[int | None] = mapped_column(SmallInteger)
    short_score: Mapped[int | None] = mapped_column(SmallInteger)
    score_1_4: Mapped[int | None] = mapped_column(SmallInteger)  # combined: lower of the two
    feedback: Mapped[dict[str, Any] | None]
    misconceptions_named: Mapped[list[Any] | None]
    created_at: Mapped[datetime] = created_at()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgDoc(Base):
    __tablename__ = "org_docs"
    __table_args__ = (UniqueConstraint("org_id", "slug"),)
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("orgs.id")
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_md: Mapped[str] = mapped_column(Text)
    sections: Mapped[list[Any]] = mapped_column(default=list)  # [{anchor, heading}] for citations
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


# --- observability ------------------------------------------------------------------------------
class LlmCall(Base):
    """Every model call, including cache hits (zero tokens) so the trace shows what was avoided."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index(None, "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID | None] = fk("courses.id", nullable=True)
    enrollment_id: Mapped[uuid.UUID | None] = fk("enrollments.id", nullable=True, index=False)
    user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, index=False)
    skill: Mapped[str] = mapped_column(String(64))
    call: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(128))
    cache_result: Mapped[CacheResult] = mapped_column(str_enum(CacheResult))
    similarity: Mapped[float | None] = mapped_column(Float)
    cache_key: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6, asdecimal=False), default=0)
    saved_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6, asdecimal=False), default=0)
    saved_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CallStatus] = mapped_column(str_enum(CallStatus))
    error: Mapped[str | None] = mapped_column(Text)
    prompt_excerpt: Mapped[str | None] = mapped_column(Text)
    response_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
