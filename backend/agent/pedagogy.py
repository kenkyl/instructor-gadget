"""Deterministic pedagogy rules (CLAUDE.md: "skills do language; code does decisions").

Scoring, mastery, bands, the unlock gate, adaptation and FSRS scheduling all land here in
PC2.1. For now: which concepts a new plan starts with unlocked.
"""

from agent.plan import Graph


def initially_unlocked(graph: Graph) -> set[str]:
    """A concept starts unlocked only if it has no prerequisites in the plan (spec §4.8).

    Everything else unlocks once every prereq is solid or better, which is decided by the
    unlock gate on quiz results (PC2.1).
    """
    return {c for c, prereqs in graph.items() if not prereqs}
