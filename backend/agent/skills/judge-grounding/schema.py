"""judge-grounding: the eval-only grounding judge (build brief §6.5, ADR-0031). Models live in
agent/types.py (kebab-case folders aren't importable)."""

from agent.types import JudgeInput, JudgeOutput

CALLS = {"judge": (JudgeInput, JudgeOutput)}
