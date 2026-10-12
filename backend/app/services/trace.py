"""Instructor trace (PC3.4): the learner's own LLM calls, newest first, plus the cache impact tile.

Read-only over `llm_calls`, which logs every lookup, hits included (zero tokens and cost, with
the original generation's cost and latency in `saved_*`). So the impact is measured, not
estimated. Scoped to the caller's own calls (`user_id`): excerpts can hold a learner's answers,
so even on a shared org course one learner never sees another's.

The org admin's view (ADR-0030) is the same aggregate without the `user_id` filter, over the org's
courses, and without excerpts: counts and dollars per course and per learner, never content.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.models import CacheResult, CallStatus, Course, Enrollment, LlmCall, User
from app.services import org_docs

ROW_LIMIT = 200
HITS = (CacheResult.exact_hit, CacheResult.semantic_hit)


class TraceCall(BaseModel):
    id: uuid.UUID
    created_at: datetime
    course_id: uuid.UUID | None
    course_title: str | None
    skill: str
    call: str
    model: str
    prompt_version: str
    cache_result: CacheResult
    similarity: float | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    est_cost_usd: float
    saved_cost_usd: float
    saved_latency_ms: int
    status: CallStatus
    error: str | None
    prompt_excerpt: str | None
    response_excerpt: str | None


class CacheImpact(BaseModel):
    calls: int  # every logged row: model requests and cache hits
    model_calls: int  # rows that reached the model (miss or bypass; a retry is its own row)
    lookups: int  # cacheable lookups: misses + hits (bypassed calls never look)
    exact_hits: int
    semantic_hits: int
    hit_rate: float | None  # hits / lookups; None before any lookup
    spent_usd: float  # what the model calls cost
    saved_usd: float  # what the hits would have cost: the original generations' cost
    saved_seconds: float  # the original generation time minus the hit's own lookup time


class TraceCourse(BaseModel):
    id: uuid.UUID
    title: str
    calls: int


class TraceResponse(BaseModel):
    impact: CacheImpact
    calls: list[TraceCall]
    courses: list[TraceCourse]  # every course with calls, for the filter
    course_id: uuid.UUID | None  # the filter applied, if any
    truncated: bool  # more rows than ROW_LIMIT match; the impact still counts them all


_IS_HIT = LlmCall.cache_result.in_(HITS)

# One aggregate over llm_calls, in the order `_impact` reads it. The trace filters it to one
# learner; the org view groups it by course and by learner.
_AGG = (
    func.count(),
    func.count(case((LlmCall.cache_result.in_((CacheResult.miss, CacheResult.bypass)), 1))),
    func.count(case((LlmCall.cache_result == CacheResult.exact_hit, 1))),
    func.count(case((LlmCall.cache_result == CacheResult.semantic_hit, 1))),
    func.count(case((LlmCall.cache_result == CacheResult.miss, 1))),
    func.coalesce(func.sum(LlmCall.est_cost_usd), 0),
    func.coalesce(func.sum(case((_IS_HIT, LlmCall.saved_cost_usd))), 0),
    func.coalesce(
        func.sum(case((_IS_HIT, func.greatest(LlmCall.saved_latency_ms - LlmCall.latency_ms, 0)))),
        0,
    ),
)


def _impact(row: Any) -> CacheImpact:
    """A CacheImpact from the first eight values of an `_AGG` row."""
    calls, model_calls, exact, semantic, misses, spent, saved, saved_ms = tuple(row)[:8]
    lookups = misses + exact + semantic
    return CacheImpact(
        calls=calls,
        model_calls=model_calls,
        lookups=lookups,
        exact_hits=exact,
        semantic_hits=semantic,
        hit_rate=(exact + semantic) / lookups if lookups else None,
        spent_usd=float(spent),
        saved_usd=float(saved),
        saved_seconds=int(saved_ms) / 1000,
    )


async def get_trace(
    db: AsyncSession, user: CurrentUser, course_id: uuid.UUID | None = None
) -> TraceResponse:
    mine = [LlmCall.user_id == user.id]
    if course_id is not None:
        mine.append(LlmCall.course_id == course_id)

    impact = _impact((await db.execute(select(*_AGG).where(*mine))).one())
    calls = impact.calls

    rows = (
        await db.execute(
            select(LlmCall, Course.title)
            .outerjoin(Course, Course.id == LlmCall.course_id)
            .where(*mine)
            .order_by(LlmCall.created_at.desc())
            .limit(ROW_LIMIT)
        )
    ).all()
    trace = [
        TraceCall.model_validate(
            {
                **{f: getattr(c, f) for f in TraceCall.model_fields if f != "course_title"},
                "course_title": title,
            }
        )
        for c, title in rows
    ]

    courses = (
        await db.execute(
            select(Course.id, Course.title, func.count())
            .join(LlmCall, LlmCall.course_id == Course.id)
            .where(LlmCall.user_id == user.id)
            .group_by(Course.id, Course.title)
            .order_by(func.max(LlmCall.created_at).desc())
        )
    ).all()
    return TraceResponse(
        impact=impact,
        calls=trace,
        courses=[TraceCourse(id=i, title=t, calls=n) for i, t, n in courses],
        course_id=course_id,
        truncated=calls > ROW_LIMIT,
    )


class OrgCourseImpact(BaseModel):
    course_id: uuid.UUID
    title: str
    learners: int  # enrolled
    impact: CacheImpact


class OrgLearnerImpact(BaseModel):
    user_id: uuid.UUID
    display_name: str
    first_call_at: datetime
    impact: CacheImpact


class OrgImpactResponse(BaseModel):
    org_name: str
    impact: CacheImpact
    courses: list[OrgCourseImpact]
    # In the order each person first used the org's courses: the first learner pays to generate a
    # lesson, and the ones after them reuse it, so the spend per learner visibly falls.
    learners: list[OrgLearnerImpact]


async def get_org_impact(db: AsyncSession, user: CurrentUser, org_slug: str) -> OrgImpactResponse:
    """The cache's effect across an org's courses (admins only). The same measured aggregate as
    the learner's trace, over every learner's calls on the org's courses, and with no excerpts,
    because those can hold a learner's answers (ADR-0027)."""
    org, role = await org_docs.member_org(db, user, org_slug)
    org_docs.require_admin(role)
    org_courses = LlmCall.course_id.in_(select(Course.id).where(Course.org_id == org.id))

    total = _impact((await db.execute(select(*_AGG).where(org_courses))).one())
    per_course = (
        await db.execute(
            select(Course.id, Course.title, *_AGG)
            .join(LlmCall, LlmCall.course_id == Course.id)
            .where(Course.org_id == org.id)
            .group_by(Course.id, Course.title)
            .order_by(func.max(LlmCall.created_at).desc())
        )
    ).all()
    enrolled = {
        course_id: n
        for course_id, n in await db.execute(
            select(Enrollment.course_id, func.count())
            .join(Course, Course.id == Enrollment.course_id)
            .where(Course.org_id == org.id)
            .group_by(Enrollment.course_id)
        )
    }
    per_learner = (
        await db.execute(
            select(User.id, User.display_name, func.min(LlmCall.created_at), *_AGG)
            .join(LlmCall, LlmCall.user_id == User.id)
            .where(org_courses)
            .group_by(User.id, User.display_name)
            .order_by(func.min(LlmCall.created_at))
        )
    ).all()
    return OrgImpactResponse(
        org_name=org.name,
        impact=total,
        courses=[
            OrgCourseImpact(
                course_id=r[0], title=r[1], learners=enrolled.get(r[0], 0), impact=_impact(r[2:])
            )
            for r in per_course
        ],
        learners=[
            OrgLearnerImpact(
                user_id=r[0], display_name=r[1], first_call_at=r[2], impact=_impact(r[3:])
            )
            for r in per_learner
        ],
    )
