"""Concept-map rules, decided in code (spec §4.4: "validated in code").

Everything here works on a plain prerequisite graph, `{concept_id: [prereq_id, ...]}`, so the
rules are pure functions: no models, no I/O, trivially testable. `ConceptMap` (agent/types.py)
calls them as Pydantic validators, so an error in a generated map makes the LLM wrapper re-ask
once with that error (ADR-0013).

Edges point from a concept to what it needs: `{"b": ["a"]}` means "b requires a", so a must
be learned first.
"""

import math
from collections.abc import Mapping, Sequence

Graph = Mapping[str, Sequence[str]]

TIME_TOLERANCE_PCT = 15  # total minutes within ±15% of the target (spec §4.4)


def find_unknown_prereqs(graph: Graph) -> list[tuple[str, str]]:
    """Every (concept, prereq) pair where the prereq isn't a concept in the graph.

    Ordered by concept (graph order), then prereq (as listed). Example:
        {"a": [], "b": ["a", "x"]} -> [("b", "x")]
    """
    return [
        (concept, prereq)
        for concept, prereqs in graph.items()
        for prereq in prereqs
        if prereq not in graph
    ]


def find_cycle(graph: Graph) -> list[str] | None:
    """One cycle as a path that starts and ends at the same id, or None if the graph is a DAG.

    Examples:
        {"a": ["a"]}                -> ["a", "a"]          (a concept requiring itself)
        {"a": ["b"], "b": ["a"]}    -> ["a", "b", "a"]
        diamond: d needs b and c, both need a -> None    (shared prereqs aren't a cycle)

    Prereqs that aren't in the graph are skipped (find_unknown_prereqs reports those).
    The path follows prereq edges; which cycle, and where it starts, is unspecified.
    """
    # Iterative DFS, so a long chain can't hit Python's recursion limit. `stack` is the current
    # route, each concept paired with its not-yet-visited prereqs. Reaching a concept that's
    # `on_path` closes a loop; reaching one that's `done` (fully explored, no cycle below it) is
    # just a shared prereq, as in the diamond.
    done: set[str] = set()
    for start in graph:
        if start in done:
            continue
        stack = [(start, iter(graph[start]))]
        on_path = {start}
        while stack:
            concept, prereqs = stack[-1]
            nxt = next(prereqs, None)
            if nxt is None:  # all of concept's prereqs explored
                stack.pop()
                on_path.remove(concept)
                done.add(concept)
            elif nxt in on_path:
                path = [c for c, _ in stack]
                return path[path.index(nxt) :] + [nxt]
            elif nxt in graph and nxt not in done:
                stack.append((nxt, iter(graph[nxt])))
                on_path.add(nxt)
    return None


def sequence_errors(graph: Graph, sequence: Sequence[str]) -> list[str]:
    """The learning order must list every concept exactly once, each after its prereqs."""
    errors: list[str] = []
    missing = [c for c in graph if c not in sequence]
    extra = [c for c in sequence if c not in graph]
    dupes = sorted({c for c in sequence if sequence.count(c) > 1})
    if missing:
        errors.append(f"sequence is missing {missing}")
    if extra:
        errors.append(f"sequence lists unknown concepts {extra}")
    if dupes:
        errors.append(f"sequence lists {dupes} more than once")
    position = {c: i for i, c in enumerate(sequence)}
    for concept, prereqs in graph.items():
        for p in prereqs:
            if concept in position and p in position and position[p] > position[concept]:
                errors.append(f"sequence puts '{concept}' before its prereq '{p}'")
    return errors


def time_error(total_minutes: int, target_minutes: int) -> str | None:
    # Integer math: in floats 180 * 1.15 == 206.99999999999997, which would reject exactly +15%.
    if abs(total_minutes - target_minutes) * 100 <= TIME_TOLERANCE_PCT * target_minutes:
        return None
    low = math.ceil(target_minutes * (100 - TIME_TOLERANCE_PCT) / 100)
    high = math.floor(target_minutes * (100 + TIME_TOLERANCE_PCT) / 100)
    return (
        f"est_minutes add up to {total_minutes}, but the target is {target_minutes} "
        f"(allowed {low}–{high}); adjust estimates or the number of concepts"
    )


def structure_errors(graph: Graph, sequence: Sequence[str]) -> list[str]:
    """Graph rules that hold for every stored map: known prereqs, no cycle, a valid order."""
    errors = [
        f"'{concept}' lists unknown prereq '{prereq}' (prereqs must be concept ids in this map)"
        for concept, prereq in find_unknown_prereqs(graph)
    ]
    cycle = find_cycle(graph)
    if cycle:
        errors.append(f"prerequisite cycle: {' -> '.join(cycle)}")
    else:  # with a cycle there's no valid order, so order errors would only be noise
        errors.extend(sequence_errors(graph, sequence))
    return errors


def dependents(graph: Graph, concept_id: str) -> list[str]:
    """Concepts that list `concept_id` as a direct prereq, in graph order."""
    return [c for c, prereqs in graph.items() if concept_id in prereqs]


def remove_concept(graph: Graph, concept_id: str) -> dict[str, list[str]]:
    """The graph without `concept_id`, with its dependents rewired (ADR-0017).

    Each dependent inherits the removed concept's own prereqs, so ordering still holds:
    A ← B ← C, remove B  =>  A ← C. Duplicates are dropped and order is kept, so a dependent
    that already needed A doesn't list it twice.
    """
    inherited = list(graph.get(concept_id, []))
    rewired: dict[str, list[str]] = {}
    for c, prereqs in graph.items():
        if c == concept_id:
            continue
        if concept_id in prereqs:
            merged = [p for p in prereqs if p != concept_id] + inherited
            prereqs = list(dict.fromkeys(merged))
        rewired[c] = list(prereqs)
    return rewired
