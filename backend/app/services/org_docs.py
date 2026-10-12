"""Org docs (J3): who may read and add them, and what makes an upload acceptable.

Surface-neutral, like the other services: ownership and role are checked here, so every surface
gets the same rule. Docs are immutable once stored (ADR-0028): a course pins its doc set by hash
when it is created, and an in-place edit would change what a pinned course is grounded in
without changing the hash it was cached under.
"""

import logging
import uuid
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent import sources
from agent.sources import MAX_DOC_CHARS, MAX_SET_CHARS, DocSection, Grounding, SourceDoc
from agent.types import SLUG
from app.auth import CurrentUser
from app.models import Course, CourseScope, Membership, Org, OrgDoc, Role

log = logging.getLogger(__name__)


class OrgMembershipOut(BaseModel):
    slug: str
    name: str
    role: Role


class OrgDocSummary(BaseModel):
    slug: str
    title: str
    section_count: int
    chars: int
    content_hash: str
    created_at: datetime


class OrgDocDetail(OrgDocSummary):
    content_md: str
    sections: list[DocSection]  # the anchors a citation may point at


class OrgDocIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    content_md: str = Field(min_length=1, max_length=MAX_DOC_CHARS)
    slug: str | None = Field(
        default=None,
        pattern=SLUG,
        max_length=100,
        description="Defaults to one made from the title",
    )


def _summary(doc: OrgDoc) -> OrgDocSummary:
    return OrgDocSummary(
        slug=doc.slug,
        title=doc.title,
        section_count=len(doc.sections),
        chars=len(doc.content_md),
        content_hash=doc.content_hash,
        created_at=doc.created_at,
    )


def _detail(doc: OrgDoc) -> OrgDocDetail:
    # JSONB: validate on the way out, don't trust the stored shape.
    return OrgDocDetail(
        **_summary(doc).model_dump(),
        content_md=doc.content_md,
        sections=[DocSection.model_validate(s) for s in doc.sections],
    )


async def my_orgs(db: AsyncSession, user: CurrentUser) -> list[OrgMembershipOut]:
    rows = await db.execute(
        select(Org.slug, Org.name, Membership.role)
        .join(Membership, Membership.org_id == Org.id)
        .where(Membership.user_id == user.id)
        .order_by(Org.name)
    )
    return [OrgMembershipOut(slug=s, name=n, role=r) for s, n, r in rows.all()]


