import uuid

from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.deps import Db
from app.services.trace import TraceResponse, get_trace

router = APIRouter(tags=["trace"])


@router.get("/trace")
async def trace(user: CurrentUserDep, db: Db, course_id: uuid.UUID | None = None) -> TraceResponse:
    """The caller's own LLM calls and cache impact, optionally for one course."""
    return await get_trace(db, user, course_id)
