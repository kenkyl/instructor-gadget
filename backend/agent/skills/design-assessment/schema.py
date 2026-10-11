"""design-assessment: the zero-hint quiz for one concept (spec §4.6).

Models live in agent/types.py (this folder name isn't importable). The stored output keeps
answer keys server-side; the API sends a public view without them.
"""

from agent.types import QuizInput, QuizOutput, TargetedQuizInput

CALLS = {"design": (QuizInput, QuizOutput), "design_targeted": (TargetedQuizInput, QuizOutput)}
