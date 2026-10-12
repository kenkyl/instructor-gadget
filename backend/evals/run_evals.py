"""`make evals`: the mini eval harness (build brief §6, ADR-0031). Needs ANTHROPIC_API_KEY.

Six checks, one summary table:
1. Diagnosis personas: each `diagnose` assess case 3x. Within one level of `expected_level`, an
   adjustment message whenever it re-levels, and the same level on every run.
2. Map constraints: 3 configs (2 personal maps + the org template map). Valid graph, time
   within ±15%, a "You can …" mastery statement on every concept.
3. Pedagogy rules: `tests/test_pedagogy.py` (deterministic; also part of `make test`).
4. Grader calibration: Kyle's 8 labelled answers, 3 runs each. Exact and within-one agreement,
   consistency, and whether a fluent restatement ever got a 4.
5. Grounding judge: the `judge-grounding` skill scores the grounded lessons and the template map
   in `ground-in-sources/evals/cases.yaml`, plus one planted invention it must catch.
6. Semantic cache: hit and false-hit rate at the default threshold (`make eval-cache`, no API).

Every model call goes through the production wrapper (validation, one retry), with no cache
tier: an eval measures fresh generations. Calls run 4 at a time. Each skill's own `evals/` cases
are run too: their Python-expression asserts are checked; "(LLM judge)" ones go to the judge.
"""

import asyncio
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from redisvl.utils.vectorize import HFTextVectorizer

from agent import plan
from agent.llm import CallContext, CallRecord, LLMClient, LLMError
from agent.registry import get_registry
from agent.semantic import DEFAULT_DISTANCE_THRESHOLD
from agent.skills.diagnose.schema import AssessInput, AssessOutput, ProbeInput, ProbeOutput
from agent.types import (
    ClaimVerdict,
    GradeInput,
    GradeOutput,
    JudgeInput,
    JudgeOutput,
    LessonOutput,
    MapInput,
    MapOutput,
    TeachInput,
)
from app.config import get_settings
from evals import cache_eval
from evals.grounding_eval import grounding_for

BACKEND = Path(__file__).parents[1]
SKILLS = BACKEND / "agent/skills"
RUNS = 3  # per persona and per labelled answer (brief §6.1, §6.4)
CONCURRENCY = 4
LEVELS = ["novice", "intermediate", "strong", "expert"]
BUDGET_USD = 5.00  # pre-authorized for PC5.2; the harness stops scheduling past it


def cases(skill: str) -> dict[str, Any]:
    return yaml.safe_load((SKILLS / skill / "evals/cases.yaml").read_text())


# --- plumbing ---------------------------------------------------------------------------------
@dataclass
class CostSink:
    """Every request the wrapper makes, retries included: the run's real spend."""

    records: list[CallRecord] = field(default_factory=list)

    async def record(self, rec: CallRecord) -> None:
        self.records.append(rec)

    @property
    def cost(self) -> float:
        return sum(r.est_cost_usd for r in self.records)

    def by_skill(self) -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for r in self.records:
            n, c = out.get(r.skill, (0, 0.0))
            out[r.skill] = (n + 1, c + r.est_cost_usd)
        return out


@dataclass
class Harness:
    llm: LLMClient
    sink: CostSink
    sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(CONCURRENCY))

    async def run[T: BaseModel](
        self, skill: str, call: str, payload: BaseModel, out: type[T], **kw: Any
    ) -> T | LLMError:
        """One call, at most CONCURRENCY at a time. A failure is a result, not a crash."""
        async with self.sem:
            if self.sink.cost > BUDGET_USD:
                return LLMError(f"skipped: over the ${BUDGET_USD:.2f} budget")
            try:
                return await self.llm.run(skill, call, payload, out, ctx=CallContext(), **kw)
            except LLMError as e:
                return e


def check_asserts(output: BaseModel, asserts: list[str]) -> tuple[list[str], list[str]]:
    """The committed cases' Python-expression asserts → (failed, left for the judge/eye)."""
    failed, judged = [], []
    for a in asserts:
        if "(LLM judge)" in a:
            judged.append(a)
            continue
        try:
            ok = eval(a, {"len": len, "all": all, "any": any}, {"output": output})  # noqa: S307  (our own committed YAML)
        except SyntaxError:
            judged.append(a)  # prose, not an expression
            continue
        if not ok:
            failed.append(a)
    return failed, judged


