"""`make warm-cache`: generate the sample courses' lessons ahead of a walkthrough, so the first
click shows a lesson instead of a ~15 s wait. Needs ANTHROPIC_API_KEY; run after `make reset`.

It runs inside the app's own lifespan (the same LLM wrapper, exact and semantic tiers, call log)
and calls the same service functions as `POST …/lesson`:
- kyle's in-progress course: every open concept's lesson is generated **and stored** on his
  enrollment, the remediation lesson included, so reopening is instant.
- dana's assigned org course: her open concepts' lessons go **into the cache only** (logged
  against the course, with no learner). Her first click is then a real exact hit: served from
  Redis in milliseconds, and the trace and org impact show what it saved.

After a reset the cache survives (its keys hold no user ids), so a second run costs little: the
core lessons are exact hits, and only the never-cached remediation lesson is regenerated.
"""

import asyncio
import time

from sqlalchemy import select

from agent.llm import CallContext
from agent.types import LessonOutput, TeachInput
from app.auth import CurrentUser
from app.main import app, lifespan
from app.models import ConceptProgress, ConceptStatus, Enrollment, EnrollmentStatus, User
from app.services.learning import DoneEvent, LessonJob, prepare_lesson, stream_lesson

CONCURRENCY = 4
STORED_FOR = "kyle"  # lessons stored on the enrollment
CACHED_FOR = "dana"  # cache only: her first open is a hit


async def open_jobs(username: str) -> list[tuple[CurrentUser, LessonJob]]:
    """A lesson job for every open concept without a stored lesson in the user's active courses."""
    jobs = []
    async with app.state.sessionmaker() as db:
        u = await db.scalar(select(User).where(User.username == username))
        assert u is not None, "run `make reset` first"
        user = CurrentUser(id=u.id, username=u.username, display_name=u.display_name)
        rows = await db.execute(
            select(Enrollment.id, ConceptProgress.concept_id)
            .join(ConceptProgress, ConceptProgress.enrollment_id == Enrollment.id)
            .where(
                Enrollment.user_id == u.id,
                Enrollment.status == EnrollmentStatus.active,
                ConceptProgress.status != ConceptStatus.locked,
            )
        )
        for enrollment_id, concept_id in rows.all():
            job = await prepare_lesson(db, user, enrollment_id, concept_id)
            if isinstance(job, LessonJob):
                jobs.append((user, job))
    return jobs


async def main() -> None:
    async with lifespan(app):
        llm = app.state.llm
        if llm is None:
            raise SystemExit("ANTHROPIC_API_KEY is not set (see .env.example)")
        sem = asyncio.Semaphore(CONCURRENCY)
        results: list[str] = []

        async def store(user: CurrentUser, job: LessonJob) -> None:
            async with sem:
                started = time.perf_counter()
                async for ev in stream_lesson(app.state.sessionmaker, app.state.redis, llm, job):
                    if isinstance(ev, DoneEvent):
                        results.append(
                            f"  {user.username} {job.concept_id}: stored "
                            f"({ev.lesson.cache_result}, {time.perf_counter() - started:.1f} s)"
                        )

        async def cache_only(user: CurrentUser, job: LessonJob) -> None:
            assert isinstance(job.payload, TeachInput)
            async with sem:
                started = time.perf_counter()
                await llm.run(
                    "teach-concept",
                    "teach",
                    job.payload,
                    LessonOutput,
                    ctx=CallContext(course_id=job.course_id),
                    semantic=job.semantic,
                    grounding=job.grounding,
                )
                results.append(
                    f"  {user.username} {job.concept_id}: cached "
                    f"({time.perf_counter() - started:.1f} s)"
                )

        work = [store(u, j) for u, j in await open_jobs(STORED_FOR)]
        work += [cache_only(u, j) for u, j in await open_jobs(CACHED_FOR)]
        started = time.perf_counter()
        await asyncio.gather(*work)
        print("\n".join(sorted(results)))
        print(f"{len(work)} lessons warmed in {time.perf_counter() - started:.0f} s.")


if __name__ == "__main__":
    asyncio.run(main())
