"""Quiz → grade → adapt (J2 steps 3–6), plus the gate override and test-out (PC2.4–2.6).

Code decides, skills write (CLAUDE.md): `pedagogy` scores, updates mastery, schedules the review,
picks the rule and recomputes the gate; the LLM designs the quiz, grades the short answer,
explains a plan change, writes a remediation concept and warns about an override.

No DB connection is held during a model call: reads happen first, the session is released,
then writes re-read what they change (and lock the attempt, so a double submit grades once).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import pedagogy
from agent.llm import CallContext, LLMClient
from agent.pedagogy import Rule, Score
from agent.types import (
    Band,
    Concept,
    ConceptMap,
    CourseConfig,
    ExplainInput,
    ExplainOutput,
    GradeInput,
    GradeOutput,
    LessonDigest,
    Misbelief,
    PlanDiff,
    QuizInput,
    QuizOutput,
    StatusChange,
    TargetedQuizInput,
    WarningInput,
    WarningOutput,
)
from app.auth import CurrentUser
from app.models import (
    ConceptProgress,
    ConceptStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    Lesson,
    Misconception,
    PlanTrigger,
    PlanVersion,
    PrereqOverride,
    QuizAttempt,
)
from app.services.dashboard import invalidate_dashboard
from app.services.learning import (
    current_plan,
    get_owned_enrollment,
    latest_lesson,
    overridden_concepts,
    progress_rows,
)


# --- views (what the browser sees) --------------------------------------------------------------
class PublicOption(BaseModel):
    id: str
    text: str


class PublicQuestion(BaseModel):
    id: str
    prompt: str
    options: list[PublicOption]


class QuizView(BaseModel):
    """The quiz without answer keys, misconception tags or the rubric: any of those is a hint."""

    attempt_id: uuid.UUID
    concept_id: str
    concept_title: str
    round: int
    questions: list[PublicQuestion]
    explain_prompt: str


class QuestionResult(BaseModel):
    id: str
    prompt: str
    options: list[PublicOption]
    chosen: str | None
    answer: str
    correct: bool
    misconception: Misbelief | None  # the belief behind the distractor they picked


class ExplainResult(BaseModel):
    prompt: str
    answer: str
    score: Score | None  # None: left blank, so only the multiple-choice score counts
    feedback: str | None
    transfer_handled: bool | None


class ConceptRef(BaseModel):
    concept_id: str
    title: str


class QuizResult(BaseModel):
    """Stored in quiz_attempts.feedback, so the results page can be reloaded."""

    attempt_id: uuid.UUID
    concept_id: str
    concept_title: str
    mcq_correct: int
    mcq_score: Score
    short_score: Score | None
    score: Score  # combined: the lower of the two (§4.7)
    questions: list[QuestionResult]
    explain: ExplainResult
    misconceptions_named: list[Misbelief]
    mastery: float
    band: Band
    due: datetime
    rule: Rule
    why: str  # plain English: what happens next and why
    plan_version: int | None  # set when the rule changed the plan
    diff: PlanDiff | None
    unlocked: list[ConceptRef]  # concepts this result opened
    test_out_offer: ConceptRef | None
    next_concept: ConceptRef | None  # where to go next
    course_complete: bool


class PlanVersionView(BaseModel):
    version: int
    trigger: PlanTrigger
    rule: str | None
    reason: str
    diff: PlanDiff | None
    created_at: datetime


class OverrideWarning(BaseModel):
    concept_id: str
    unmet_prereqs: list[ConceptRef]
    warning: str


class OverrideRequest(BaseModel):
    warning: str = Field(min_length=1, max_length=2000)  # what the learner was shown


class SubmitRequest(BaseModel):
    # {q1..q4: option id, explain: free text}; first try only
    answers: dict[str, Annotated[str, Field(max_length=5000)]] = Field(max_length=10)


def _ctx(user: CurrentUser, enrollment: Enrollment) -> CallContext:
    return CallContext(user_id=user.id, course_id=enrollment.course_id, enrollment_id=enrollment.id)


def _ref(cmap: ConceptMap, concept_id: str) -> ConceptRef:
    c = cmap.concept(concept_id)
    return ConceptRef(concept_id=concept_id, title=c.title if c else concept_id)


def _public(attempt: QuizAttempt, concept: Concept, quiz: QuizOutput, round_: int) -> QuizView:
    return QuizView(
        attempt_id=attempt.id,
        concept_id=attempt.concept_id,
        concept_title=concept.title,
        round=round_,
        questions=[
            PublicQuestion(
                id=q.id,
                prompt=q.prompt,
                options=[PublicOption(id=o.id, text=o.text) for o in q.options],
            )
            for q in quiz.questions
        ],
        explain_prompt=quiz.explain_item.prompt,
    )


async def _open_misconceptions(
    db: AsyncSession, enrollment_id: uuid.UUID, concept_ids: list[str]
) -> list[Misbelief]:
    rows = await db.scalars(
        select(Misconception)
        .where(
            Misconception.enrollment_id == enrollment_id,
            Misconception.concept_id.in_(concept_ids),
            Misconception.resolved_at.is_(None),
        )
        .order_by(Misconception.created_at.desc())
    )
    seen: dict[str, Misbelief] = {}
    for m in rows:
        seen.setdefault(m.label, Misbelief(label=m.label[:120], note=m.note))
    return list(seen.values())[:5]


def _concept_or_404(cmap: ConceptMap, concept_id: str) -> Concept:
    concept = cmap.concept(concept_id)
    if concept is None:
        raise HTTPException(404, "concept not in your plan")
    return concept


# --- PC2.4: the quiz ----------------------------------------------------------------------------
async def open_quiz(
    db: AsyncSession, llm: LLMClient, user: CurrentUser, enrollment_id: uuid.UUID, concept_id: str
) -> QuizView:
    """The open (unsubmitted) quiz for this concept, or a newly designed one."""
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    cmap = await current_plan(db, enrollment)
    concept = _concept_or_404(cmap, concept_id)
    progress = await db.get(ConceptProgress, (enrollment.id, concept_id))
    if progress is None or progress.status == ConceptStatus.locked:
        raise HTTPException(409, "This concept is locked until its prerequisites are solid.")

    submitted = await db.scalar(
        select(func.count()).where(
            QuizAttempt.enrollment_id == enrollment.id,
            QuizAttempt.concept_id == concept_id,
            QuizAttempt.submitted_at.is_not(None),
        )
    )
    round_ = (submitted or 0) + 1
    pending = await db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.enrollment_id == enrollment.id,
            QuizAttempt.concept_id == concept_id,
            QuizAttempt.submitted_at.is_(None),
        )
    )
    if pending is not None:  # reopening shows the same questions: no fresh draw, no new call
        return _public(pending, concept, QuizOutput.model_validate(pending.questions), round_)

    lesson = await latest_lesson(db, enrollment.id, concept_id)
    if lesson is None and concept_id not in cmap.test_out:
        raise HTTPException(409, "Read the lesson first (or test out after scoring a 4).")
    lesson_row_id = await db.scalar(
        select(Lesson.id)
        .where(Lesson.enrollment_id == enrollment.id, Lesson.concept_id == concept_id)
        .order_by(Lesson.created_at.desc())
        .limit(1)
    )
    course = await db.get(Course, enrollment.course_id)
    assert course is not None
    config = CourseConfig.model_validate(course.config)
    # This learner's open beliefs about this concept and its prereqs target distractors (§4.6).
    beliefs = await _open_misconceptions(
        db,
        enrollment.id,
        [concept_id, *concept.prereqs] + ([concept.remedy.for_concept] if concept.remedy else []),
    )
    ctx = _ctx(user, enrollment)
    await db.close()  # don't hold a pooled connection during the model call

    base = QuizInput(
        topic=config.topic,
        target_level=config.target_level,
        # The lesson's situations, so the quiz can avoid them; the plan-state fields don't matter.
        concept=concept.model_copy(update={"remedy": None}),
        lesson=LessonDigest(
            explanation_md=lesson.content.explanation_md, example_md=lesson.content.example_md
        )
        if lesson
        else None,
        round=round_,
    )
    if beliefs:  # personal → never cached (ADR-0007)
        targeted = TargetedQuizInput(**base.model_dump(), misconceptions=beliefs)
        quiz = await llm.run("design-assessment", "design_targeted", targeted, QuizOutput, ctx=ctx)
    else:  # shareable → exact-cached on the lesson's content + round
        quiz = await llm.run("design-assessment", "design", base, QuizOutput, ctx=ctx)

    # Two opens can race (the lesson page prefetches the quiz while the learner reads, and
    # they may click "Take the quiz" before it lands): the first stored attempt wins.
    raced = await db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.enrollment_id == enrollment_id,
            QuizAttempt.concept_id == concept_id,
            QuizAttempt.submitted_at.is_(None),
        )
    )
    if raced is not None:
        return _public(raced, concept, QuizOutput.model_validate(raced.questions), round_)
    attempt = QuizAttempt(
        enrollment_id=enrollment_id,
        concept_id=concept_id,
        lesson_id=lesson_row_id,
        questions=quiz.model_dump(mode="json"),
    )
    db.add(attempt)
    await db.commit()
    return _public(attempt, concept, quiz, round_)


# --- PC2.4–2.5: submit → grade → mastery → FSRS → adapt ----------------------------------------
async def submit_quiz(
    db: AsyncSession,
    redis: Redis,
    llm: LLMClient,
    user: CurrentUser,
    enrollment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    answers: dict[str, str],
) -> QuizResult:
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.enrollment_id != enrollment.id:
        raise HTTPException(404, "quiz not found")
    if attempt.submitted_at is not None:
        raise HTTPException(409, "This quiz was already submitted.")
    cmap = await current_plan(db, enrollment)
    concept = _concept_or_404(cmap, attempt.concept_id)
    quiz = QuizOutput.model_validate(attempt.questions)
    progress = await db.get(ConceptProgress, (enrollment.id, concept.id))
    assert progress is not None
    lesson = await latest_lesson(db, enrollment.id, concept.id)
    prev_mastery, prev_attempts = progress.mastery, progress.attempts
    ctx = _ctx(user, enrollment)
    await db.close()  # the grade (and maybe explain_change) calls take seconds

    # Multiple choice: deterministic. A picked distractor names its belief (§4.7).
    results: list[QuestionResult] = []
    named: dict[str, Misbelief] = {}
    for q in quiz.questions:
        chosen = answers.get(q.id)
        picked = next((o for o in q.options if o.id == chosen), None)
        if picked is not None and picked.misconception is not None:
            named.setdefault(picked.misconception.label, picked.misconception)
        results.append(
            QuestionResult(
                id=q.id,
                prompt=q.prompt,
                options=[PublicOption(id=o.id, text=o.text) for o in q.options],
                chosen=chosen,
                answer=q.answer,
                correct=chosen == q.answer,
                misconception=picked.misconception if picked else None,
            )
        )
    mcq_correct = sum(r.correct for r in results)
    mcq = pedagogy.mcq_score(mcq_correct)

    # Short answer: the LLM grades it on the rubric (never cached).
    explain_text = answers.get("explain", "").strip()
    grade: GradeOutput | None = None
    if explain_text:
        grade = await llm.run(
            "grade",
            "grade",
            GradeInput(
                concept_title=concept.title,
                mastery_statement=concept.mastery_statement,
                item=quiz.explain_item,
                answer=explain_text,
            ),
            GradeOutput,
            ctx=ctx,
        )
        if grade.misconception is not None:
            # The grader's belief comes first: it's from the learner's own words.
            named = {grade.misconception.label: grade.misconception, **named}
    short: Score | None = grade.score if grade else None
    score = pedagogy.combine(mcq, short)

    # The decisions (§4.7–4.10), all in pedagogy.
    now = datetime.now(UTC)
    mastery = pedagogy.update_mastery(prev_mastery, score)
    band = pedagogy.band(mastery)
    rule = pedagogy.adapt(score, band, pedagogy.remediation_count(cmap, concept.id))

    explain: ExplainOutput | None = None
    if rule == Rule.insert_remediation:
        explain = await llm.run(
            "remediate",
            "explain_change",
            ExplainInput(
                concept=concept.model_copy(update={"remedy": None}),
                score=score,
                rule=rule.value,
                misconceptions=list(named.values()),
                lesson_explanation=lesson.content.explanation_md if lesson else None,
            ),
            ExplainOutput,
            ctx=ctx,
        )

    # --- writes: re-read under a row lock so a double submit grades once ----------------------
    attempt = await db.scalar(
        select(QuizAttempt).where(QuizAttempt.id == attempt_id).with_for_update()
    )
    assert attempt is not None
    progress = await db.get(ConceptProgress, (enrollment_id, concept.id))
    assert progress is not None
    if attempt.submitted_at is not None or progress.attempts != prev_attempts:
        raise HTTPException(409, "This quiz was already submitted.")
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    cmap = await current_plan(db, enrollment)

    card = pedagogy.schedule_review(
        pedagogy.load_card(progress.fsrs_card) if progress.fsrs_card else None, score, now
    )
    progress.mastery = mastery
    progress.band = band
    progress.last_score = score
    progress.attempts += 1
    progress.last_attempt_at = now
    progress.fsrs_card = dict(card.to_dict())
    progress.due = card.due

    for belief in named.values():
        db.add(
            Misconception(
                enrollment_id=enrollment_id,
                concept_id=concept.id,
                label=belief.label,
                note=belief.note,
                source_question=_source_question(quiz, results, belief, grade),
                quiz_attempt_id=attempt.id,
            )
        )

    new_map, diff = cmap, None
    if explain is not None:
        lead = next(iter(named.values()), None)
        new_map, diff = pedagogy.insert_remediation(
            cmap,
            concept.id,
            title=explain.remediation_concept.title,
            mastery_statement=explain.remediation_concept.mastery_statement,
            angle=explain.remediation_concept.angle,
            misconception=lead,
        )
        db.add(
            ConceptProgress(
                enrollment_id=enrollment_id,
                concept_id=diff.added[0].id,
                status=ConceptStatus.locked,  # the gate below decides
                attempts=0,
            )
        )
        await db.flush()

    rows = await progress_rows(db, enrollment_id)
    changes = _apply_gate(new_map, rows, await overridden_concepts(db, enrollment_id))
    if pedagogy.at_least(band, pedagogy.UNLOCK_BAND) and progress.status != ConceptStatus.complete:
        changes.append(StatusChange(concept_id=concept.id, old=progress.status, new="complete"))
        progress.status = ConceptStatus.complete

    plan_version: int | None = None
    if diff is not None and explain is not None:
        diff.status_changes = changes
        plan_version = enrollment.current_plan_version + 1
        db.add(
            PlanVersion(
                enrollment_id=enrollment_id,
                version=plan_version,
                plan=new_map.model_dump(mode="json"),
                diff=diff.model_dump(mode="json"),
                trigger=PlanTrigger.quiz_result,
                reason=explain.why,
                rule=rule.value,
            )
        )
        enrollment.current_plan_version = plan_version

    complete = pedagogy.course_complete({cid: p.band for cid, p in rows.items()})
    if complete and enrollment.status != EnrollmentStatus.complete:
        enrollment.status = EnrollmentStatus.complete
        enrollment.completed_at = now

    lessoned = set(
        await db.scalars(select(Lesson.concept_id).where(Lesson.enrollment_id == enrollment_id))
    )
    offer = (
        _test_out_offer(new_map, rows, lessoned, concept.id)
        if rule == Rule.offer_test_out
        else None
    )
    unlocked = [_ref(new_map, c.concept_id) for c in changes if c.new == ConceptStatus.unlocked]
    result = QuizResult(
        attempt_id=attempt.id,
        concept_id=concept.id,
        concept_title=concept.title,
        mcq_correct=mcq_correct,
        mcq_score=mcq,
        short_score=short,
        score=score,
        questions=results,
        explain=ExplainResult(
            prompt=quiz.explain_item.prompt,
            answer=explain_text,
            score=short,
            feedback=grade.feedback if grade else None,
            transfer_handled=grade.transfer_handled if grade else None,
        ),
        misconceptions_named=list(named.values()),
        mastery=round(mastery, 4),
        band=band,
        due=card.due,
        rule=rule,
        why=explain.why if explain else _why(rule, score, concept, band, offer, unlocked),
        plan_version=plan_version,
        diff=diff,
        unlocked=unlocked,
        test_out_offer=offer,
        next_concept=_next_concept(new_map, rows),
        course_complete=complete,
    )
    attempt.answers = answers
    attempt.mcq_correct = mcq_correct
    attempt.mcq_score = mcq
    attempt.short_score = short
    attempt.score_1_4 = score
    attempt.feedback = result.model_dump(mode="json")
    attempt.misconceptions_named = [b.label for b in named.values()]
    attempt.submitted_at = now
    await db.commit()
    await invalidate_dashboard(redis, user.id)  # progress changed (after the commit)
    return result


def _source_question(
    quiz: QuizOutput, results: list[QuestionResult], belief: Misbelief, grade: GradeOutput | None
) -> str | None:
    if grade and grade.misconception and grade.misconception.label == belief.label:
        return quiz.explain_item.prompt
    hit = next(
        (r for r in results if r.misconception and r.misconception.label == belief.label), None
    )
    return hit.prompt if hit else None


def _apply_gate(
    cmap: ConceptMap, rows: dict[str, ConceptProgress], overridden: set[str]
) -> list[StatusChange]:
    """Recompute the prerequisite gate (§4.8) and return what changed.

    Locked concepts whose prereqs are now all solid unlock. An open concept whose prereqs are
    no longer all solid (a remediation was just inserted before it) re-locks, unless the learner
    overrode the gate for it. Complete concepts stay complete.

    A remediation for an overridden concept inherits the override: it takes that concept's
    unmet prereqs, so without this it would be locked behind the very gate the learner already
    chose to skip, while the concept it remediates stays open.
    """
    bands = {cid: p.band for cid, p in rows.items()}
    passes = pedagogy.unlocked(cmap.graph(), bands)
    exempt = overridden | {
        c.id for c in cmap.concepts if c.remedy and c.remedy.for_concept in overridden
    }
    changes: list[StatusChange] = []
    for cid in cmap.sequence:
        p = rows.get(cid)
        if p is None or p.status == ConceptStatus.complete:
            continue
        new = p.status
        if p.status == ConceptStatus.locked and (cid in passes or cid in exempt - overridden):
            new = ConceptStatus.unlocked
        elif p.status != ConceptStatus.locked and cid not in passes and cid not in exempt:
            new = ConceptStatus.locked
        if new != p.status:
            changes.append(StatusChange(concept_id=cid, old=p.status, new=new))
            p.status = new
    return changes


def _next_concept(cmap: ConceptMap, rows: dict[str, ConceptProgress]) -> ConceptRef | None:
    """The first open, not-yet-complete concept in sequence (from the start, so an inserted
    remediation before `after` comes first)."""
    for cid in cmap.sequence:
        p = rows.get(cid)
        if p is not None and p.status in (ConceptStatus.unlocked, ConceptStatus.in_progress):
            return _ref(cmap, cid)
    return None


def _test_out_offer(
    cmap: ConceptMap, rows: dict[str, ConceptProgress], lessoned: set[str], after: str
) -> ConceptRef | None:
    """ADR-0006: after a 4, offer the next unlocked concept that hasn't been started."""
    start = cmap.sequence.index(after) + 1
    for cid in cmap.sequence[start:]:
        p = rows.get(cid)
        c = cmap.concept(cid)
        if (
            p is not None
            and c is not None
            and not c.is_remediation
            and p.status == ConceptStatus.unlocked
            and p.attempts == 0
            and cid not in lessoned
            and cid not in cmap.test_out
        ):
            return _ref(cmap, cid)
    return None


