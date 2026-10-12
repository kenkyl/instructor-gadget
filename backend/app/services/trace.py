"""Instructor trace (PC3.4): the learner's own LLM calls, newest first, plus the cache impact tile.

Read-only over `llm_calls`, which logs every lookup, hits included (zero tokens and cost, with
the original generation's cost and latency in `saved_*`). So the impact is measured, not
estimated. Scoped to the caller's own calls (`user_id`): excerpts can hold a learner's answers,
so even on a shared org course one learner never sees another's. An org-wide view is CP4's.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.models import CacheResult, CallStatus, Course, LlmCall

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


async def get_trace(
    db: AsyncSession, user: CurrentUser, course_id: uuid.UUID | None = None
) -> TraceResponse:
    mine = [LlmCall.user_id == user.id]
    if course_id is not None:
        mine.append(LlmCall.course_id == course_id)

    is_hit = LlmCall.cache_result.in_(HITS)
    agg = (
        await db.execute(
            select(
                func.count(),
                func.count(
                    case((LlmCall.cache_result.in_((CacheResult.miss, CacheResult.bypass)), 1))
                ),
                func.count(case((LlmCall.cache_result == CacheResult.exact_hit, 1))),
                func.count(case((LlmCall.cache_result == CacheResult.semantic_hit, 1))),
                func.count(case((LlmCall.cache_result == CacheResult.miss, 1))),
                func.coalesce(func.sum(LlmCall.est_cost_usd), 0),
                func.coalesce(func.sum(case((is_hit, LlmCall.saved_cost_usd))), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                is_hit,
                                func.greatest(LlmCall.saved_latency_ms - LlmCall.latency_ms, 0),
                            )
                        )
                    ),
                    0,
                ),
            ).where(*mine)
        )
    ).one()
    calls, model_calls, exact, semantic, misses, spent, saved, saved_ms = agg
    lookups = misses + exact + semantic
    impact = CacheImpact(
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
