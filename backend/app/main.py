"""FastAPI entrypoint. Connections are opened once in the lifespan and shared via app.state."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anthropic import AsyncAnthropic
from fastapi import FastAPI
from redis.asyncio import Redis
from redisvl.utils.vectorize import HFTextVectorizer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent.cache import ExactCache, ensure_index
from agent.guard import IntakeGuard
from agent.llm import LLMClient
from agent.registry import get_registry
from agent.semantic import MODEL as SEMANTIC_MODEL
from agent.semantic import SemanticTier
from app.api import auth, courses, dashboard, health, learning, orgs, skills, trace
from app.config import Settings, get_settings
from app.services.llm_log import DbCallSink

log = logging.getLogger(__name__)


async def _vector_features(
    redis: Redis, settings: Settings, *, cache: bool
) -> tuple[SemanticTier | None, IntakeGuard | None]:
    """The semantic cache tier and the intake guard: both need the local MiniLM model (loaded
    once, shared) and a vector index on Redis DB 0 (ADR-0019). Building them is blocking work
    (model load, FT.CREATE), so it runs in a worker thread. Any failure disables the feature,
    not the app: the exact cache still works and course intake falls back to the model's own
    conduct rules."""
    want_guard = settings.intake_guard_enabled
    want_cache = cache and settings.semantic_cache_enabled
    if not (want_guard or want_cache):
        return None, None
    if redis.connection_pool.connection_kwargs.get("db", 0) != 0:
        log.warning("semantic cache and intake guard off: vector indexes need Redis DB 0")
        return None, None

    def build() -> tuple[SemanticTier | None, IntakeGuard | None]:
        vectorizer = HFTextVectorizer(model=SEMANTIC_MODEL)
        tier = (
            SemanticTier.build(
                settings.redis_url,
                vectorizer=vectorizer,
                distance_threshold=settings.semantic_cache_distance_threshold,
            )
            if want_cache
            else None
        )
        guard = IntakeGuard.build(settings.redis_url, vectorizer) if want_guard else None
        return tier, guard

    try:
        return await asyncio.to_thread(build)
    except Exception:  # broad on purpose: neither feature may stop the app from starting
        log.warning("semantic cache and intake guard off: failed to start", exc_info=True)
        return None, None


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
    semantic, app.state.guard = await _vector_features(
        app.state.redis, settings, cache=bool(api_key)
    )
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
            semantic=semantic,
        )
    app.state.semantic = semantic
    yield
    if semantic is not None:
        await semantic.cache.adisconnect()
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
app.include_router(orgs.router, prefix="/api")
app.include_router(learning.router, prefix="/api")
app.include_router(trace.router, prefix="/api")