def _why(
    rule: Rule,
    score: Score,
    concept: Concept,
    band: Band,
    offer: ConceptRef | None,
    unlocked: list[ConceptRef],
) -> str:
    """The plain-English outcome for rules that don't change the plan (no LLM needed)."""
    opened = " Now open: " + ", ".join(f"'{u.title}'" for u in unlocked) + "." if unlocked else ""
    if rule == Rule.offer_test_out:
        tail = (
            f" You can test out of '{offer.title}': skip its lesson and go straight to its quiz."
            " Mastery still comes only from that quiz."
            if offer
            else ""
        )
        return (
            f"You scored 4 on '{concept.title}', including the transfer case: {band}.{opened}{tail}"
        )
    if rule == Rule.advance:
        return f"You scored {score} on '{concept.title}': {band}.{opened}"
    if score <= 2:
        return (
            f"You scored {score} on '{concept.title}'. It already has "
            f"{pedagogy.MAX_REMEDIATIONS} remediation concepts, so retake the quiz rather than "
            "adding another; re-read the lesson first."
        )
    return (
        f"You scored {score} on '{concept.title}', but your mastery is {band}: one good result "
        "doesn't erase an earlier miss. Retake the quiz to unlock what depends on it."
    )


async def quiz_result(
    db: AsyncSession, user: CurrentUser, enrollment_id: uuid.UUID, attempt_id: uuid.UUID
) -> QuizResult:
    await get_owned_enrollment(db, user, enrollment_id)
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.enrollment_id != enrollment_id or attempt.feedback is None:
        raise HTTPException(404, "no graded quiz")
    return QuizResult.model_validate(attempt.feedback)


