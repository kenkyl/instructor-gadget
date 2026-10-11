"""diagnose: probe (questions at the claimed level) and assess (demonstrated level)."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from agent.types import CourseConfig, Level, Mission


# --- probe ---------------------------------------------------------------------------------
class ProbeInput(BaseModel):
    config: CourseConfig
    mission: Mission


class ProbeQuestion(BaseModel):
    id: str = Field(description="Short stable id: q1, q2, ...")
    prompt: str = Field(description="The question, answerable in 2-4 sentences of free text")
    targets_concept: str = Field(description="The one concept this question checks")
    level: Level = Field(description="Level the question is pitched at (the claimed level)")


class ProbeOutput(BaseModel):
    questions: list[ProbeQuestion] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")
        return self


# --- assess --------------------------------------------------------------------------------
class ProbeAnswer(BaseModel):
    question_id: str
    answer: str


class AssessInput(BaseModel):
    config: CourseConfig
    mission: Mission
    probe: ProbeOutput
    answers: list[ProbeAnswer]


class Evidence(BaseModel):
    question_id: str
    observation: str = Field(description="What the answer showed or failed to show")
    points_to: Level


class AssessOutput(BaseModel):
    claimed_level: Level
    assessed_level: Level
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(min_length=1)
    gaps: list[str]
    adjustment_message: str | None = Field(
        default=None, description="Required when assessed_level != claimed_level; else null"
    )

    @model_validator(mode="after")
    def explain_adjustments(self) -> Self:
        # Spec §4.3: never re-level silently. A validation error here makes the LLM wrapper
        # retry once with this message (PC1.1).
        if self.assessed_level != self.claimed_level and not self.adjustment_message:
            raise ValueError("adjustment_message is required when assessed_level != claimed_level")
        return self


CALLS = {
    "probe": (ProbeInput, ProbeOutput),
    "assess": (AssessInput, AssessOutput),
}
