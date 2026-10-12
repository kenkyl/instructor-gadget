"""Org course drafts: pinned to a doc set (ADR-0028), admin-only, and off the personal J1 path."""

from agent.sources import MAX_DOC_CHARS
from tests.test_org_docs import DOC, clean_uploads, login  # noqa: F401  (autouse fixture)

BASE = {
    "config": {"topic": "Technical readiness at Acme AI", "target_level": "intermediate"},
    "mission": {"goal": "Be useful in week one", "expert_means": "I can run an incident"},
}


def org_intake(*slugs: str, org: str = "acme") -> dict:
    return {**BASE, "org_slug": org, "doc_slugs": list(slugs)}


def test_admin_creates_an_org_course_pinned_to_its_docs(client) -> None:
    login(client, "priya")
    res = client.post("/api/courses", json=org_intake("service-map", "on-call-runbook"))
    assert res.status_code == 201
    course = res.json()
    assert (course["scope"], course["org_name"], course["status"]) == ("org", "Acme AI", "draft")
    # Listed in the order chosen, with what the course page shows.
    assert [d["slug"] for d in course["docs"]] == ["service-map", "on-call-runbook"]
    assert all(d["title"] and d["section_count"] >= 5 for d in course["docs"])
    assert len(course["doc_set_hash"]) == 64
    # The admin can open it again; nothing was probed or enrolled.
    again = client.get(f"/api/courses/{course['id']}").json()
    assert again["docs"] == course["docs"] and again["questions"] == []
    assert again["enrollment_id"] is None


def test_the_doc_set_hash_depends_on_the_set_not_the_order(client) -> None:
    login(client, "priya")
    make = lambda *s: client.post("/api/courses", json=org_intake(*s)).json()  # noqa: E731
    ab = make("service-map", "on-call-runbook")
    ba = make("on-call-runbook", "service-map")
    a_only = make("service-map")
    assert ab["doc_set_hash"] == ba["doc_set_hash"]
    assert [d["slug"] for d in ba["docs"]] == ["on-call-runbook", "service-map"]
    assert a_only["doc_set_hash"] != ab["doc_set_hash"]
    # The same doc twice is one doc.
    assert make("service-map", "service-map")["doc_set_hash"] == a_only["doc_set_hash"]


def test_a_personal_course_has_no_docs_and_says_so(client) -> None:
    login(client, "kyle")
    created = client.post("/api/courses", json=BASE).json()
    assert (created["scope"], created["org_name"], created["docs"]) == ("personal", None, [])
    assert created["doc_set_hash"] is None
    # Docs only ground org courses.
    assert (
        client.post("/api/courses", json={**BASE, "doc_slugs": ["service-map"]}).status_code == 422
    )


def test_only_an_org_admin_can_create_an_org_course(client) -> None:
    login(client, "dana")  # a member
    assert client.post("/api/courses", json=org_intake("service-map")).status_code == 403
    login(client, "kyle")  # not in the org
    assert client.post("/api/courses", json=org_intake("service-map")).status_code == 404
    login(client, "priya")
    assert (
        client.post("/api/courses", json=org_intake("service-map", org="nope")).status_code == 404
    )


def test_the_doc_selection_is_validated(client) -> None:
    login(client, "priya")
    none = client.post("/api/courses", json=org_intake())
    assert none.status_code == 422 and "at least one doc" in none.json()["detail"]
    unknown = client.post("/api/courses", json=org_intake("service-map", "nope"))
    assert unknown.status_code == 422 and "nope" in unknown.json()["detail"]


def test_a_doc_set_over_the_prompt_budget_is_refused(client) -> None:
    login(client, "priya")
    slugs = []
    for i in range(3):  # each is within the per-doc limit; together they are not
        body = {"title": f"T big {i}", "content_md": "# Big\n" + "x" * (MAX_DOC_CHARS - 100)}
        res = client.post("/api/orgs/acme/docs", json=body)
        assert res.status_code == 201
        slugs.append(res.json()["slug"])
    assert client.post("/api/courses", json=org_intake(*slugs[:2])).status_code == 201
    over = client.post("/api/courses", json=org_intake(*slugs))
    assert over.status_code == 422 and "Pick fewer docs" in over.json()["detail"]


def test_org_courses_are_the_admins_not_the_learners(client) -> None:
    login(client, "priya")
    course_id = client.post("/api/courses", json=org_intake("service-map")).json()["id"]
    for who in ("dana", "kyle"):
        login(client, who)
        assert client.get(f"/api/courses/{course_id}").status_code == 404


def test_the_personal_flow_does_not_run_on_an_org_course(client, fake_llm) -> None:
    login(client, "priya")
    course_id = client.post("/api/courses", json=org_intake("service-map")).json()["id"]
    for step in ("probe", "assess", "map", "accept"):
        body = {"answers": {}} if step == "assess" else None
        res = client.post(f"/api/courses/{course_id}/{step}", json=body)
        assert res.status_code == 409, step
        assert "no diagnostic probe" in res.json()["detail"]
    assert fake_llm.requests == []  # no model call, no enrollment for the admin
    assert client.get("/api/dashboard").json()["courses"] == []
