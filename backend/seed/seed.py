"""Idempotent seed: the sample org, its users, memberships and the seeded prototypes.
Safe to run repeatedly.

Run with `make seed`. Course/learner sample state is added at CP6.
"""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.models import Membership, Org, Prototype, Role, User

ORGS = [{"slug": "acme", "name": "Acme AI"}]

USERS = [
    {"username": "kyle", "display_name": "Kyle (individual learner)"},
    {"username": "dana", "display_name": "Dana (new SRE at Acme)"},
    {"username": "priya", "display_name": "Priya (Acme eng manager)"},
]

MEMBERSHIPS = [  # (username, org slug, role)
    ("dana", "acme", Role.member),
    ("priya", "acme", Role.admin),
]


# Hand-built, hand-checked prototypes (spec §4.5; live generation is P1+). Each HTML file is
# self-contained and only ever rendered in a sandboxed iframe. Which lessons show one is decided
# in app/services/prototypes.py.
PROTOTYPE_DIR = Path(__file__).parent / "prototypes"
PROTOTYPES = [
    {
        "slug": "conn-pool-sim",
        "concept_type": "systems",
        "title": "Connection-pool exhaustion simulator",
    },
]


async def seed(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:  # one transaction: all or nothing
        # ON CONFLICT DO UPDATE makes reruns converge to the same state instead of failing.
        for org in ORGS:
            stmt = insert(Org).values(**org)
            await conn.execute(stmt.on_conflict_do_update(index_elements=["slug"], set_=org))
        for user in USERS:
            stmt = insert(User).values(**user)
            await conn.execute(stmt.on_conflict_do_update(index_elements=["username"], set_=user))

        org_ids = dict((await conn.execute(select(Org.slug, Org.id))).all())
        user_ids = dict((await conn.execute(select(User.username, User.id))).all())
        for username, org_slug, role in MEMBERSHIPS:
            stmt = insert(Membership).values(
                user_id=user_ids[username], org_id=org_ids[org_slug], role=role
            )
            await conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["user_id", "org_id"], set_={"role": role}
                )
            )
        for proto in PROTOTYPES:
            values = {**proto, "html": (PROTOTYPE_DIR / f"{proto['slug']}.html").read_text()}
            stmt = insert(Prototype).values(**values)
            await conn.execute(stmt.on_conflict_do_update(index_elements=["slug"], set_=values))


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        await seed(engine)
    finally:
        await engine.dispose()
    print(
        f"Seeded {len(ORGS)} org, {len(USERS)} users, {len(MEMBERSHIPS)} memberships, "
        f"{len(PROTOTYPES)} prototype."
    )


if __name__ == "__main__":
    asyncio.run(main())
