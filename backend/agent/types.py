"""Shared domain types used across product skills and services (learning-design §4)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

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

    topic: str
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
