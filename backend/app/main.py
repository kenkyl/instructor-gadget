"""FastAPI entrypoint. Connections are opened once in the lifespan and shared via app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.api import health
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(title="Instructor API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
