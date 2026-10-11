"""Writes the LLM wrapper's CallRecords to llm_calls (the agent package never imports app)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.llm import CallRecord
from app.models import CacheResult, CallStatus, LlmCall


class DbCallSink:
    """Each record commits in its own session, so the log survives even when the request
    that made the call fails and rolls back. A failed call is exactly what the trace needs."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def record(self, rec: CallRecord) -> None:
        async with self.sessionmaker() as db, db.begin():
            db.add(
                LlmCall(
                    course_id=rec.context.course_id,
                    enrollment_id=rec.context.enrollment_id,
                    user_id=rec.context.user_id,
                    skill=rec.skill,
                    call=rec.call,
                    model=rec.model,
                    prompt_version=rec.prompt_version,
                    cache_result=CacheResult(rec.cache_result),
                    input_tokens=rec.input_tokens,
                    output_tokens=rec.output_tokens,
                    latency_ms=rec.latency_ms,
                    est_cost_usd=rec.est_cost_usd,
                    status=CallStatus(rec.status),
                    error=rec.error,
                    prompt_excerpt=rec.prompt_excerpt,
                    response_excerpt=rec.response_excerpt,
                )
            )
