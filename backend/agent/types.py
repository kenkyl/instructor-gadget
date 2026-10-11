"""Shared domain types used across product skills and services (learning-design §4)."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from agent import plan

Level = Literal["novice", "intermediate", "strong", "expert"]  # claimed / assessed level
TargetLevel = Literal["beginner", "intermediate", "advanced", "expert"]
Bloom = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
ConceptType = Literal["algorithm", "systems", "math", "syntax", "api", "conceptual"]

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


class Concept(BaseModel):
    id: str = Field(pattern=SLUG, max_length=64, description="Short kebab-case slug")
    title: str = Field(max_length=120)
    mastery_statement: str = Field(description='Observable outcome, starting "You can …"')
    objective_level: Bloom = Field(description="Bloom level of the mastery statement's verb")
    prereqs: list[str] = Field(description="Ids of direct prerequisites in this map")
    est_minutes: int = Field(ge=5, le=120, description="Lesson + quiz time")
    concept_type: ConceptType


class ConceptMap(BaseModel):
    """Stored in courses.template_plan and plan_versions.plan. These graph rules hold for
    every stored map, including after the learner cuts concepts (PC1.4)."""

    concepts: list[Concept] = Field(min_length=1, max_length=20)
    sequence: list[str] = Field(description="Every concept id once, each after its prereqs")
    sequence_rationale: str = Field(description="Why this order, written to the learner")

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