VERDICTS: tuple[ClaimVerdict, ...] = (
    "cited_supported",
    "cited_unsupported",
    "uncited_from_docs",
    "general_knowledge",
    "invented_org_detail",
)


def md(*cells: object) -> str:
    """One Markdown table row; a bool cell reads yes/no."""
    return (
        "| "
        + " | ".join(("yes" if c else "no") if isinstance(c, bool) else str(c) for c in cells)
        + " |"
    )


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


@dataclass
class Row:
    check: str
    result: str
    detail: str = ""


# --- 1. diagnosis personas ---------------------------------------------------------------------
async def diagnosis(h: Harness) -> tuple[list[Row], list[str]]:
    personas = cases("diagnose")["assess"]
    jobs = [
        h.run("diagnose", "assess", AssessInput.model_validate(p["input"]), AssessOutput)
        for p in personas
        for _ in range(RUNS)
    ]
    probe_case = cases("diagnose")["probe"][0]
    jobs_probe = h.run(
        "diagnose", "probe", ProbeInput.model_validate(probe_case["input"]), ProbeOutput
    )
    results, probe = await asyncio.gather(asyncio.gather(*jobs), jobs_probe)

    lines = [
        "\n## 1. Diagnosis personas (3 runs each)\n",
        "| persona | expected | runs | within one | message when re-levelled | consistent |",
        "|---|---|---|---|---|---|",
    ]
    within = consistent = msg_ok = total = 0
    for i, p in enumerate(personas):
        outs = results[i * RUNS : (i + 1) * RUNS]
        levels = [o.assessed_level if isinstance(o, AssessOutput) else "error" for o in outs]
        exp = LEVELS.index(p["expected_level"])
        w = sum(lv != "error" and abs(LEVELS.index(lv) - exp) <= 1 for lv in levels)
        m = sum(
            isinstance(o, AssessOutput)
            and (o.assessed_level == o.claimed_level or bool(o.adjustment_message))
            for o in outs
        )
        c = len(set(levels)) == 1 and "error" not in levels
        within, msg_ok, consistent, total = within + w, msg_ok + m, consistent + c, total + RUNS
        lines.append(
            md(p["id"], p["expected_level"], ", ".join(levels), f"{w}/{RUNS}", f"{m}/{RUNS}", c)
        )
    if isinstance(probe, ProbeOutput):
        failed, _ = check_asserts(probe, probe_case["assert"])
        lines.append(
            f"\nProbe case `{probe_case['id']}`: {len(probe.questions)} questions, "
            + ("asserts pass" if not failed else f"FAILED {failed}")
        )
    else:
        lines.append(f"\nProbe case `{probe_case['id']}`: error {probe}")
    rows = [
        Row(
            "Diagnosis: within one level", pct(within, total), f"{len(personas)} personas x {RUNS}"
        ),
        Row("Diagnosis: consistent across runs", pct(consistent, len(personas))),
        Row("Diagnosis: re-levels are explained", pct(msg_ok, total)),
    ]
    return rows, lines


# --- 2. map constraints ------------------------------------------------------------------------
def map_checks(cmap: MapOutput, target: int) -> list[str]:
    errs = plan.structure_errors(cmap.graph(), cmap.sequence)
    if (e := plan.time_error(cmap.total_minutes(), target)) is not None:
        errs.append(e)
    errs += [
        f"{c.id}: no 'You can …' mastery statement"
        for c in cmap.concepts
        if not c.mastery_statement.strip().startswith("You can")
    ]
    return errs


