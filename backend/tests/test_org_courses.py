"""Org course drafts: pinned to a doc set (ADR-0028), admin-only, and off the personal J1 path."""

import json
import uuid

from agent.sources import MAX_DOC_CHARS
from tests.llm_fakes import FakeAnthropic, message
from tests.test_courses import GOOD_MAP, IDS, _login, _mapped_course
from tests.test_learning import _events
from tests.test_llm import GOOD_LESSON
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


def test_the_diagnostic_probe_does_not_run_on_an_org_course(client, fake_llm) -> None:
    login(client, "priya")
    course_id = client.post("/api/courses", json=org_intake("service-map")).json()["id"]
    for step in ("probe", "assess"):
        res = client.post(
            f"/api/courses/{course_id}/{step}", json={"answers": {}} if step == "assess" else None
        )
        assert res.status_code == 409, step
        assert "no diagnostic probe" in res.json()["detail"]
    assert fake_llm.requests == []  # no model call, no enrollment for the admin
    assert client.get("/api/dashboard").json()["courses"] == []


# --- the admin template flow (PC4.3, ADR-0004, ADR-0030) ----------------------------------------
def template(client, fake_llm: FakeAnthropic, *slugs: str) -> str:
    """An org course with a generated (not yet accepted) template map."""
    login(client, "priya")
    course_id = client.post("/api/courses", json=org_intake(*(slugs or ("service-map",)))).json()[
        "id"
    ]
    fake_llm.reply(message(GOOD_MAP))
    assert client.post(f"/api/courses/{course_id}/map").status_code == 200
    return course_id


def test_the_template_map_comes_from_the_docs_with_no_assessment(client, fake_llm) -> None:
    login(client, "priya")
    course_id = client.post(
        "/api/courses", json=org_intake("service-map", "on-call-runbook")
    ).json()["id"]
    fake_llm.reply(message(GOOD_MAP))

    detail = client.post(f"/api/courses/{course_id}/map").json()

    assert (detail["status"], detail["concept_map"]["sequence"]) == ("mapped", IDS)
    request = fake_llm.requests[-1]
    # Docs first, so they are the same prefix for every call on this course; but no citation
    # rules: a concept map has nothing to cite (ADR-0030).
    assert request["system"].startswith("# Source documents\n\n<documents>")
    assert '<document slug="on-call-runbook"' in request["system"]
    assert "# Grounding rules" not in request["system"]
    assert "When source documents are given" in request["system"]
    sent = json.loads(request["messages"][0]["content"])
    assert (sent["assessed_level"], sent["gaps"]) == ("intermediate", [])  # the cohort's level
    assert sent["target_minutes"] == 180
    # Generating twice returns the stored template.
    client.post(f"/api/courses/{course_id}/map")
    assert len(fake_llm.requests) == 1


def test_a_personal_map_is_not_grounded(client, fake_llm) -> None:
    _login(client, "kyle")
    _mapped_course(client, fake_llm)
    system = fake_llm.requests[-1]["system"]
    assert "# Source documents" not in system and "<document slug=" not in system


def test_the_template_can_be_edited_then_accepted_without_enrolling_the_admin(
    client, fake_llm
) -> None:
    course_id = template(client, fake_llm)
    cut = client.delete(f"/api/courses/{course_id}/map/concepts/ttls").json()
    assert "ttls" not in [c["id"] for c in cut["concept_map"]["concepts"]]

    accepted = client.post(f"/api/courses/{course_id}/accept").json()

    assert accepted["status"] == "active"
    assert accepted["enrollment_id"] is None  # a template, not the admin's course
    assert client.get("/api/dashboard").json()["courses"] == []
    # After accept it is only ever copied: the template can't be edited under learners.
    assert client.delete(f"/api/courses/{course_id}/map/concepts/eviction").status_code == 409
    assert client.post(f"/api/courses/{course_id}/accept").json()["status"] == "active"


def test_a_template_must_be_accepted_before_it_is_assigned(client, fake_llm) -> None:
    course_id = template(client, fake_llm)
    members = client.get(f"/api/courses/{course_id}/assignments").json()
    assert members["assignable"] is False
    dana = next(m for m in members["members"] if m["username"] == "dana")
    res = client.post(f"/api/courses/{course_id}/assign", json={"user_ids": [dana["user_id"]]})
    assert res.status_code == 409 and "Accept the course template" in res.json()["detail"]


def _accepted_and_assigned(client, fake_llm) -> tuple[str, str]:
    course_id = template(client, fake_llm)
    client.post(f"/api/courses/{course_id}/accept")
    members = client.get(f"/api/courses/{course_id}/assignments").json()["members"]
    dana = next(m for m in members if m["username"] == "dana")
    res = client.post(f"/api/courses/{course_id}/assign", json={"user_ids": [dana["user_id"]]})
    assert res.status_code == 200
    return course_id, dana["user_id"]


