"""Org docs through the API: who can read and upload, and what an upload must satisfy."""

import asyncio
from collections.abc import Iterator

import pytest
import redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine

from agent.sources import MAX_DOC_CHARS
from app.config import get_settings
from app.models import Course, OrgDoc

SEEDED = ["how-we-ship", "on-call-runbook", "postmortem-pool-exhaustion", "service-map"]
DOC = (
    "# Staging access\n\n## Getting in\n\nUse the VPN.\n\n## Resetting data\n\nAsk in `#staging`.\n"
)


def login(client, username: str) -> None:
    assert client.post("/api/auth/login", json={"username": username}).status_code == 200


async def _cleanup() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(delete(Course).where(Course.scope == "org"))
            await conn.execute(delete(OrgDoc).where(OrgDoc.slug.like("t-%")))
    finally:
        await engine.dispose()
    # Assigned learners' dashboards were cached: a deleted course must not linger in them.
    r = redis.Redis.from_url(get_settings().redis_url)
    keys = list(r.scan_iter("dash:*"))
    if keys:
        r.unlink(*keys)


@pytest.fixture(autouse=True)
def clean_uploads() -> Iterator[None]:
    """Uploads and org courses made by a test don't outlive it: the seed tests count docs."""
    yield
    asyncio.run(_cleanup())


def test_docs_need_login(client) -> None:
    assert client.get("/api/orgs/acme/docs").status_code == 401
    assert client.get("/api/orgs").status_code == 401


def test_orgs_lists_membership_and_role(client) -> None:
    login(client, "priya")
    assert client.get("/api/orgs").json() == [{"slug": "acme", "name": "Acme AI", "role": "admin"}]
    login(client, "dana")
    assert client.get("/api/orgs").json()[0]["role"] == "member"
    login(client, "kyle")
    assert client.get("/api/orgs").json() == []


def test_a_member_lists_and_reads_the_seeded_docs(client) -> None:
    login(client, "dana")
    docs = client.get("/api/orgs/acme/docs").json()
    assert sorted(d["slug"] for d in docs) == SEEDED
    runbook = next(d for d in docs if d["slug"] == "on-call-runbook")
    assert runbook["section_count"] >= 5 and runbook["chars"] > 0
    assert "content_md" not in runbook  # the list is light

    one = client.get("/api/orgs/acme/docs/on-call-runbook").json()
    assert one["content_md"].startswith("# On-call runbook")
    assert {"anchor": "severity-levels", "heading": "Severity levels"} in one["sections"]
    assert one["content_hash"] == runbook["content_hash"]


def test_strangers_and_missing_things_are_404(client) -> None:
    login(client, "kyle")  # not a member of acme
    assert client.get("/api/orgs/acme/docs").status_code == 404
    assert client.get("/api/orgs/acme/docs/service-map").status_code == 404
    assert client.get("/api/orgs/nope/docs").status_code == 404  # same answer: no existence leak
    login(client, "dana")
    assert client.get("/api/orgs/acme/docs/nope").status_code == 404


def test_only_admins_upload(client) -> None:
    body = {"title": "T staging access", "content_md": DOC}
    login(client, "dana")
    assert client.post("/api/orgs/acme/docs", json=body).status_code == 403
    login(client, "kyle")
    assert client.post("/api/orgs/acme/docs", json=body).status_code == 404

    login(client, "priya")
    created = client.post("/api/orgs/acme/docs", json=body)
    assert created.status_code == 201
    doc = created.json()
    assert doc["slug"] == "t-staging-access"  # made from the title
    assert [s["anchor"] for s in doc["sections"]] == [
        "staging-access",
        "getting-in",
        "resetting-data",
    ]
    # Members see it straight away.
    login(client, "dana")
    assert client.get("/api/orgs/acme/docs/t-staging-access").status_code == 200


def test_uploading_the_same_doc_again_is_the_same_doc(client) -> None:
    login(client, "priya")
    body = {"title": "T repeat", "content_md": DOC}
    first = client.post("/api/orgs/acme/docs", json=body)
    # Windows line endings are the same document once normalized.
    again = client.post(
        "/api/orgs/acme/docs",
        json={**body, "content_md": DOC.replace("\n", "\r\n")},
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["content_hash"] == first.json()["content_hash"]
    docs = client.get("/api/orgs/acme/docs").json()
    assert [d["slug"] for d in docs].count("t-repeat") == 1


def test_a_doc_never_changes_in_place(client) -> None:
    login(client, "priya")
    body = {"title": "T pinned", "content_md": DOC}
    assert client.post("/api/orgs/acme/docs", json=body).status_code == 201
    edited = client.post("/api/orgs/acme/docs", json={**body, "content_md": DOC + "\n## New\nx\n"})
    assert edited.status_code == 409
    assert "new title" in edited.json()["detail"]
    # The seeded docs are protected the same way.
    seeded = client.post(
        "/api/orgs/acme/docs",
        json={"title": "On-call runbook", "content_md": DOC},
    )
    assert seeded.status_code == 409


def test_upload_rules(client) -> None:
    login(client, "priya")
    post = lambda **kw: client.post("/api/orgs/acme/docs", json={"title": "T rules", **kw})  # noqa: E731

    no_headings = post(content_md="Just a paragraph with no structure at all.")
    assert no_headings.status_code == 422
    assert "heading" in no_headings.json()["detail"]
    # A `#` line inside a code fence isn't a heading.
    assert post(content_md="```\n# not a heading\n```\n").status_code == 422

    assert post(content_md="").status_code == 422
    assert post(content_md="# x\n" + "y" * MAX_DOC_CHARS).status_code == 422  # too big
    assert post(content_md=DOC, slug="Not A Slug").status_code == 422
    assert (
        client.post("/api/orgs/acme/docs", json={"title": "", "content_md": DOC}).status_code == 422
    )

    explicit = post(content_md=DOC, slug="t-explicit-key")
    assert explicit.status_code == 201 and explicit.json()["slug"] == "t-explicit-key"
