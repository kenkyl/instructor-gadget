"""Shared domain types used across product skills and services (learning-design §4)."""

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, ValidationInfo, model_validator
from pydantic.json_schema import SkipJsonSchema

from agent import plan, sources

Level = Literal["novice", "intermediate", "strong", "expert"]  # claimed / assessed level
TargetLevel = Literal["beginner", "intermediate", "advanced", "expert"]
Bloom = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
ConceptType = Literal["algorithm", "systems", "math", "syntax", "api", "conceptual"]


class Band(StrEnum):
    """Mastery bands (spec §4.9). Stored in concept_progress.band; set by pedagogy.band()."""

    shaky = "shaky"
    learning = "learning"
    solid = "solid"
    mastered = "mastered"


# Format preferences are an open set (spec §6). Phase 1 implements these three; others are
# accepted and stored, and the UI labels them "coming soon".
Format = str
IMPLEMENTED_FORMATS: frozenset[str] = frozenset({"reading", "quizzes", "hands_on"})


class CourseConfig(BaseModel):
    """Stored in courses.config (JSONB). New knobs = new fields with defaults, no migration."""

    topic: str = Field(min_length=2, max_length=300)
    target_hours: float = Field(default=3, ge=0.5, le=40)
    target_level: TargetLevel = "intermediate"
    self_level: Level = "intermediate"
    formats: list[Format] = Field(default_factory=lambda: ["reading", "quizzes", "hands_on"])


class Mission(BaseModel):
    """Stored in courses.mission (JSONB): what the learner is really after (spec §4.1)."""

    goal: str
    expert_means: str
    mode: Literal["cram", "foundation"] = "foundation"
    deadline: date | None = None
    analogy_domain: str | None = None


# --- concept map (spec §4.4) -------------------------------------------------------------------
# Defined here, not in skills/map-concepts/schema.py: kebab-case skill folders aren't importable,
# and services, plans and later skills all need these types. schema.py re-exports them.
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class Misbelief(BaseModel):
    """A specific wrong belief (spec §4.6–4.7): what a distractor represents, or what the grader
    found. Logged to `misconceptions` when a learner shows it."""

    label: str = Field(max_length=120, description="Short name, e.g. 'requests = limits'")
    note: str = Field(description="The underlying belief in one plain sentence")


class Remedy(BaseModel):
    """Set by code (never the model) on a remediation concept inserted by the adapt rules."""

    for_concept: str  # the concept it re-teaches
    angle: str  # the different angle it takes (spec §4.8)
    misconception: Misbelief | None  # the named belief it attacks


class Concept(BaseModel):
    id: str = Field(pattern=SLUG, max_length=64, description="Short kebab-case slug")
    title: str = Field(max_length=120)
    mastery_statement: str = Field(description='Observable outcome, starting "You can …"')
    objective_level: Bloom = Field(description="Bloom level of the mastery statement's verb")
    prereqs: list[str] = Field(description="Ids of direct prerequisites in this map")
    est_minutes: int = Field(ge=5, le=120, description="Lesson + quiz time")
    concept_type: ConceptType
    # Plan state set by code: hidden from the model's output schema (SkipJsonSchema).
    remedy: SkipJsonSchema[Remedy | None] = None

    @property
    def is_remediation(self) -> bool:
        return self.remedy is not None


class ConceptMap(BaseModel):
    """Stored in courses.template_plan and plan_versions.plan. These graph rules hold for
    every stored map, including after the learner cuts concepts (PC1.4)."""

    # 20 core concepts at most, plus room for remediation concepts the adapt rules insert.
    concepts: list[Concept] = Field(min_length=1, max_length=40)
    sequence: list[str] = Field(description="Every concept id once, each after its prereqs")
    sequence_rationale: str = Field(description="Why this order, written to the learner")
    # Concepts the learner chose to test out of: no lesson, straight to the quiz (ADR-0006).
    test_out: SkipJsonSchema[list[str]] = Field(default_factory=list)

    def concept(self, concept_id: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == concept_id), None)

    def graph(self) -> dict[str, list[str]]:
        return {c.id: c.prereqs for c in self.concepts}

    def total_minutes(self) -> int:
        return sum(c.est_minutes for c in self.concepts)

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        ids = [c.id for c in self.concepts]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"concept ids must be unique; repeated: {dupes}")
        errors = plan.structure_errors(self.graph(), self.sequence)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class PrereqChange(BaseModel):
    concept_id: str
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class StatusChange(BaseModel):
    concept_id: str
    old: str  # a ConceptStatus value (app.models); kept a string so agent/ never imports app/
    new: str