async def maps(h: Harness) -> tuple[list[Row], list[str], MapOutput | LLMError, dict[str, Any]]:
    personal = cases("map-concepts")["map"]
    grounded = cases("ground-in-sources")["grounded_map"][0]
    grounding = grounding_for(grounded["docs"])
    outs = await asyncio.gather(
        *(
            h.run("map-concepts", "map", MapInput.model_validate(c["input"]), MapOutput)
            for c in personal
        ),
        h.run(
            "map-concepts",
            "map",
            MapInput.model_validate(grounded["input"]),
            MapOutput,
            grounding=grounding,
        ),
    )
    lines = [
        "\n## 2. Concept map constraints\n",
        "| config | concepts | minutes (target) | graph + time + statements | case asserts |",
        "|---|---|---|---|---|",
    ]
    ok = 0
    for c, o in zip([*personal, grounded], outs, strict=True):
        target = c["input"]["target_minutes"]
        if isinstance(o, LLMError):
            lines.append(f"| {c['id']} | error | | {o} | |")
            continue
        errs = map_checks(o, target)
        failed, _ = check_asserts(o, c["assert"])
        ok += not errs and not failed
        lines.append(
            md(
                c["id"],
                len(o.concepts),
                f"{o.total_minutes()} ({target})",
                "valid" if not errs else "; ".join(errs),
                "pass" if not failed else "FAILED: " + "; ".join(failed),
            )
        )
    return [Row("Map constraints (3 configs)", pct(ok, len(outs)))], lines, outs[-1], grounded


