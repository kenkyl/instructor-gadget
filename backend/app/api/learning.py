"""Learning-loop endpoints (J2). Thin adapter over app/services/learning.py."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from agent.llm import LLMError, LLMRefusal
from app.auth import CurrentUserDep
from app.deps import Db, LlmDep, RedisDep
from app.services.learning import (
    DoneEvent,
    EnrollmentDetail,
    FieldDeltaEvent,
    LessonJob,
    LessonView,
    RestartEvent,
    enrollment_detail,
    get_owned_enrollment,
    latest_lesson,
    prepare_lesson,
    stream_lesson,
)

router = APIRouter(prefix="/enrollments", tags=["learning"])


@router.get("/{enrollment_id}")
async def get_enrollment(
    enrollment_id: uuid.UUID, user: CurrentUserDep, db: Db
) -> EnrollmentDetail:
    """The learner's plan with per-concept status and band."""
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    return await enrollment_detail(db, enrollment)


@router.get("/{enrollment_id}/concepts/{concept_id}/lesson")
async def get_lesson(
    enrollment_id: uuid.UUID, concept_id: str, user: CurrentUserDep, db: Db
) -> LessonView:
    """The stored lesson, or 404 if it hasn't been generated yet (then POST to stream it)."""
    await get_owned_enrollment(db, user, enrollment_id)
    lesson = await latest_lesson(db, enrollment_id, concept_id)
    if lesson is None:
        raise HTTPException(404, "no lesson yet")
    return lesson


async def lesson_to_open(
    enrollment_id: uuid.UUID, concept_id: str, user: CurrentUserDep, db: Db, response: Response
) -> LessonView | LessonJob:
    """Checks run here, as a dependency, so 404/409 are real HTTP errors sent before the
    event stream starts. The DB session is released before streaming begins (see below)."""
    # Next's server gzips responses, and gzip held the whole stream back until the end
    # (measured: 332 events in one burst at 13 s). `no-transform` tells intermediaries not to
    # re-encode the body, so Next skips compressing it and events arrive as they're written.
    # Set here, not in the generator: dependencies finish before the response headers are built.
    # FastAPI's SSE response already sends `no-cache`; the two headers combine.
    response.headers["Cache-Control"] = "no-transform"
    found = await prepare_lesson(db, user, enrollment_id, concept_id)
    await db.close()  # don't hold a pooled connection for the ~20 s of streaming
    return found


# Declare before LlmDep: auth, ownership and the gate decide first (401/404/409), then 503.
LessonToOpenDep = Annotated[LessonView | LessonJob, Depends(lesson_to_open)]


@router.post("/{enrollment_id}/concepts/{concept_id}/lesson", response_class=EventSourceResponse)
async def open_lesson(
    found: LessonToOpenDep, request: Request, redis: RedisDep, llm: LlmDep
) -> AsyncIterator[ServerSentEvent]:
    """Stream the lesson as SSE: `field_delta`* (`restart`)? then `done` with the stored lesson,
    or `error`. A lesson that already exists arrives as a single `done`."""
    if isinstance(found, LessonView):
        yield ServerSentEvent(event="done", data=DoneEvent(lesson=found))
        return
    try:
        async for ev in stream_lesson(request.app.state.sessionmaker, redis, llm, found):
            match ev:
                case FieldDeltaEvent():
                    yield ServerSentEvent(event="field_delta", data=ev)
                case RestartEvent():
                    yield ServerSentEvent(event="restart", data=ev)
                case DoneEvent():
                    yield ServerSentEvent(event="done", data=ev)
    except LLMRefusal:
        # The status code is already sent (200), so errors travel as an event.
        yield ServerSentEvent(event="error", data={"message": "The instructor can't teach this."})
    except LLMError:
        yield ServerSentEvent(
            event="error", data={"message": "The instructor couldn't write this lesson. Retry."}
        )
