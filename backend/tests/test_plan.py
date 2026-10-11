"""agent/plan.py: the deterministic concept-map rules (spec §4.4)."""

from agent.pedagogy import initially_unlocked
from agent.plan import (
    dependents,
    find_cycle,
    find_unknown_prereqs,
    remove_concept,
    sequence_errors,
    time_error,
)


def assert_is_cycle(graph: dict[str, list[str]], path: list[str] | None) -> None:
    """A real cycle: closes on itself, and every step follows a prereq edge in the graph."""
    assert path is not None, "expected a cycle"
    assert len(path) >= 2 and path[0] == path[-1], f"not a closed path: {path}"
    for a, b in zip(path, path[1:], strict=False):
        # Either direction is fine: a needs b, or b needs a, consistently along the path.
        assert b in graph.get(a, []) or a in graph.get(b, []), f"no edge {a}–{b} in {path}"
    forward = all(b in graph[a] for a, b in zip(path, path[1:], strict=False))
    backward = all(a in graph[b] for a, b in zip(path, path[1:], strict=False))
    assert forward or backward, f"path changes direction: {path}"


# --- ★ your turn ---------------------------------------------------------------------------
class TestUnknownPrereqs:
    def test_all_known(self) -> None:
        assert find_unknown_prereqs({"a": [], "b": ["a"], "c": ["a", "b"]}) == []

    def test_reports_each_unknown_pair_in_order(self) -> None:
        graph = {"a": ["x"], "b": ["a", "y", "z"], "c": []}
        assert find_unknown_prereqs(graph) == [("a", "x"), ("b", "y"), ("b", "z")]

    def test_empty_graph(self) -> None:
        assert find_unknown_prereqs({}) == []


class TestFindCycle:
    def test_dag_has_no_cycle(self) -> None:
        assert find_cycle({"a": [], "b": ["a"], "c": ["b"]}) is None

    def test_diamond_is_not_a_cycle(self) -> None:
        # The classic false positive: "a" is reached twice (via b and via c), but that's
        # a shared prerequisite, not a loop. A plain visited-set DFS gets this wrong.
        graph = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
        assert find_cycle(graph) is None

    def test_self_loop(self) -> None:
        graph = {"a": ["a"], "b": []}
        assert_is_cycle(graph, find_cycle(graph))

    def test_two_cycle(self) -> None:
        graph = {"a": ["b"], "b": ["a"]}
        assert_is_cycle(graph, find_cycle(graph))

    def test_three_cycle_reported_as_a_path(self) -> None:
        graph = {"a": ["c"], "b": ["a"], "c": ["b"]}
        path = find_cycle(graph)
        assert_is_cycle(graph, path)
        assert path is not None and set(path) == {"a", "b", "c"}

    def test_cycle_not_reachable_from_the_first_concept(self) -> None:
        # Starting a search only from the first node would miss this one.
        graph = {"a": [], "b": ["a"], "c": ["d"], "d": ["c"]}
        path = find_cycle(graph)
        assert_is_cycle(graph, path)
        assert path is not None and set(path) == {"c", "d"}

    def test_path_into_a_cycle_is_trimmed(self) -> None:
        # a leads into the b<->c loop but isn't part of it, so it mustn't appear in the path.
        graph = {"a": ["b"], "b": ["c"], "c": ["b"]}
        path = find_cycle(graph)
        assert_is_cycle(graph, path)
        assert path is not None and set(path) == {"b", "c"}

    def test_unknown_prereqs_are_ignored(self) -> None:
        assert find_cycle({"a": ["ghost"], "b": ["a"]}) is None

    def test_long_chain_is_fine(self) -> None:
        # 500 concepts in a line: a recursive DFS still fits Python's default limit (1000),
        # but an iterative one is the robust choice. Either passes.
        graph = {f"c{i}": ([f"c{i - 1}"] if i else []) for i in range(500)}
        assert find_cycle(graph) is None


# --- already implemented -------------------------------------------------------------------
def test_sequence_must_cover_every_concept_once_in_prereq_order() -> None:
    graph = {"a": [], "b": ["a"], "c": ["b"]}
    assert sequence_errors(graph, ["a", "b", "c"]) == []
    assert sequence_errors(graph, ["b", "a", "c"]) == ["sequence puts 'b' before its prereq 'a'"]
    errors = sequence_errors(graph, ["a", "a", "c", "z"])
    assert "sequence is missing ['b']" in errors
    assert "sequence lists unknown concepts ['z']" in errors
    assert "sequence lists ['a'] more than once" in errors


def test_time_within_fifteen_percent() -> None:
    assert time_error(180, 180) is None
    assert time_error(153, 180) is None  # -15% exactly
    assert time_error(207, 180) is None  # +15% exactly
    err = time_error(240, 180)
    assert err is not None and "add up to 240" in err and "153–207" in err


# --- PC1.4: removing a concept (ADR-0017) --------------------------------------------------
def test_dependents_are_direct_only() -> None:
    graph = {"a": [], "b": ["a"], "c": ["b"], "d": ["a", "c"]}
    assert dependents(graph, "a") == ["b", "d"]
    assert dependents(graph, "d") == []


def test_removing_a_middle_concept_rewires_its_dependents() -> None:
    # A <- B <- C, cut B: C inherits A, so C still comes after A.
    assert remove_concept({"a": [], "b": ["a"], "c": ["b"]}, "b") == {"a": [], "c": ["a"]}


def test_removing_a_root_frees_its_dependents() -> None:
    assert remove_concept({"a": [], "b": ["a"], "c": ["a", "b"]}, "a") == {"b": [], "c": ["b"]}


def test_rewiring_drops_duplicates_and_keeps_order() -> None:
    graph = {"a": [], "x": [], "b": ["a", "x"], "c": ["x", "b"]}
    # c needed x and b; b needed a and x. Without b, c needs x (already there) and a.
    assert remove_concept(graph, "b")["c"] == ["x", "a"]


def test_rewired_graph_stays_valid() -> None:
    graph = {"a": [], "b": ["a"], "c": ["b"], "d": ["b", "c"]}
    after = remove_concept(graph, "b")
    assert find_unknown_prereqs(after) == []
    assert find_cycle(after) is None
    assert sequence_errors(after, ["a", "c", "d"]) == []  # the old order minus b still works


def test_only_concepts_without_prereqs_start_unlocked() -> None:
    assert initially_unlocked({"a": [], "b": ["a"], "c": [], "d": ["b", "c"]}) == {"a", "c"}
