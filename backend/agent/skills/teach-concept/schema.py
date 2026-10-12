"""teach-concept: one just-in-time lesson for one concept (spec §4.5).

The models live in agent/types.py because this folder name isn't importable and services need
them. The input is shareable across learners by design (ADR-0007).
"""

from agent.types import LessonOutput, TeachInput

CALLS = {"teach": (TeachInput, LessonOutput)}