class PlanDiff(BaseModel):
    """Stored in plan_versions.diff: what changed against the previous version (spec §4.8)."""

    added: list[Concept] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    prereq_changes: list[PrereqChange] = Field(default_factory=list)
    status_changes: list[StatusChange] = Field(default_factory=list)
    test_out: list[str] = Field(default_factory=list)  # concepts the learner chose to test out of


class MapInput(BaseModel):
    config: CourseConfig
    mission: Mission
    assessed_level: Level  # where the course starts (the demonstrated level, not the claim)
    gaps: list[str]  # what the assessment showed missing; covered early
    target_minutes: int  # config.target_hours in minutes, computed in code for the model


class MapOutput(ConceptMap):
    """What map-concepts generates: tighter bounds than a stored map (Phase 1: 6–12)."""

    concepts: list[Concept] = Field(min_length=6, max_length=12)

    @model_validator(mode="after")
    def fits_input(self, info: ValidationInfo) -> Self:
        # Needs the request (ADR-0015); skipped when a stored map is read back.
        inp = (info.context or {}).get("input")
        if not isinstance(inp, MapInput):
            return self
        bad = [c.id for c in self.concepts if not c.mastery_statement.lower().startswith("you can")]
        if bad:
            raise ValueError(f'mastery_statement must start with "You can": {bad}')
        err = plan.time_error(self.total_minutes(), inp.target_minutes)
        if err:
            raise ValueError(err)
        return self


# --- lessons (spec §4.5) -----------------------------------------------------------------------
# The diagram types a lesson may use: the ones that show structure or flow (§4.5), and that the
# web renderer is tested with.
MERMAID_TYPES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram-v2", "classDiagram")


class TeachInput(BaseModel):
    """First-pass lesson input. Deliberately shareable: no learner ids, assessment or
    misconceptions (ADR-0007), so two learners with the same bucket can share a cached lesson."""

    topic: str
    target_level: TargetLevel
    analogy_domain: str | None
    formats: list[Format]  # sorted by the service, so order doesn't change the cache key
    concept: Concept
    prereq_titles: list[str]  # what the learner has already been taught for this concept


class Citation(BaseModel):
    """Where a grounded claim comes from (spec §5). `doc` and `section` are copied from the
    source tags in the prompt; `quote` lets code check that the section really says it."""

    doc: str = Field(description="The doc's slug, from <document slug=…>")
    section: str = Field(description="The section's anchor, from <section anchor=…>")
    quote: str = Field(description="Verbatim words from that section that support the claim")


class NotInDocs(BaseModel):
    """Something the learner needs that the org's docs don't cover (spec §5)."""

    point: str = Field(description="What the docs don't cover, as a short topic or question")
    general_knowledge: str | None = Field(
        description="Optional general (not org-specific) knowledge on it, or null"
    )


def citation_errors(cited: list[tuple[str, Citation]], grounding: sources.Grounding) -> list[str]:
    """Each (label, citation) names a real section of the composed docs and quotes it verbatim.
    The label ("citation [2]", "q3") names it in the error the retry sends back."""
    errors = []
    for label, c in cited:
        text = grounding.section_text(c.doc, c.section)
        if text is None:
            errors.append(
                f"{label} points at {c.doc}#{c.section}, which isn't a section of the source "
                "documents; copy `slug` and `anchor` from the tags"
            )
        elif not sources.quote_in(c.quote, text):
            errors.append(
                f"{label}'s quote isn't in {c.doc}#{c.section}; quote the section's words "
                "exactly, or cite the section that says it"
            )
    return errors


def _grounding(info: ValidationInfo) -> tuple[bool, sources.Grounding | None]:
    """(is this a fresh model output?, the docs it must be grounded in). Stored outputs are
    validated without context (ADR-0015), so these checks only run on the model's reply."""
    ctx = info.context or {}
    return "input" in ctx, ctx.get("grounding")


