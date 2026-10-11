"""Learning-loop endpoints (J2). Thin adapter over app/services/learning.py and quiz.py."""

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
from app.services.quiz import (
    OverrideRequest,
    OverrideWarning,
    PlanVersionView,
    QuizResult,
    QuizView,
    SubmitRequest,
    accept_test_out,
    confirm_override,
    open_quiz,
    override_warning,
    plan_history,
    quiz_result,
    submit_quiz,
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


@router.get("/{enrollment_id}/plans")
async def get_plan_history(
    enrollment_id: uuid.UUID, user: CurrentUserDep, db: Db
) -> list[PlanVersionView]:
    """Every plan version, newest first, with its trigger, rule, why and diff (spec §4.8)."""
    return await plan_history(db, user, enrollment_id)


@router.post("/{enrollment_id}/concepts/{concept_id}/quiz")
async def post_quiz(
    enrollment_id: uuid.UUID, concept_id: str, user: CurrentUserDep, db: Db, llm: LlmDep
) -> QuizView:
    """The open quiz for this concept, or a new one (no answer keys in the response)."""
    return await open_quiz(db, llm, user, enrollment_id, concept_id)


@router.post("/{enrollment_id}/quiz-attempts/{attempt_id}/submit")
async def post_submit(
    enrollment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    body: SubmitRequest,
    user: CurrentUserDep,
    db: Db,
    redis: RedisDep,
    llm: LlmDep,
) -> QuizResult:
    """Grade, update mastery and the review date, then apply the adapt rules."""
    return await submit_quiz(db, redis, llm, user, enrollment_id, attempt_id, body.answers)


@router.get("/{enrollment_id}/quiz-attempts/{attempt_id}")
async def get_quiz_result(
    enrollment_id: uuid.UUID, attempt_id: uuid.UUID, user: CurrentUserDep, db: Db
) -> QuizResult:
    return await quiz_result(db, user, enrollment_id, attempt_id)


@router.post("/{enrollment_id}/concepts/{concept_id}/test-out")
async def post_test_out(
    enrollment_id: uuid.UUID, concept_id: str, user: CurrentUserDep, db: Db, redis: RedisDep
) -> PlanVersionView:
    """Accept the test-out offer after a 4 (ADR-0006): a new plan version."""
    return await accept_test_out(db, redis, user, enrollment_id, concept_id)


@router.get("/{enrollment_id}/concepts/{concept_id}/override")
async def get_override_warning(
    enrollment_id: uuid.UUID, concept_id: str, user: CurrentUserDep, db: Db, llm: LlmDep
) -> OverrideWarning:
    """What will break if the learner opens this locked concept now (spec §4.8)."""
    return await override_warning(db, llm, user, enrollment_id, concept_id)


@router.post("/{enrollment_id}/concepts/{concept_id}/override")
async def post_override(
    enrollment_id: uuid.UUID,
    concept_id: str,
    body: OverrideRequest,
    user: CurrentUserDep,
    db: Db,
    redis: RedisDep,
) -> PlanVersionView:
    """Open a locked concept anyway: logged, with a new plan version."""
    return await confirm_override(db, redis, user, enrollment_id, concept_id, body.warning)
