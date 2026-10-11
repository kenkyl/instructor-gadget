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
    redis.Redis.from_url(TEST_REDIS_URL).flushdb()
    asyncio.run(_seed())


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:  # `with` runs the lifespan (opens and closes connections)
        yield c
