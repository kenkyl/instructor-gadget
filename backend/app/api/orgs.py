"""An org's internal docs (J3). Thin adapter: the rules live in app/services/org_docs.py."""

from fastapi import APIRouter, Response

from app.auth import CurrentUserDep
from app.deps import Db
from app.services import org_docs
from app.services.org_docs import OrgDocDetail, OrgDocIn, OrgDocSummary, OrgMembershipOut

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
