"""GET /api/health: is every dependency the app needs reachable?"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: CheckStatus
    postgres: CheckStatus
    redis: CheckStatus
    redis_version: str | None
    query_engine: CheckStatus


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    postgres: CheckStatus = "error"
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        postgres = "ok"
    except Exception:
        pass

    redis_status: CheckStatus = "error"
    redis_version: str | None = None
    query_engine: CheckStatus = "error"
    try:
        r = request.app.state.redis
        await r.ping()
        redis_status = "ok"
        redis_version = (await r.info("server"))["redis_version"]
        await r.execute_command("FT._LIST")  # fails if the Query Engine (vector search) is absent
        query_engine = "ok"
    except Exception:
        pass

    overall: CheckStatus = "ok" if postgres == redis_status == query_engine == "ok" else "error"
    return HealthResponse(
        status=overall,
        postgres=postgres,
        redis=redis_status,
        redis_version=redis_version,
        query_engine=query_engine,
    )