class LessonOutput(BaseModel):
    """Stored in lessons.content. Field order is the streaming order the learner sees."""

    explanation_md: str = Field(min_length=1, description="Counterintuitive part first")
    example_md: str = Field(min_length=1, description="One complete worked example")
    diagram_mermaid: str = Field(min_length=1, description="Mermaid source, no code fences")
    citations: list[Citation] = Field(
        default_factory=list, description="Org docs only: citations[n-1] backs each [n] marker"
    )
    not_in_docs: list[NotInDocs] = Field(default_factory=list, description="Org docs only")

    @model_validator(mode="after")
    def diagram_is_renderable(self) -> Self:
        src = self.diagram_mermaid.strip()
        if src.startswith("```"):
            raise ValueError("diagram_mermaid must be bare Mermaid source, without ``` fences")
        if not src.startswith(MERMAID_TYPES):
            raise ValueError(f"diagram_mermaid must start with one of {list(MERMAID_TYPES)}")
        if any(line.strip().startswith("click ") for line in src.splitlines()):
            raise ValueError("diagram_mermaid must not use click directives")
        return self

    @model_validator(mode="after")
    def grounded_in_the_docs(self, info: ValidationInfo) -> Self:
        fresh, grounding = _grounding(info)
        if not fresh:
            return self
        if grounding is None:
            if self.citations or self.not_in_docs:
                raise ValueError("citations and not_in_docs must be empty: no source documents")
            return self
        if not self.citations and not self.not_in_docs:
            raise ValueError(
                "a lesson for this course cites the source documents, or says in not_in_docs "
                "what they don't cover"
            )
        errors = citation_errors(
            [(f"citation [{n}]", c) for n, c in enumerate(self.citations, start=1)], grounding
        )
        used = set(
            sources.citation_markers(self.explanation_md)
            + sources.citation_markers(self.example_md)
        )
        numbers = set(range(1, len(self.citations) + 1))
        if dangling := sorted(used - numbers):
            errors.append(f"markers {dangling} have no citation (there are {len(numbers)})")
        if unused := sorted(numbers - used):
            errors.append(f"citations {unused} are never referenced by an [n] marker in the text")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# --- quizzes (spec §4.6) -----------------------------------------------------------------------
QUIZ_MCQS = 4  # = pedagogy.MCQ_QUESTIONS


class LessonDigest(BaseModel):
    """What the quiz designer needs from the lesson: its situations, so the quiz can avoid them."""

    explanation_md: str
    example_md: str


class QuizInput(BaseModel):
    """design-assessment.design input: shareable (no learner data), so it's exact-cached and
    keyed on the lesson's content (ADR-0007). `round` makes a retake a different quiz."""

    topic: str
    target_level: TargetLevel
    concept: Concept
    lesson: LessonDigest | None  # None when the learner tests out (ADR-0006)
    round: int = Field(ge=1)


class TargetedQuizInput(QuizInput):
    """design-assessment.design_targeted input: includes this learner's logged misconceptions,
    so it is never cached (ADR-0007)."""

    misconceptions: list[Misbelief] = Field(min_length=1)


class Option(BaseModel):
    id: str = Field(pattern=r"^[a-d]$")
    text: str
    misconception: Misbelief | None = Field(
        description="null only for the correct option; every distractor names its belief"
    )


class MCQ(BaseModel):
    id: str = Field(pattern=r"^q[1-4]$")
    prompt: str
    options: list[Option] = Field(min_length=4, max_length=4)
    answer: str = Field(pattern=r"^[a-d]$", description="Id of the correct option")
    transfer_situation: str = Field(description="The new situation, not one from the lesson")
    objective_level: Bloom
    targets_logged_misconception: str | None = Field(
        description="Label of a logged misconception a distractor targets, else null"
    )
    source: Citation | None = Field(
        default=None, description="Org docs only: the section the answer comes from, else null"
    )

    @model_validator(mode="after")
    def one_correct_option(self) -> Self:
        ids = [o.id for o in self.options]
        if sorted(ids) != ["a", "b", "c", "d"]:
            raise ValueError(f"{self.id}: option ids must be a, b, c, d; got {ids}")
        correct = [o.id for o in self.options if o.misconception is None]
        if correct != [self.answer]:
            raise ValueError(
                f"{self.id}: exactly the answer option ({self.answer}) must have a null "
                f"misconception; options without one: {correct}"
            )
        return self


class Rubric(BaseModel):
    score_1: str = Field(description="Wrong, or right for the wrong reason")
    score_2: str = Field(description="Partially right with visible gaps")
    score_3: str = Field(description="Right, clearly, in their own words")
    score_4: str = Field(description="Right plus correctly handles the transfer case")


