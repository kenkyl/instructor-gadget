"""The PC3.2 eval's labelled sets stay well-formed, and the threshold it chose is the one in use.

The eval itself (`make eval-cache`) needs the real model; these checks don't.
"""

from collections import Counter
from dataclasses import fields

from agent.semantic import DEFAULT_DISTANCE_THRESHOLD, SemanticKey
from app.config import Settings
from evals.cache_eval import load_guard_set, load_pairs


def test_cache_pairs_are_labelled_and_unique() -> None:
    pairs = load_pairs()
    labels = Counter(p.label for p in pairs)
    assert labels["hit"] >= 6 and labels["miss"] >= 6  # the brief's minimum on each side
    assert len({p.id for p in pairs}) == len(pairs)
    for p in pairs:
        assert (
            len(p.stored.splitlines()) == 3 and len(p.request.splitlines()) == 3
        )  # topic/title/mastery
        assert set(p.request_bucket) <= {f.name for f in fields(SemanticKey)} - {"text"}


def test_guard_set_has_both_sides() -> None:
    gs = load_guard_set()
    assert len(gs.allow) >= 15 and len([b for b in gs.block if not b.known_miss]) >= 8
    assert not set(gs.allow) & {b.text for b in gs.block}


def test_config_default_is_the_evaluated_threshold() -> None:
    assert (
        Settings.model_fields["semantic_cache_distance_threshold"].default
        == DEFAULT_DISTANCE_THRESHOLD
    )