# --- PC2.5: plan history --------------------------------------------------------------------------
async def plan_history(
    db: AsyncSession, user: CurrentUser, enrollment_id: uuid.UUID
) -> list[PlanVersionView]:
    await get_owned_enrollment(db, user, enrollment_id)
    rows = await db.scalars(
        select(PlanVersion)
        .where(PlanVersion.enrollment_id == enrollment_id)
        .order_by(PlanVersion.version.desc())
    )
    return [
        PlanVersionView(
            version=v.version,
            trigger=v.trigger,
            rule=v.rule,
            reason=v.reason,
            diff=PlanDiff.model_validate(v.diff) if v.diff else None,
            created_at=v.created_at,
        )
        for v in rows
    ]


async def _new_version(
    db: AsyncSession,
    enrollment: Enrollment,
    cmap: ConceptMap,
    diff: PlanDiff,
    trigger: PlanTrigger,
    reason: str,
    rule: str | None,
) -> int:
    version = enrollment.current_plan_version + 1
    db.add(
        PlanVersion(
            enrollment_id=enrollment.id,
            version=version,
            plan=cmap.model_dump(mode="json"),
            diff=diff.model_dump(mode="json"),
            trigger=trigger,
            reason=reason,
            rule=rule,
        )
    )
    enrollment.current_plan_version = version
    return version


