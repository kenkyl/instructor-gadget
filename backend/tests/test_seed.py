import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from agent import sources
from app.config import get_settings
from app.models import Membership, Org, OrgDoc, Prototype, Role, User
from seed.seed import seed


async def _seed_twice_and_count() -> dict[str, object]:
    engine = create_async_engine(get_settings().database_url)
    try:
        await seed(engine)
        await seed(engine)  # idempotent: a rerun must not duplicate or fail
        async with engine.connect() as conn:
            users = await conn.scalar(select(func.count()).select_from(User))
            orgs = await conn.scalar(select(func.count()).select_from(Org))
            protos = await conn.scalar(select(func.count()).select_from(Prototype))
            docs = (
                await conn.execute(
                    select(OrgDoc.slug, OrgDoc.content_md, OrgDoc.sections, OrgDoc.content_hash)
                )
            ).all()
            priya_role = await conn.scalar(
                select(Membership.role).join(User).where(User.username == "priya")
            )
    finally:
        await engine.dispose()
    return {
        "users": users,
        "orgs": orgs,
        "protos": protos,
        "priya_role": priya_role,
        "docs": {d.slug: d for d in docs},
    }


def test_seed_is_idempotent() -> None:
    result = asyncio.run(_seed_twice_and_count())
    assert {k: v for k, v in result.items() if k != "docs"} == {
        "users": 3,
        "orgs": 1,
        "protos": 1,
        "priya_role": Role.admin,
    }
    assert sorted(result["docs"]) == [  # type: ignore[arg-type]
        "how-we-ship",
        "on-call-runbook",
        "postmortem-pool-exhaustion",
        "service-map",
    ]


def test_seeded_docs_are_citable_and_within_the_prompt_budget() -> None:
    docs = asyncio.run(_seed_twice_and_count())["docs"]
    assert isinstance(docs, dict)
    for slug, doc in docs.items():
        anchors = [s["anchor"] for s in doc.sections]
        assert len(anchors) >= 5, slug  # something specific to cite
        assert len(set(anchors)) == len(anchors), slug
        # What's stored is what the code would compute again (so an upload and a seed agree),
        # and the hash covers the stored text.
        assert doc.sections == [s.model_dump() for s in sources.parse_sections(doc.content_md)]
        assert doc.content_hash == sources.content_hash(doc.content_md)
        assert len(doc.content_md) <= sources.MAX_DOC_CHARS
    assert sum(len(d.content_md) for d in docs.values()) <= sources.MAX_SET_CHARS
