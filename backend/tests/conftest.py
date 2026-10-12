"""Test setup: isolated stores so tests never touch dev data.

- Postgres: a separate `instructor_test` database, recreated and migrated to head each session
  (which also proves the Alembic migrations apply cleanly from scratch).
- Redis: logical DB 15 (dev uses 0), flushed at the start of each session.
"""

import asyncio
import os

import pytest
import redis
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from seed.seed import seed

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

dev_url = make_url(get_settings().database_url)
TEST_DB = f"{dev_url.database}_test"
TEST_URL = dev_url.set(database=TEST_DB).render_as_string(hide_password=False)

TEST_REDIS_URL = get_settings().redis_url.rsplit("/", 1)[0] + "/15"

# Point the app (and anything reading settings) at the test stores before it's imported.
os.environ["DATABASE_URL"] = TEST_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
# Tests never call the real model: blank the key from .env (env vars beat the .env file).
# Tests that need an LLM override get_llm with a fake client (tests/llm_fakes.py).
os.environ["ANTHROPIC_API_KEY"] = ""
get_settings.cache_clear()


async def _recreate_test_db() -> None:
    admin = create_async_engine(
        dev_url.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",  # CREATE/DROP DATABASE can't run inside a transaction
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_recreate_test_db())
    cfg = Config(toml_file=os.path.join(BACKEND_DIR, "pyproject.toml"))
    cfg.attributes["database_url"] = TEST_URL
    command.upgrade(cfg, "head")


async def _seed() -> None:
    engine = create_async_engine(TEST_URL)
    try:
        await seed(engine)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_stores(test_database: None) -> None:
    # Delete DB 15's keys one by one, never FLUSHDB: on Redis 8, FLUSHDB on *any* DB drops every
    # search index, including the dev server's on DB 0 (idx:llm_exact, idx:llm_semantic,
    # idx:intake_guard), so `make test` would silently break a running `make dev`.
    r = redis.Redis.from_url(TEST_REDIS_URL)
    keys = list(r.scan_iter(count=1000))
    if keys:
        r.unlink(*keys)
    asyncio.run(_seed())


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:  # `with` runs the lifespan (opens and closes connections)
        yield c


@pytest.fixture
def fake_llm():
    """Swap in a fake model behind the real wrapper and DB sink. Tests queue its replies with
    `fake_llm.reply(...)`. No exact cache here: API tests see `miss`/`bypass` deterministically."""
    from fastapi import Request

    from agent.llm import LLMClient
    from agent.registry import get_registry
    from app.deps import get_llm
    from app.main import app
    from app.services.llm_log import DbCallSink
    from tests.llm_fakes import FakeAnthropic

    fake = FakeAnthropic()

    def override(request: Request) -> LLMClient:
        sink = DbCallSink(request.app.state.sessionmaker)
        return LLMClient(fake.as_client(), get_registry(), sink, model="claude-sonnet-5-5")

    app.dependency_overrides[get_llm] = override
    yield fake
    app.dependency_overrides.pop(get_llm, None)
