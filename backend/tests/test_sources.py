"""Section anchors and hashes (agent/sources.py): the rules citations depend on."""

import pytest

from agent import sources
from agent.sources import DocSection


def _anchors(md: str) -> list[str]:
    return [s.anchor for s in sources.parse_sections(md)]


def test_sections_in_document_order_with_slugged_anchors() -> None:
    md = "# Runbook\n\nIntro.\n\n## When you are paged\n\n### Severity levels (SEV1–SEV3)\n"
    assert sources.parse_sections(md) == [
        DocSection(anchor="runbook", heading="Runbook"),
        DocSection(anchor="when-you-are-paged", heading="When you are paged"),
        DocSection(anchor="severity-levels-sev1sev3", heading="Severity levels (SEV1–SEV3)"),
    ]


def test_headings_inside_code_fences_are_code_not_sections() -> None:
    md = "## Real\n```bash\n# roll back\nkubectl undo\n```\n~~~\n## also code\n~~~\n## After\n"
    assert _anchors(md) == ["real", "after"]


def test_a_longer_fence_is_not_closed_by_a_shorter_one() -> None:
    md = "````md\n```\n## still code\n```\n````\n## Real\n"
    assert _anchors(md) == ["real"]


def test_repeated_headings_get_suffixes_and_suffixes_never_collide() -> None:
    assert _anchors("## Impact\n## Impact\n## Impact\n") == ["impact", "impact-2", "impact-3"]
    # "Impact 2" really slugs to "impact-2": the second "Impact" must step past it.
    assert _anchors("## Impact\n## Impact 2\n## Impact\n") == ["impact", "impact-2", "impact-3"]


def test_inline_marks_and_closing_hashes_are_stripped() -> None:
    [s] = sources.parse_sections("## The `model-router` pool ##\n")
    assert s == DocSection(anchor="the-model-router-pool", heading="The model-router pool")
    # A "#" that is part of the word stays.
    assert sources.parse_sections("## Learning C#\n")[0].heading == "Learning C#"


def test_no_space_after_hashes_is_not_a_heading() -> None:
    assert sources.parse_sections("#hashtag\n\ntext #1 and #2\n") == []


def test_empty_slug_falls_back_to_section() -> None:
    assert _anchors("## ???\n## !!!\n") == ["section", "section-2"]


def test_normalize_makes_line_endings_irrelevant_to_the_hash() -> None:
    unix = "# Doc\n\n## A\ntext\n"
    windows = "# Doc\r\n\r\n## A\r\ntext\r\n\r\n"
    assert sources.content_hash(unix) == sources.content_hash(windows)
    assert sources.content_hash(unix) != sources.content_hash(unix + "more\n")
    assert sources.normalize(windows) == unix


def test_doc_set_hash_ignores_order_and_sees_every_change() -> None:
    a, b = ("on-call-runbook", "h1"), ("service-map", "h2")
    base = sources.doc_set_hash([a, b])
    assert len(base) == 64  # fits courses.doc_set_hash
    assert sources.doc_set_hash([b, a]) == base
    assert sources.doc_set_hash([a, ("service-map", "h3")]) != base  # an edit
    assert sources.doc_set_hash([a]) != base  # a removal
    assert sources.doc_set_hash([a, ("service-map-v2", "h2")]) != base  # a rename


def test_empty_doc_set_is_an_error() -> None:
    with pytest.raises(ValueError):
        sources.doc_set_hash([])


def test_doc_slug_is_ascii_kebab_case_and_bounded() -> None:
    assert sources.doc_slug("On-call runbook") == "on-call-runbook"
    assert sources.doc_slug("Postmortem: model-router pool (12 Mar)") == (
        "postmortem-model-router-pool-12-mar"
    )
    assert sources.doc_slug("Café für Ops") == "cafe-fur-ops"
    assert sources.doc_slug("日本語") == "doc"  # nothing ASCII left: a fallback, never empty
    assert len(sources.doc_slug("x" * 300)) == 100