# --- PC2.6: test out (ADR-0006) -------------------------------------------------------------------
async def accept_test_out(
    db: AsyncSession, redis: Redis, user: CurrentUser, enrollment_id: uuid.UUID, concept_id: str
) -> PlanVersionView:
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    cmap = await current_plan(db, enrollment)
    concept = _concept_or_404(cmap, concept_id)
    last = await db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.enrollment_id == enrollment.id, QuizAttempt.submitted_at.is_not(None))
        .order_by(QuizAttempt.submitted_at.desc())
        .limit(1)
    )
    offered = (last.feedback or {}).get("test_out_offer") if last else None
    if not offered or offered.get("concept_id") != concept_id:
        raise HTTPException(409, "Testing out is offered only right after scoring a 4.")
    if concept_id in cmap.test_out:
        raise HTTPException(409, "You're already testing out of this concept.")
    new_map = cmap.model_copy(update={"test_out": [*cmap.test_out, concept_id]})
    from_title = last.feedback["concept_title"] if last and last.feedback else "the last concept"
    reason = (
        f"You scored 4 on '{from_title}', including the transfer case, and chose to test out of "
        f"'{concept.title}': its lesson is skipped and you go straight to its quiz. That quiz "
        "is graded like any other, and the lesson stays available if you want it."
    )
    version = await _new_version(
        db,
        enrollment,
        new_map,
        PlanDiff(test_out=[concept_id]),
        PlanTrigger.quiz_result,
        reason,
        Rule.offer_test_out.value,
    )
    await db.commit()
    await invalidate_dashboard(redis, user.id)
    return PlanVersionView(
        version=version,
        trigger=PlanTrigger.quiz_result,
        rule=Rule.offer_test_out.value,
        reason=reason,
        diff=PlanDiff(test_out=[concept_id]),
        created_at=datetime.now(UTC),
    )


