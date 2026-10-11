"""Course creation endpoints (J1). Thin adapter: the logic lives in app/services/courses.py."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent.llm import LLMError, LLMRefusal
from app.auth import CurrentUserDep
from app.deps import Db, LlmDep, RedisDep
from app.models import Course
from app.services.courses import (
    AnswersIn,
    CourseDetail,
    CourseIntake,
    accept_map,
    course_detail,
    create_course,
    get_owned_course,
    remove_concept,
    run_assess,
    run_map,
    run_probe,
)

router = APIRouter(prefix="/courses", tags=["courses"])


async def owned_course(course_id: uuid.UUID, user: CurrentUserDep, db: Db) -> Course:
    return await get_owned_course(db, user, course_id)


# Declare before LlmDep: FastAPI resolves dependencies in order, so auth (401) and ownership
# (404) are decided before "LLM not configured" (503).
OwnedCourseDep = Annotated[Course, Depends(owned_course)]


@router.post("", status_code=201)
async def create(intake: CourseIntake, user: CurrentUserDep, db: Db) -> CourseDetail:
    course = await create_course(db, user, intake)
    return await course_detail(db, user, course)


@router.get("/{course_id}")
async def get(course: OwnedCourseDep, user: CurrentUserDep, db: Db) -> CourseDetail:
    return await course_detail(db, user, course)


@router.post("/{course_id}/probe")
async def probe(course: OwnedCourseDep, user: CurrentUserDep, db: Db, llm: LlmDep) -> CourseDetail:
    """Generate the diagnostic questions (idempotent: a second call returns the same ones)."""
    try:
        await run_probe(db, llm, user, course)
    except LLMRefusal as err:
        raise HTTPException(422, "The instructor can't write questions for this topic.") from err
    except LLMError as err:
        # Details are in llm_calls; the learner gets a retryable message.
        raise HTTPException(502, "The instructor couldn't write questions. Try again.") from err
    return await course_detail(db, user, course)


@router.post("/{course_id}/assess")
async def assess(
    body: AnswersIn, course: OwnedCourseDep, user: CurrentUserDep, db: Db, llm: LlmDep
) -> CourseDetail:
    """Assess the probe answers (once; afterwards the result is returned unchanged)."""
    try:
        await run_assess(db, llm, user, course, body.answers)
    except LLMRefusal as err:
        raise HTTPException(422, "The instructor can't assess these answers.") from err
    except LLMError as err:
        raise HTTPException(502, "The instructor couldn't assess your answers. Try again.") from err
    return await course_detail(db, user, course)


@router.post("/{course_id}/map")
async def map_concepts(
    course: OwnedCourseDep, user: CurrentUserDep, db: Db, llm: LlmDep
) -> CourseDetail:
    """Generate the concept map (once; afterwards the same map is returned)."""
    try:
        await run_map(db, llm, user, course)
    except LLMRefusal as err:
        raise HTTPException(422, "The instructor can't plan this course.") from err
    except LLMError as err:
        raise HTTPException(502, "The instructor couldn't build your map. Try again.") from err
    return await course_detail(db, user, course)


@router.delete("/{course_id}/map/concepts/{concept_id}")
async def remove_map_concept(
    concept_id: str, course: OwnedCourseDep, user: CurrentUserDep, db: Db
) -> CourseDetail:
    """Cut a concept before accepting; its dependents inherit its prereqs (ADR-0017)."""
    await remove_concept(db, course, concept_id)
    return await course_detail(db, user, course)


@router.post("/{course_id}/accept")
async def accept(
    course: OwnedCourseDep, user: CurrentUserDep, db: Db, redis: RedisDep
) -> CourseDetail:
    """Accept the map: creates the enrollment, plan v1 and progress rows (idempotent)."""
    await accept_map(db, redis, user, course)
    return await course_detail(db, user, course)
