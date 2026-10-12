"""Sample learner state (build brief §7), so a fresh install shows courses mid-flight with no
model calls. Run by `make reset` (after `make seed`); refuses to run twice.

The maps in `sample/courses.yaml` are real model output (two exported from development runs,
one generated for this file), so they read like what the product makes. The state is built
through the same services the API uses (create, accept, assign), and every mastery, band and
review date comes from `agent/pedagogy.py` applied to a scripted score history, so nothing
here can disagree with the rules:

- kyle, "Incident investigation fundamentals for on-call engineers": 4 of 10 concepts done
  (one due for review), one shaky with a logged misconception, which inserted a remediation
  (plan v1 → v2) and re-locked it and the concept behind it.
- kyle, "Redis data structures": complete, with its badge; two concepts due for review.
- priya's Acme AI org course: the template accepted and assigned to dana, who hasn't started,
  so the admin flow shows without a ~40 s template build.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from agent import pedagogy
from agent.pedagogy import Score
from agent.types import ConceptMap, Misbelief, StatusChange
from app.auth import CurrentUser
from app.config import get_settings
from app.models import (
    Assessment,
    ConceptProgress,
    ConceptStatus,
    Course,
    CourseStatus,
    Enrollment,
    EnrollmentStatus,
    Misconception,
    PlanTrigger,
    PlanVersion,
    User,
)
from app.services import courses
from app.services.courses import CourseIntake
from app.services.dashboard import invalidate_dashboard

FIXTURE = Path(__file__).parent / "sample/courses.yaml"

# (concept id, score, days ago). Scores go through pedagogy like a graded quiz; the first one is
# old enough that FSRS has made it due.
INCIDENT_HISTORY: list[tuple[str, Score, float]] = [
    ("incident-roles-severity", 3, 30),
    ("evidence-before-restart", 3, 1),
    ("golden-signals-triage", 4, 1),
    ("utilization-vs-saturation", 3, 0.5),
    ("liveness-readiness-probes", 1, 0.1),
]
SHAKY = "liveness-readiness-probes"
MISCONCEPTION = Misbelief(
    label="liveness failure = out of the load balancer",
    note="Thinks a failing liveness probe takes the pod out of the Service's endpoints, when it "
    "restarts the container; readiness is what controls traffic.",
)
REMEDY = {
    "title": "What a failing liveness probe actually does",
    "mastery_statement": "You can say what happens to a pod's traffic and to its container when "
    "liveness fails, and when readiness fails",
    "angle": "Follow one pod through both failures on a timeline, instead of comparing "
    "definitions side by side",
}
WHY = (
    "You scored 1 on Liveness vs. readiness probes: you said a failing liveness probe takes the "
    "pod out of the load balancer. That's readiness; a failing liveness probe restarts the "
    "container. A short remediation from a different angle comes first, then you retake the quiz."
)


def load() -> dict[str, Any]:
    return yaml.safe_load(FIXTURE.read_text())


async def _user(db: AsyncSession, username: str) -> CurrentUser:
    u = await db.scalar(select(User).where(User.username == username))
    assert u is not None, f"run `make seed` first ({username} missing)"
    return CurrentUser(id=u.id, username=u.username, display_name=u.display_name)


async def _mapped_course(
    db: AsyncSession, user: CurrentUser, spec: dict[str, Any], org_slug: str | None = None
) -> Course:
    """A course at `mapped`, as if its map had just been generated."""
    intake = CourseIntake.model_validate(
        {
            "config": spec["config"],
            "mission": spec["mission"],
            "org_slug": org_slug,
            "doc_slugs": spec.get("doc_slugs", []),
        }
    )
    course = await courses.create_course(db, user, intake)
    course.title = spec["title"]
    course.template_plan = ConceptMap.model_validate(spec["template_plan"]).model_dump(mode="json")
    course.status = CourseStatus.mapped
    if a := spec.get("assessment"):
        db.add(
            Assessment(
                course_id=course.id,
                user_id=user.id,
                probe=a["probe"],
                answers=a["answers"],
                result=a["result"],
                assessed_level=a["result"]["assessed_level"],
                confidence=a["result"]["confidence"],
            )
        )
    await db.commit()
    return course


async def _enrollment(db: AsyncSession, course: Course, user: CurrentUser) -> Enrollment:
    e = await db.scalar(
        select(Enrollment).where(Enrollment.course_id == course.id, Enrollment.user_id == user.id)
    )
    assert e is not None
    return e


def _grade(p: ConceptProgress, score: Score, at: datetime) -> None:
    """What a submitted quiz does to a progress row (app/services/quiz.py), minus the model."""
    mastery = pedagogy.update_mastery(p.mastery, score)
    p.mastery, p.band = mastery, pedagogy.band(mastery)
    p.last_score = score
    p.attempts += 1
    p.last_attempt_at = at
    card = pedagogy.schedule_review(
        pedagogy.load_card(p.fsrs_card) if p.fsrs_card else None, score, at
    )
    p.fsrs_card = dict(card.to_dict())
    p.due = card.due
    if pedagogy.at_least(p.band, pedagogy.UNLOCK_BAND):
        p.status = ConceptStatus.complete


def _gate(cmap: ConceptMap, rows: dict[str, ConceptProgress]) -> list[StatusChange]:
    """The prerequisite gate over every open concept (quiz._apply_gate, with no overrides)."""
    passes = pedagogy.unlocked(cmap.graph(), {cid: p.band for cid, p in rows.items()})
    changes = []
    for cid in cmap.sequence:
        p = rows[cid]
        if p.status == ConceptStatus.complete:
            continue
        new = ConceptStatus.unlocked if cid in passes else ConceptStatus.locked
        if p.status == ConceptStatus.in_progress and cid in passes:
            new = ConceptStatus.in_progress
        if new != p.status:
            changes.append(StatusChange(concept_id=cid, old=p.status, new=new))
            p.status = new
    return changes


async def _rows(db: AsyncSession, enrollment_id: uuid.UUID) -> dict[str, ConceptProgress]:
    rows = await db.scalars(
        select(ConceptProgress).where(ConceptProgress.enrollment_id == enrollment_id)
    )
    return {p.concept_id: p for p in rows}


async def _backdate(db: AsyncSession, enrollment: Enrollment, at: datetime) -> None:
    enrollment.created_at = at
    await db.execute(
        update(PlanVersion)
        .where(PlanVersion.enrollment_id == enrollment.id, PlanVersion.version == 1)
        .values(created_at=at)
    )


async def incident_course(db: AsyncSession, redis: Redis, kyle: CurrentUser, spec: dict) -> str:
    now = datetime.now(UTC)
    course = await _mapped_course(db, kyle, spec)
    await courses.accept_map(db, redis, kyle, course)
    enr = await _enrollment(db, course, kyle)
    await _backdate(db, enr, now - timedelta(days=31))
    cmap = ConceptMap.model_validate(spec["template_plan"])
    rows = await _rows(db, enr.id)
    for cid, score, days in INCIDENT_HISTORY:
        rows[cid].status = ConceptStatus.in_progress  # the learner opened its lesson
        _grade(rows[cid], score, now - timedelta(days=days))
        _gate(cmap, rows)

    # The 1 on the probes quiz: log the belief, insert a remediation (plan v2), re-lock.
    db.add(
        Misconception(
            enrollment_id=enr.id,
            concept_id=SHAKY,
            label=MISCONCEPTION.label,
            note=MISCONCEPTION.note,
            source_question="What happens to a pod's traffic when its liveness probe fails?",
        )
    )
    new_map, diff = pedagogy.insert_remediation(cmap, SHAKY, misconception=MISCONCEPTION, **REMEDY)
    remedy = ConceptProgress(
        enrollment_id=enr.id, concept_id=diff.added[0].id, status=ConceptStatus.locked, attempts=0
    )
    db.add(remedy)
    rows[remedy.concept_id] = remedy
    diff.status_changes = _gate(new_map, rows)
    db.add(
        PlanVersion(
            enrollment_id=enr.id,
            version=2,
            plan=new_map.model_dump(mode="json"),
            diff=diff.model_dump(mode="json"),
            trigger=PlanTrigger.quiz_result,
            reason=WHY,
            rule=pedagogy.Rule.insert_remediation.value,
            created_at=now - timedelta(days=0.1),
        )
    )
    enr.current_plan_version = 2
    await db.commit()
    await invalidate_dashboard(redis, kyle.id)
    return str(enr.id)


async def completed_course(db: AsyncSession, redis: Redis, kyle: CurrentUser, spec: dict) -> str:
    now = datetime.now(UTC)
    course = await _mapped_course(db, kyle, spec)
    await courses.accept_map(db, redis, kyle, course)
    enr = await _enrollment(db, course, kyle)
    await _backdate(db, enr, now - timedelta(days=40))  # listed below the active course
    cmap = ConceptMap.model_validate(spec["template_plan"])
    rows = await _rows(db, enr.id)
    # Mostly 4s over the last week (FSRS: next review in 8 days), two 3s (2 days) now due.
    for n, cid in enumerate(cmap.sequence):
        _grade(rows[cid], 3 if n in (1, 4) else 4, now - timedelta(days=7 - n * 0.8))
        _gate(cmap, rows)
    assert pedagogy.course_complete({cid: p.band for cid, p in rows.items()})
    enr.status = EnrollmentStatus.complete
    enr.completed_at = now - timedelta(days=7 - (len(cmap.sequence) - 1) * 0.8)
    await db.commit()
    await invalidate_dashboard(redis, kyle.id)
    return str(enr.id)


async def org_course(
    db: AsyncSession, redis: Redis, priya: CurrentUser, dana: CurrentUser, spec: dict
) -> str:
    course = await _mapped_course(db, priya, spec, org_slug="acme")
    await courses.accept_map(db, redis, priya, course)  # an assignable template, nobody enrolled
    await courses.assign_course(db, redis, priya, course, [dana.id])
    return str(course.id)


async def sample(db: AsyncSession, redis: Redis) -> dict[str, str]:
    fixture = load()
    kyle, priya, dana = [await _user(db, u) for u in ("kyle", "priya", "dana")]
    if await db.scalar(select(Course).where(Course.title == fixture["incident"]["title"])):
        raise SystemExit("Sample data is already loaded. `make reset` rebuilds it from scratch.")
    return {
        "kyle incident course (enrollment)": await incident_course(
            db, redis, kyle, fixture["incident"]
        ),
        "kyle completed course (enrollment)": await completed_course(
            db, redis, kyle, fixture["completed"]
        ),
        "Acme AI org course (course)": await org_course(db, redis, priya, dana, fixture["org"]),
    }


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            for what, id_ in (await sample(db, redis)).items():
                print(f"  {what}: {id_}")
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
