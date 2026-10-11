"""GET /api/health: is every dependency the app needs reachable?"""

import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: CheckStatus
    postgres: CheckStatus
    redis: CheckStatus
    redis_version: str | None
    query_engine: CheckStatus
    postgres_version: str | None


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    postgres: CheckStatus = "error"
    postgres_version: str | None = None
    try:
        async with request.app.state.engine.connect() as conn:
            result = await conn.execute(text("SHOW server_version"))
            postgres_version = result.scalar()
        postgres = "ok"
    except Exception:
        # Report "error" to the caller, but log why: a code bug must not look like an outage.
        logger.exception("health check: postgres failed")

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
        logger.exception("health check: redis failed")

    overall: CheckStatus = "ok" if postgres == redis_status == query_engine == "ok" else "error"
    return HealthResponse(
        status=overall,
        postgres=postgres,
        postgres_version=postgres_version,
        redis=redis_status,
        redis_version=redis_version,
        query_engine=query_engine,
    )