def test_assigning_gives_the_learner_their_own_copy_of_the_template(client, fake_llm) -> None:
    course_id, dana_id = _accepted_and_assigned(client, fake_llm)

    view = client.get(f"/api/courses/{course_id}/assignments").json()
    assert view["assignable"] is True
    by_name = {m["username"]: m for m in view["members"]}
    assert by_name["priya"]["enrollment_id"] is None  # the admin isn't a learner of it
    dana = by_name["dana"]
    assert dana["enrollment_id"] and dana["status"] == "active"
    assert (dana["concepts_total"], dana["concepts_complete"]) == (6, 0)

    login(client, "dana")
    dash = client.get("/api/dashboard").json()["courses"]
    assert [(c["enrollment_id"], c["scope"], c["org_name"], c["concepts_total"]) for c in dash] == [
        (dana["enrollment_id"], "org", "Acme AI", 6)
    ]
    detail = client.get(f"/api/enrollments/{dana['enrollment_id']}").json()
    assert detail["plan_version"] == 1
    assert [p["concept_id"] for p in detail["progress"]][:2] == ["cache-aside", "ttls"]
    plans = client.get(f"/api/enrollments/{dana['enrollment_id']}/plans").json()
    assert [(p["version"], p["trigger"]) for p in plans] == [(1, "assignment")]
    # The learner is not the admin: the template itself stays the admin's.
    assert client.get(f"/api/courses/{course_id}").status_code == 404
    assert client.get(f"/api/courses/{course_id}/assignments").status_code == 404
    assert (
        client.post(f"/api/courses/{course_id}/assign", json={"user_ids": [dana_id]}).status_code
        == 404
    )


def test_assigning_twice_changes_nothing_and_outsiders_are_refused(client, fake_llm) -> None:
    course_id, dana_id = _accepted_and_assigned(client, fake_llm)
    login(client, "priya")
    before = client.get(f"/api/courses/{course_id}/assignments").json()

    again = client.post(f"/api/courses/{course_id}/assign", json={"user_ids": [dana_id, dana_id]})
    assert again.status_code == 200 and again.json() == before

    stranger = client.post(
        f"/api/courses/{course_id}/assign", json={"user_ids": [str(uuid.uuid4())]}
    )
    assert stranger.status_code == 422
    assert client.post(f"/api/courses/{course_id}/assign", json={"user_ids": []}).status_code == 422


def test_a_personal_course_cannot_be_assigned(client, fake_llm) -> None:
    login(client, "kyle")
    course_id = client.post("/api/courses", json=BASE).json()["id"]
    assert client.get(f"/api/courses/{course_id}/assignments").status_code == 409


def test_an_assigned_learner_gets_a_lesson_grounded_in_the_docs(client, fake_llm) -> None:
    """The first org lesson end to end: assignment → enrollment → lesson from the pinned docs."""
    course_id, _ = _accepted_and_assigned(client, fake_llm)
    login(client, "dana")
    eid = client.get("/api/dashboard").json()["courses"][0]["enrollment_id"]
    grounded = {
        **GOOD_LESSON,
        "not_in_docs": [
            {"point": "How a cache stampede is triaged here", "general_knowledge": None}
        ],
    }
    fake_llm.reply(message(grounded))

    res = client.post(f"/api/enrollments/{eid}/concepts/cache-aside/lesson")

    assert res.status_code == 200
    kind, done = _events(res.text)[-1]
    assert kind == "done" and done["lesson"]["content"]["not_in_docs"][0]["point"]
    system = fake_llm.requests[-1]["system"]
    assert system.startswith("# Source documents\n\n<documents>")
    assert '<document slug="service-map"' in system and "# Grounding rules" in system


def test_the_admin_sees_the_cache_impact_across_the_org_without_excerpts(client, fake_llm) -> None:
    course_id, _ = _accepted_and_assigned(client, fake_llm)
    login(client, "dana")
    eid = client.get("/api/dashboard").json()["courses"][0]["enrollment_id"]
    fake_llm.reply(
        message({**GOOD_LESSON, "not_in_docs": [{"point": "x", "general_knowledge": None}]})
    )
    client.post(f"/api/enrollments/{eid}/concepts/cache-aside/lesson")

    login(client, "priya")
    res = client.get("/api/orgs/acme/impact")
    assert res.status_code == 200
    body = res.json()
    assert body["org_name"] == "Acme AI"
    # priya's map call plus dana's lesson call, both on this org course.
    assert body["impact"]["calls"] == 2 and body["impact"]["spent_usd"] > 0
    assert [(c["course_id"], c["learners"]) for c in body["courses"]] == [(course_id, 1)]
    assert body["learners"][-1]["display_name"].startswith("Dana")
    # Counts and dollars only: no prompt or response text anywhere in the payload.
    assert "excerpt" not in json.dumps(body)

    login(client, "dana")
    assert client.get("/api/orgs/acme/impact").status_code == 403
    login(client, "kyle")
    assert client.get("/api/orgs/acme/impact").status_code == 404


def test_the_admin_lists_the_org_courses_they_manage(client, fake_llm) -> None:
    course_id, _ = _accepted_and_assigned(client, fake_llm)
    login(client, "priya")
    res = client.get("/api/orgs/acme/courses")
    assert res.status_code == 200
    assert [(c["course_id"], c["status"], c["assigned_count"]) for c in res.json()] == [
        (course_id, "active", 1)
    ]
    assert res.json()[0]["doc_count"] >= 1

    login(client, "dana")
    assert client.get("/api/orgs/acme/courses").status_code == 403
    login(client, "kyle")
    assert client.get("/api/orgs/acme/courses").status_code == 404
