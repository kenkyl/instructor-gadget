"""Test setup: run every test against a separate `instructor_test` database, never the dev DB.

The test DB is created if missing and migrated to head once per session, so tests also
prove that the Alembic migrations apply cleanly from scratch.
"""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

dev_url = make_url(get_settings().database_url)
TEST_DB = f"{dev_url.database}_test"
TEST_URL = dev_url.set(database=TEST_DB).render_as_string(hide_password=False)

# Point the app (and anything reading settings) at the test DB before it's imported.
os.environ["DATABASE_URL"] = TEST_URL
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
