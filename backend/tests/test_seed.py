import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import Membership, Org, Role, User
from seed.seed import seed


async def _seed_twice_and_count() -> dict[str, object]:
    engine = create_async_engine(get_settings().database_url)
    try:
        await seed(engine)
        await seed(engine)  # idempotent: a rerun must not duplicate or fail
        async with engine.connect() as conn:
            users = await conn.scalar(select(func.count()).select_from(User))
            orgs = await conn.scalar(select(func.count()).select_from(Org))
            priya_role = await conn.scalar(
                select(Membership.role).join(User).where(User.username == "priya")
            )
    finally:
        await engine.dispose()
    return {"users": users, "orgs": orgs, "priya_role": priya_role}


def test_seed_is_idempotent() -> None:
    result = asyncio.run(_seed_twice_and_count())
    assert result == {"users": 3, "orgs": 1, "priya_role": Role.admin}
