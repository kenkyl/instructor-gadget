"""FastAPI entrypoint. Connections are opened once in the lifespan and shared via app.state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anthropic import AsyncAnthropic
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent.cache import ExactCache, ensure_index
from agent.llm import LLMClient
from agent.registry import get_registry
from app.api import auth, courses, dashboard, health, learning, skills
from app.config import get_settings
from app.services.llm_log import DbCallSink


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = get_registry()  # load + validate every skill now: a malformed one fails startup
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await ensure_index(app.state.redis)  # idx:llm_exact (exact LLM cache inventory)
    # No key (e.g. CI): the app still starts; LLM endpoints answer 503 via get_llm.
    anthropic_client: AsyncAnthropic | None = None
    app.state.llm = None
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if api_key:
        anthropic_client = AsyncAnthropic(
            api_key=api_key,
            timeout=settings.anthropic_timeout_seconds,
        )
        app.state.llm = LLMClient(
            anthropic_client,
            registry,
            DbCallSink(app.state.sessionmaker),
            model=settings.anthropic_model,
            cache=ExactCache(app.state.redis),
        )
    yield
    if anthropic_client is not None:
        await anthropic_client.close()
    await app.state.redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(title="Instructor API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(courses.router, prefix="/api")
app.include_router(learning.router, prefix="/api")