# --- 3. pedagogy -------------------------------------------------------------------------------
def pedagogy() -> tuple[list[Row], list[str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_pedagogy.py"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]
    return [Row("Pedagogy rules (unit tests)", "pass" if proc.returncode == 0 else "FAIL", tail)], [
        "\n## 3. Pedagogy rules\n",
        f"`tests/test_pedagogy.py`: {tail}",
    ]


# --- 4. grader calibration ---------------------------------------------------------------------
async def calibration(h: Harness) -> tuple[list[Row], list[str]]:
    data = yaml.safe_load((BACKEND / "evals/grader_calibration.yaml").read_text())
    labelled = [a for a in data["answers"] if a.get("label")]
    item = {k: data["item"][k] for k in ("prompt", "transfer_situation", "rubric")}
    base = {
        "concept_title": data["item"]["concept_title"],
        "mastery_statement": data["item"]["mastery_statement"],
        "item": item,
    }
    grade_case = cases("grade")["grade"][0]
    results, case_out = await asyncio.gather(
        asyncio.gather(
            *(
                h.run(
                    "grade",
                    "grade",
                    GradeInput.model_validate({**base, "answer": a["answer"]}),
                    GradeOutput,
                )
                for a in labelled
                for _ in range(RUNS)
            )
        ),
        h.run("grade", "grade", GradeInput.model_validate(grade_case["input"]), GradeOutput),
    )
    lines = [
        "\n## 4. Grader calibration (Kyle's labels, 3 runs each)\n",
        "| answer | label | scores | exact | within one |",
        "|---|---|---|---|---|",
    ]
    exact = within = n = consistent = 0
    inflated: list[str] = []
    for i, a in enumerate(labelled):
        label = int(str(a["label"]).removeprefix("score_"))
        outs = results[i * RUNS : (i + 1) * RUNS]
        scores = [o.score for o in outs if isinstance(o, GradeOutput)]
        e, w = sum(s == label for s in scores), sum(abs(s - label) <= 1 for s in scores)
        exact, within, n = exact + e, within + w, n + len(outs)
        consistent += len(set(scores)) == 1 and len(scores) == RUNS
        if "restatement" in a["id"] and 4 in scores:
            inflated.append(a["id"])
        lines.append(
            md(a["id"], label, ", ".join(map(str, scores)) or "error", f"{e}/{RUNS}", f"{w}/{RUNS}")
        )
    lines.append(
        "\nFluent restatements scored 4: "
        + (", ".join(inflated) if inflated else "never (the cap held)")
    )
    if isinstance(case_out, GradeOutput):
        failed, _ = check_asserts(case_out, grade_case["assert"])
        lines.append(
            f"Grade case `{grade_case['id']}`: score {case_out.score}, "
            + ("asserts pass" if not failed else f"FAILED {failed}")
        )
    rows = [
        Row("Grader: exact agreement", pct(exact, n), f"{len(labelled)} answers x {RUNS}"),
        Row("Grader: within one", pct(within, n)),
        Row("Grader: consistent across runs", pct(consistent, len(labelled))),
        Row(
            "Grader: restatement capped at 3",
            "yes" if not inflated else f"NO ({', '.join(inflated)})",
        ),
    ]
    return rows, lines


# --- 5. grounding judge ------------------------------------------------------------------------
def render_lesson(lesson: LessonOutput) -> str:
    cites = "\n".join(
        f'[{n}] {c.doc} › {c.section}: "{c.quote}"' for n, c in enumerate(lesson.citations, 1)
    )
    gaps = "\n".join(
        f"- {g.point}"
        + (f" (general knowledge: {g.general_knowledge})" if g.general_knowledge else "")
        for g in lesson.not_in_docs
    )
    return "\n\n".join(
        [
            lesson.explanation_md,
            f"## Example\n{lesson.example_md}",
            f"## Citations\n{cites or '(none)'}",
            f"## Not in your docs\n{gaps or '(none)'}",
        ]
    )


def render_map(cmap: MapOutput) -> str:
    by_id = {c.id: c for c in cmap.concepts}
    rows = [
        f"{n}. {by_id[cid].title}: {by_id[cid].mastery_statement}"
        for n, cid in enumerate(cmap.sequence, 1)
    ]
    return "\n".join(rows) + f"\n\nRationale: {cmap.sequence_rationale}"


async def grounding_judge(
    h: Harness, tmap: MapOutput | LLMError, map_case: dict[str, Any]
) -> tuple[list[Row], list[str]]:
    teach = cases("ground-in-sources")["grounded_teach"]
    lessons = await asyncio.gather(
        *(
            h.run(
                "teach-concept",
                "teach",
                TeachInput.model_validate(c["input"]),
                LessonOutput,
                grounding=grounding_for(c["docs"]),
            )
            for c in teach
        )
    )
    planted = cases("judge-grounding")["judge"][0]
    todo: list[tuple[str, str, dict[str, Any], str, list[str]]] = []
    lines = ["\n## 5. Grounding judge (`judge-grounding`, unvalidated: ADR-0031)\n"]
    for c, lesson in zip(teach, lessons, strict=True):
        if isinstance(lesson, LessonOutput):
            failed, judged = check_asserts(lesson, c["assert"])
            todo.append((c["id"], "lesson", c, render_lesson(lesson), judged))
            lines.append(
                f"- `{c['id']}`: {len(lesson.citations)} citations, "
                f"{len(lesson.not_in_docs)} gaps; code asserts "
                + ("pass" if not failed else f"FAILED {failed}")
            )
        else:
            lines.append(f"- `{c['id']}`: lesson error {lesson}")
    if isinstance(tmap, MapOutput):
        _, judged = check_asserts(tmap, map_case["assert"])
        todo.append((map_case["id"], "map", map_case, render_map(tmap), judged))
    todo.append(
        (planted["id"], planted["kind"], planted, planted["artifact_md"], planted["assertions"])
    )

    verdicts = await asyncio.gather(
        *(
            h.run(
                "judge-grounding",
                "judge",
                JudgeInput.model_validate(
                    {
                        "kind": kind,
                        "docs_md": grounding_for(c["docs"]).text,
                        "artifact_md": art,
                        "assertions": asserts,
                    }
                ),
                JudgeOutput,
            )
            for _, kind, c, art, asserts in todo
        )
    )
    lines += [
        "",
        md(
            "case",
            "claims",
            "cited ✓",
            "cited ✗",
            "uncited, in docs",
            "general",
            "invented",
            "asserts",
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    passed = asserted = invented = cited_bad = 0
    planted_caught = False
    for (cid, *_), v in zip(todo, verdicts, strict=True):
        if not isinstance(v, JudgeOutput):
            lines.append(f"| {cid} | judge error: {v} | | | | | | |")
            continue
        p = sum(a.passed for a in v.assertions)
        if cid == planted["id"]:
            failed, _ = check_asserts(v, planted["assert"])
            planted_caught = not failed
        else:
            passed, asserted = passed + p, asserted + len(v.assertions)
            invented += v.count("invented_org_detail")
            cited_bad += v.count("cited_unsupported")
        lines.append(
            md(
                cid,
                len(v.claims),
                *(v.count(k) for k in VERDICTS),
                f"{p}/{len(v.assertions)}",
            )
        )
        for cl in v.claims:
            if cl.verdict in ("cited_unsupported", "invented_org_detail"):
                lines.append(f"|  ↳ {cl.verdict}: {cl.claim[:90]} | {cl.note[:120]} | | | | | | |")
        for a in v.assertions:
            if not a.passed:
                lines.append(f"|  ↳ failed: {a.assertion[:90]} | {a.reason[:120]} | | | | | | |")
    rows = [
        Row(
            "Grounding judge: assertions passed", pct(passed, asserted), "2 lessons + template map"
        ),
        Row(
            "Grounding judge: invented org detail",
            str(invented),
            f"cited but unsupported: {cited_bad}",
        ),
        Row("Grounding judge: catches a planted invention", "yes" if planted_caught else "NO"),
    ]
    return rows, lines


# --- 6. semantic cache -------------------------------------------------------------------------
async def cache() -> tuple[list[Row], list[str]]:
    vectorizer = await asyncio.to_thread(HFTextVectorizer, model=cache_eval.MODEL)
    results = await cache_eval.measure_cache(cache_eval.load_pairs(), vectorizer)
    t = DEFAULT_DISTANCE_THRESHOLD
    hits = [r for r in results if r.pair.label == "hit"]
    misses = [r for r in results if r.pair.label == "miss"]
    h, f = sum(r.hit_at(t) for r in hits), sum(r.hit_at(t) for r in misses)
    rows = [
        Row(
            f"Semantic cache: false-hit rate @ {t}", pct(f, len(misses)), "should-miss pairs served"
        ),
        Row(f"Semantic cache: hit rate @ {t}", pct(h, len(hits)), "should-hit pairs served"),
    ]
    return rows, [
        f"\n## 6. Semantic cache (MiniLM, threshold {t}; full sweep: `make eval-cache`)\n",
        f"False hits {pct(f, len(misses))}, hits {pct(h, len(hits))}.",
    ]


# --- main --------------------------------------------------------------------------------------
async def main() -> None:
    settings = get_settings()
    key = settings.anthropic_api_key
    if key is None or not key.get_secret_value():
        raise SystemExit("ANTHROPIC_API_KEY is not set (see .env.example)")
    client = AsyncAnthropic(
        api_key=key.get_secret_value(), timeout=settings.anthropic_timeout_seconds
    )
    sink = CostSink()
    h = Harness(LLMClient(client, get_registry(), sink, model=settings.anthropic_model), sink)
    started = time.perf_counter()
    print(
        f"make evals: model {settings.anthropic_model}, {CONCURRENCY} calls at a time, "
        f"budget ${BUDGET_USD:.2f}"
    )
    try:
        ped = pedagogy()

        async def maps_then_judge() -> tuple[
            tuple[list[Row], list[str]], tuple[list[Row], list[str]]
        ]:
            mrows, mlines, tmap, mcase = await maps(h)
            return (mrows, mlines), await grounding_judge(h, tmap, mcase)

        parts: list[Awaitable[Any]] = [diagnosis(h), maps_then_judge(), calibration(h), cache()]
        diag, (mp, judge), cal, cch = await asyncio.gather(*parts)
    finally:
        await client.close()

    sections = [diag, mp, ped, cal, judge, cch]
    for _, lines in sections:
        print("\n".join(lines))
    print("\n## Summary\n\n| check | result | detail |\n|---|---|---|")
    for rows, _ in sections:
        for r in rows:
            print(f"| {r.check} | {r.result} | {r.detail} |")
    retries = Counter(r.attempt for r in sink.records)[2]
    print(
        f"\n{len(sink.records)} requests ({retries} retries), ${sink.cost:.3f}, "
        f"{time.perf_counter() - started:.0f} s wall clock."
    )
    for skill, (n, c) in sorted(sink.by_skill().items()):
        print(f"  {skill}: {n} requests, ${c:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
