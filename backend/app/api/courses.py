"""Course creation endpoints (J1). Thin adapter: the logic lives in app/services/courses.py."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent.llm import LLMError, LLMRefusal
from app.auth import CurrentUserDep
from app.deps import Db, LlmDep
from app.models import Course
from app.services.courses import (
    CourseDetail,
    CourseIntake,
    course_detail,
    create_course,
    get_owned_course,
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