# --- PC2.6: the gate override ---------------------------------------------------------------------
async def _locked_with_unmet(
    db: AsyncSession, enrollment: Enrollment, concept_id: str
) -> tuple[ConceptMap, Concept, list[Concept]]:
    cmap = await current_plan(db, enrollment)
    concept = _concept_or_404(cmap, concept_id)
    progress = await db.get(ConceptProgress, (enrollment.id, concept_id))
    if progress is None or progress.status != ConceptStatus.locked:
        raise HTTPException(409, "This concept isn't locked.")
    rows = await progress_rows(db, enrollment.id)
    unmet = [
        c
        for p in concept.prereqs
        if (c := cmap.concept(p)) is not None
        and not pedagogy.at_least(rows[p].band if p in rows else None, pedagogy.UNLOCK_BAND)
    ]
    return cmap, concept, unmet


async def override_warning(
    db: AsyncSession, llm: LLMClient, user: CurrentUser, enrollment_id: uuid.UUID, concept_id: str
) -> OverrideWarning:
    """The specific cost of skipping the gate (spec §4.8), shown before the learner confirms."""
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    _cmap, concept, unmet = await _locked_with_unmet(db, enrollment, concept_id)
    ctx = _ctx(user, enrollment)
    await db.close()
    out = await llm.run(
        "remediate",
        "prereq_warning",
        WarningInput(
            concept=concept.model_copy(update={"remedy": None}),
            unmet_prereqs=[c.model_copy(update={"remedy": None}) for c in unmet],
        ),
        WarningOutput,
        ctx=ctx,
    )
    return OverrideWarning(
        concept_id=concept_id,
        unmet_prereqs=[ConceptRef(concept_id=c.id, title=c.title) for c in unmet],
        warning=out.what_will_break,
    )


