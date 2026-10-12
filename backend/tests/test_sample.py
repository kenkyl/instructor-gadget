"""The sample learner state (seed/sample.py) holds the shape the build brief promises. Checked in
memory with the same grading and gate functions; `make reset` loads it into the dev DB."""

from datetime import UTC, datetime, timedelta

from agent import pedagogy, plan
from agent.types import Band, ConceptMap
from app.models import ConceptProgress, ConceptStatus
from seed import sample


def test_the_fixture_maps_are_valid_and_the_org_docs_exist() -> None:
    fixture = sample.load()
    assert set(fixture) == {"incident", "completed", "org"}
    for spec in fixture.values():
        cmap = ConceptMap.model_validate(spec["template_plan"])
        assert plan.structure_errors(cmap.graph(), cmap.sequence) == []
    assert fixture["org"]["doc_slugs"]
    assert fixture["incident"]["assessment"]["result"]["adjustment_message"]


def test_the_incident_history_lands_mid_course_with_a_remediation() -> None:
    cmap = ConceptMap.model_validate(sample.load()["incident"]["template_plan"])
    rows = {
        c.id: ConceptProgress(concept_id=c.id, status=ConceptStatus.locked, attempts=0)
        for c in cmap.concepts
    }
    for cid in pedagogy.initially_unlocked(cmap.graph()):
        rows[cid].status = ConceptStatus.unlocked
    now = datetime.now(UTC)
    for cid, score, days in sample.INCIDENT_HISTORY:
        assert rows[cid].status != ConceptStatus.locked, f"{cid} is graded while locked"
        rows[cid].status = ConceptStatus.in_progress
        sample._grade(rows[cid], score, now - timedelta(days=days))
        sample._gate(cmap, rows)
    new_map, diff = pedagogy.insert_remediation(
        cmap, sample.SHAKY, misconception=sample.MISCONCEPTION, **sample.REMEDY
    )
    remedy = diff.added[0].id
    rows[remedy] = ConceptProgress(concept_id=remedy, status=ConceptStatus.locked, attempts=0)
    sample._gate(new_map, rows)

    complete = [c for c, p in rows.items() if p.status == ConceptStatus.complete]
    assert len(complete) == 4 and len(rows) == 10  # "about 40%"
    assert [c for c, p in rows.items() if pedagogy.is_due(p.due, now)] == [
        "incident-roles-severity"
    ]
    assert rows[sample.SHAKY].band == Band.shaky
    assert rows[sample.SHAKY].status == ConceptStatus.locked  # re-locked behind its remedy
    assert rows[remedy].status == ConceptStatus.unlocked
    assert rows["probe-misconfig-diagnosis"].status == ConceptStatus.locked  # behind the shaky one
