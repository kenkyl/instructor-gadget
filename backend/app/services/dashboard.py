"""Dashboard read model with a cache-aside Redis layer.

Postgres is the source of truth. `dash:{user_id}` is a native JSON copy (ADR-0011) that is
refilled on a miss and **deleted** whenever a write changes that user's enrollments.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import pedagogy
from agent.types import Band, ConceptMap
from app.auth import CurrentUser
from app.config import get_settings
from app.models import ConceptProgress, ConceptStatus, Course, Enrollment, Org, PlanVersion


class DashboardConcept(BaseModel):
    """One cell of the course's strip, in plan order."""

    concept_id: str
    title: str
    band: Band | None  # None = not quizzed yet
    complete: bool
    due: bool  # FSRS review date has passed


class BandCounts(BaseModel):
    not_started: int = 0
    shaky: int = 0
    learning: int = 0
    solid: int = 0
    mastered: int = 0


class DashboardCourse(BaseModel):
    enrollment_id: uuid.UUID
    course_id: uuid.UUID
    title: str
    scope: Literal["personal", "org"]
    org_name: str | None
    status: Literal["active", "complete"]
    concepts_total: int
    concepts_complete: int
    due_count: int
    bands: BandCounts
    concepts: list[DashboardConcept]
    completed_at: datetime | None


class Dashboard(BaseModel):
    user: CurrentUser
    courses: list[DashboardCourse]
    generated_at: datetime


class DashboardResponse(Dashboard):
    served_from: Literal["cache", "db"]


def dash_key(user_id: uuid.UUID) -> str:
    return f"dash:{user_id}"


async def build_dashboard(db: AsyncSession, user: CurrentUser) -> Dashboard:
    """The expensive path: enrollments, their current plans and progress from Postgres. The
    band and due rules are pedagogy's; this only orders and counts."""
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Enrollment, Course, Org.name, PlanVersion.plan)
            .join(Course, Course.id == Enrollment.course_id)
            .outerjoin(Org, Org.id == Course.org_id)
            .outerjoin(
                PlanVersion,
                (PlanVersion.enrollment_id == Enrollment.id)
                & (PlanVersion.version == Enrollment.current_plan_version),
            )
            .where(Enrollment.user_id == user.id)
            .order_by(Enrollment.created_at.desc())
        )
    ).all()
    progress: dict[uuid.UUID, list[ConceptProgress]] = {}
    if rows:
        for p in await db.scalars(
            select(ConceptProgress).where(
                ConceptProgress.enrollment_id.in_([enr.id for enr, *_ in rows])
            )
        ):
            progress.setdefault(p.enrollment_id, []).append(p)

    courses = []
    for enr, course, org_name, plan in rows:
        cmap = ConceptMap.model_validate(plan) if plan else None  # JSONB: validate it
        by_id = {p.concept_id: p for p in progress.get(enr.id, [])}
        order = [cid for cid in (cmap.sequence if cmap else []) if cid in by_id]
        order += sorted(set(by_id) - set(order))  # anything the plan doesn't list goes last
        concepts = [
            DashboardConcept(
                concept_id=cid,
                title=(c.title if cmap and (c := cmap.concept(cid)) else cid),
                band=by_id[cid].band,
                complete=by_id[cid].status == ConceptStatus.complete,
                due=pedagogy.is_due(by_id[cid].due, now),
            )
            for cid in order
        ]
        courses.append(
            DashboardCourse(
                enrollment_id=enr.id,
                course_id=course.id,
                title=course.title,
                scope=course.scope.value,
                org_name=org_name,
                status=enr.status.value,
                concepts_total=len(concepts),
                concepts_complete=sum(c.complete for c in concepts),
                due_count=sum(c.due for c in concepts),
                bands=BandCounts(**pedagogy.band_counts(c.band for c in concepts)),
                concepts=concepts,
                completed_at=enr.completed_at,
            )
        )
    return Dashboard(user=user, courses=courses, generated_at=now)


async def get_dashboard(db: AsyncSession, redis: Redis, user: CurrentUser) -> DashboardResponse:
    """Cache-aside: try Redis; on a miss, build from Postgres and store with a TTL."""
    key = dash_key(user.id)
    cached = await redis.json().get(key)
    if cached is not None:
        dashboard = Dashboard.model_validate(cached)  # validate the cached shape, don't trust it
        return DashboardResponse(**dashboard.model_dump(), served_from="cache")

    dashboard = await build_dashboard(db, user)
    async with redis.pipeline(transaction=True) as pipe:  # never a key without a TTL
        pipe.json().set(key, "$", dashboard.model_dump(mode="json"))
        pipe.expire(key, get_settings().dashboard_ttl_seconds)
        await pipe.execute()
    return DashboardResponse(**dashboard.model_dump(), served_from="db")


async def invalidate_dashboard(redis: Redis, user_id: uuid.UUID) -> None:
    """Call after any write that changes this user's enrollments or progress.

    ★ PC0.5 "your turn": implement this. Make tests/test_dashboard.py::test_invalidate pass.
    """
    await redis.delete(dash_key(user_id))