async def member_org(db: AsyncSession, user: CurrentUser, org_slug: str) -> tuple[Org, Role]:
    """The org and the caller's role in it. 404 for a stranger as well as for a missing org:
    don't confirm that an org exists to someone outside it."""
    row = (
        await db.execute(
            select(Org, Membership.role)
            .join(Membership, Membership.org_id == Org.id)
            .where(Org.slug == org_slug, Membership.user_id == user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "org not found")
    return row[0], row[1]


def require_admin(role: Role) -> None:
    if role != Role.admin:
        raise HTTPException(403, "Only org admins can do this.")


async def list_docs(db: AsyncSession, user: CurrentUser, org_slug: str) -> list[OrgDocSummary]:
    org, _ = await member_org(db, user, org_slug)
    docs = await db.scalars(select(OrgDoc).where(OrgDoc.org_id == org.id).order_by(OrgDoc.title))
    return [_summary(d) for d in docs]


async def get_doc(
    db: AsyncSession, user: CurrentUser, org_slug: str, doc_slug: str
) -> OrgDocDetail:
    org, _ = await member_org(db, user, org_slug)
    doc = await db.scalar(select(OrgDoc).where(OrgDoc.org_id == org.id, OrgDoc.slug == doc_slug))
    if doc is None:
        raise HTTPException(404, "doc not found")
    return _detail(doc)


async def create_doc(
    db: AsyncSession, user: CurrentUser, org_slug: str, body: OrgDocIn
) -> tuple[OrgDocDetail, bool]:
    """Store an uploaded doc. Returns (doc, created). The same slug with the same content is
    the same upload again (a double click, a retry) and returns the stored doc; the same slug
    with different content is a 409, because docs never change in place (ADR-0028)."""
    org, role = await member_org(db, user, org_slug)
    require_admin(role)

    content = sources.normalize(body.content_md)
    sections = sources.parse_sections(content)
    if not sections:
        raise HTTPException(
            422,
            "Add at least one heading (a line starting with `#`) so lessons can cite a section.",
        )
    slug = body.slug or sources.doc_slug(body.title)
    digest = sources.content_hash(content)

    existing = await db.scalar(select(OrgDoc).where(OrgDoc.org_id == org.id, OrgDoc.slug == slug))
    if existing is not None:
        if existing.content_hash == digest:
            return _detail(existing), False
        raise HTTPException(
            409,
            f"A doc with the key `{slug}` already exists with different content. Docs don't "
            "change once uploaded, because courses are pinned to the version they were built "
            "on. Upload this one under a new title.",
        )

    doc = OrgDoc(
        org_id=org.id,
        slug=slug,
        title=body.title.strip(),
        content_md=content,
        sections=[s.model_dump() for s in sections],
        content_hash=digest,
    )
    db.add(doc)
    try:
        await db.commit()
    except IntegrityError as err:  # a concurrent upload of the same key won the race
        await db.rollback()
        raise HTTPException(409, f"A doc with the key `{slug}` already exists.") from err
    return _detail(doc), True


async def resolve_doc_set(db: AsyncSession, org_id: uuid.UUID, slugs: list[str]) -> list[OrgDoc]:
    """The docs an org course is grounded in, in the order chosen, deduplicated. Validates the
    whole set against the prompt budget (context stuffing has a ceiling)."""
    wanted = list(dict.fromkeys(slugs))
    if not wanted:
        raise HTTPException(422, "Pick at least one doc to ground the course in.")
    found = {
        d.slug: d
        for d in await db.scalars(
            select(OrgDoc).where(OrgDoc.org_id == org_id, OrgDoc.slug.in_(wanted))
        )
    }
    missing = [s for s in wanted if s not in found]
    if missing:
        raise HTTPException(422, f"Not in this org's docs: {', '.join(missing)}")
    docs = [found[s] for s in wanted]
    total = sum(len(d.content_md) for d in docs)
    if total > MAX_SET_CHARS:
        raise HTTPException(
            422,
            f"These docs are {total:,} characters; a course can be grounded in at most "
            f"{MAX_SET_CHARS:,}. Pick fewer docs.",
        )
    return docs


async def course_grounding(db: AsyncSession, course: Course) -> Grounding | None:
    """The docs an org course's generations are grounded in, composed for the prompt (PC4.2).
    None for a personal course.

    The hash is recomputed from the docs loaded here, which are the docs the model will see.
    The course's stored `doc_set_hash` is what it was created with; they differ only if a doc
    changed under it, which the API forbids and only `make seed` can do (ADR-0028)."""
    if course.scope != CourseScope.org:
        return None
    ids = [uuid.UUID(str(i)) for i in course.doc_ids]
    docs = list(await db.scalars(select(OrgDoc).where(OrgDoc.id.in_(ids))))
    if not docs or len(docs) != len(ids) or course.org_id is None:
        # A doc can't be deleted through the API, so this is a broken course, not a user error.
        raise HTTPException(409, "This course's docs are missing; ask an org admin to rebuild it.")
    grounding = sources.compose(
        str(course.org_id), (SourceDoc(d.slug, d.title, d.content_md) for d in docs)
    )
    if grounding.doc_set_hash != course.doc_set_hash:
        log.warning(
            "course %s: its docs changed since it was created (re-seeded?); lessons are grounded "
            "in, and cached under, the current text",
            course.id,
        )
    return grounding