async def confirm_override(
    db: AsyncSession,
    redis: Redis,
    user: CurrentUser,
    enrollment_id: uuid.UUID,
    concept_id: str,
    warning: str,
) -> PlanVersionView:
    """Log the override and open the concept: a new plan version (trigger prereq_override)."""
    enrollment = await get_owned_enrollment(db, user, enrollment_id)
    cmap, concept, unmet = await _locked_with_unmet(db, enrollment, concept_id)
    db.add(
        PrereqOverride(
            enrollment_id=enrollment.id,
            concept_id=concept_id,
            unmet_prereqs=[c.id for c in unmet],
            warning=warning,
        )
    )
    progress = await db.get(ConceptProgress, (enrollment.id, concept_id))
    assert progress is not None
    progress.status = ConceptStatus.unlocked
    names = ", ".join(f"'{c.title}'" for c in unmet) or "its prerequisites"
    reason = f"You opened '{concept.title}' before {names} were solid. You were warned: {warning}"
    diff = PlanDiff(
        status_changes=[StatusChange(concept_id=concept_id, old="locked", new="unlocked")]
    )
    version = await _new_version(
        db, enrollment, cmap, diff, PlanTrigger.prereq_override, reason, None
    )
    await db.commit()
    await invalidate_dashboard(redis, user.id)
    return PlanVersionView(
        version=version,
        trigger=PlanTrigger.prereq_override,
        rule=None,
        reason=reason,
        diff=diff,
        created_at=datetime.now(UTC),
    )
