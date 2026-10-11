"""grade: the 1–4 rubric grade for a short answer (spec §4.7). A 4 requires transfer
(validator). Models live in agent/types.py so services can import them."""

from agent.types import GradeInput, GradeOutput

CALLS = {"grade": (GradeInput, GradeOutput)}