class ShortItem(BaseModel):
    id: Literal["explain"] = "explain"
    prompt: str
    transfer_situation: str
    rubric: Rubric
    source: Citation | None = Field(
        default=None, description="Org docs only: the section the rubric draws on, else null"
    )


class QuizOutput(BaseModel):
    """Stored in quiz_attempts.questions, answer keys included. The API sends `public()`."""

    questions: list[MCQ] = Field(min_length=QUIZ_MCQS, max_length=QUIZ_MCQS)
    explain_item: ShortItem

    @model_validator(mode="after")
    def fits_concept(self, info: ValidationInfo) -> Self:
        ids = [q.id for q in self.questions]
        if ids != [f"q{i}" for i in range(1, QUIZ_MCQS + 1)]:
            raise ValueError(f"question ids must be q1..q{QUIZ_MCQS} in order; got {ids}")
        inp = (info.context or {}).get("input")
        if not isinstance(inp, QuizInput):
            return self
        level = inp.concept.objective_level
        if not any(q.objective_level == level for q in self.questions):
            raise ValueError(f"at least one question must be at the objective level '{level}'")
        if isinstance(inp, TargetedQuizInput):
            logged = {m.label for m in inp.misconceptions}
            if not any(q.targets_logged_misconception in logged for q in self.questions):
                raise ValueError(
                    f"at least one question must target a logged misconception: {logged}"
                )
        return self

    @model_validator(mode="after")
    def grounded_in_the_docs(self, info: ValidationInfo) -> Self:
        # Spec §5: a grounded course's quiz tests the org's actual practice, so it says where.
        fresh, grounding = _grounding(info)
        if not fresh:
            return self
        items = [(q.id, q.source) for q in self.questions] + [("explain", self.explain_item.source)]
        cited = [(label, c) for label, c in items if c is not None]
        if grounding is None:
            if cited:
                raise ValueError("every `source` must be null: no source documents")
            return self
        if not cited:
            raise ValueError("at least one question must test the docs and give its `source`")
        if errors := citation_errors(cited, grounding):
            raise ValueError("; ".join(errors))
        return self


# --- grading (spec §4.7) -----------------------------------------------------------------------
class GradeInput(BaseModel):
    """grade.grade input: the learner's own words, so never cached."""

    concept_title: str
    mastery_statement: str
    item: ShortItem
    answer: str


class GradeOutput(BaseModel):
    transfer_handled: bool = Field(description="Did the answer correctly handle the transfer case?")
    score: Literal[1, 2, 3, 4]
    feedback: str = Field(description="To the learner: what was right, what wasn't, and why")
    misconception: Misbelief | None = Field(description="The wrong belief shown, if any")

    @model_validator(mode="after")
    def four_needs_transfer(self) -> Self:
        if self.score == 4 and not self.transfer_handled:
            raise ValueError("a 4 requires transfer (spec §4.7); without it the most is 3")
        return self


# --- remediation and the "why" (spec §4.8) -----------------------------------------------------
class RemedyConcept(BaseModel):
    title: str = Field(max_length=120)
    mastery_statement: str = Field(description='Starts "You can …"')
    angle: str = Field(description="How it re-teaches differently from the original lesson")


class ExplainInput(BaseModel):
    """remediate.explain_change input (never cached: it carries misconceptions)."""

    concept: Concept
    score: Literal[1, 2, 3, 4]
    rule: str  # the pedagogy rule that fired
    misconceptions: list[Misbelief]
    lesson_explanation: str | None  # what the first lesson said, so the remedy differs


class ExplainOutput(BaseModel):
    why: str = Field(description="Plain English, to the learner: names the score and the belief")
    remediation_concept: RemedyConcept


class WarningInput(BaseModel):
    concept: Concept
    unmet_prereqs: list[Concept]


class WarningOutput(BaseModel):
    what_will_break: str = Field(description="Specific: what they'll misread or get stuck on")


class RemediationLessonInput(BaseModel):
    """remediate.lesson input: a lesson for a remediation concept (never cached)."""

    topic: str
    target_level: TargetLevel
    analogy_domain: str | None
    concept: Concept  # the remediation concept; `remedy` names the angle and the belief
    original_concept_title: str
    original_explanation: str | None
