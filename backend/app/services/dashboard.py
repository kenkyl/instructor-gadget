"""Dashboard read model with a cache-aside Redis layer.

Postgres is the source of truth. `dash:{user_id}` is a native JSON copy (ADR-0011) that is
refilled on a miss and **deleted** whenever a write changes that user's enrollments.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.config import get_settings
from app.models import ConceptProgress, ConceptStatus, Course, Enrollment, Org


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
    """The expensive path: aggregate enrollments + progress from Postgres."""
    now = datetime.now(UTC)
    progress = (
        select(
            ConceptProgress.enrollment_id,
            func.count().label("total"),
            func.count(case((ConceptProgress.status == ConceptStatus.complete, 1))).label("done"),
            func.count(case((ConceptProgress.due <= now, 1))).label("due"),
        )
        .group_by(ConceptProgress.enrollment_id)
        .subquery()
    )
    rows = await db.execute(
        select(Enrollment, Course, Org.name, progress.c.total, progress.c.done, progress.c.due)
        .join(Course, Course.id == Enrollment.course_id)
        .outerjoin(Org, Org.id == Course.org_id)
        .outerjoin(progress, progress.c.enrollment_id == Enrollment.id)
        .where(Enrollment.user_id == user.id)
        .order_by(Enrollment.created_at.desc())
    )
    courses = [
        DashboardCourse(
            enrollment_id=enr.id,
            course_id=course.id,
            title=course.title,
            scope=course.scope.value,
            org_name=org_name,
            status=enr.status.value,
            concepts_total=total or 0,
            concepts_complete=done or 0,
            due_count=due or 0,
            completed_at=enr.completed_at,
        )
        for enr, course, org_name, total, done, due in rows.all()
    ]
    return Dashboard(user=user, courses=courses, generated_at=now)


async def get_dashboard(db: AsyncSession, redis: Redis, user: CurrentUser) -> DashboardResponse:
    """Cache-aside: try Redis; on a miss, build from Postgres and store with a TTL."""
    key = dash_key(user.id)
    cached = await redis.json().get(key)
    if cached is not None:
        return DashboardResponse(**cached, served_from="cache")

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
