"""An org's internal docs (J3). Thin adapter: the rules live in app/services/org_docs.py."""

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.deps import Db
from app.services import courses, org_docs
from app.services.courses import OrgCourseSummary
from app.services.org_docs import OrgDocDetail, OrgDocIn, OrgDocSummary, OrgMembershipOut
from app.services.trace import OrgImpactResponse, get_org_impact

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.get("")
async def my_orgs(user: CurrentUserDep, db: Db) -> list[OrgMembershipOut]:
    """The orgs the caller belongs to, with their role (who may upload docs and build courses)."""
    return await org_docs.my_orgs(db, user)


@router.get("/{org_slug}/docs")
async def list_docs(org_slug: str, user: CurrentUserDep, db: Db) -> list[OrgDocSummary]:
    return await org_docs.list_docs(db, user, org_slug)


@router.get("/{org_slug}/docs/{doc_slug}")
async def get_doc(org_slug: str, doc_slug: str, user: CurrentUserDep, db: Db) -> OrgDocDetail:
    return await org_docs.get_doc(db, user, org_slug, doc_slug)


@router.post("/{org_slug}/docs", status_code=201)
async def upload_doc(
    org_slug: str, body: OrgDocIn, response: Response, user: CurrentUserDep, db: Db
) -> OrgDocDetail:
    """Add a doc (admins only). Uploading the same doc again returns it with a 200."""
    doc, created = await org_docs.create_doc(db, user, org_slug, body)
    if not created:
        response.status_code = 200
    return doc


@router.get("/{org_slug}/impact")
async def impact(org_slug: str, user: CurrentUserDep, db: Db) -> OrgImpactResponse:
    """What the cache did across the org's courses: calls, hit rate, $ spent and saved, per course
    and per learner (admins only; counts and dollars, never excerpts)."""
    return await get_org_impact(db, user, org_slug)


@router.get("/{org_slug}/courses")
async def org_courses(org_slug: str, user: CurrentUserDep, db: Db) -> list[OrgCourseSummary]:
    """The org's courses, drafts and templates included, with doc and learner counts (admins
    only). The admin's way back to a template, which isn't on their dashboard."""
    return await courses.list_org_courses(db, user, org_slug)
