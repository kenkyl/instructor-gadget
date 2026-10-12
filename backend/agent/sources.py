"""Grounding sources (spec §5): what makes an org doc citable, and when two doc sets are the same.

Org docs are markdown. A citation names a doc and a section anchor, so anchors must be stable,
unique within a doc and computed by code: the model only ever chooses among them. The doc-set
hash is part of the semantic-cache bucket (ADR-0007), so the same set must hash the same
whatever order an admin ticked the docs in, and any edit must change it (ADR-0028).

Pure functions, no I/O: `app/` stores the results, `agent/` composes them into prompts (PC4.2).
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable

from pydantic import BaseModel

# Context stuffing (build brief §4, decision 4): the whole doc set goes in the prompt, so it
# has a budget. ~4 characters per token puts MAX_SET_CHARS near 40k tokens, under the brief's
# "about 50k" and leaving room for the lesson instructions. RAG is the upgrade past this.
MAX_DOC_CHARS = 60_000
MAX_SET_CHARS = 160_000


class DocSection(BaseModel):
    """One citable section of a doc: stored in `org_docs.sections` (JSONB)."""

    anchor: str
    heading: str


# A fenced block opens and closes with 3+ backticks or tildes. Headings inside one (a `# comment`
# in a shell snippet) are code, not sections.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# ATX headings only (`#`..`######`), with an optional closing run of `#`s ("## Title ##").
# Setext headings (underlined with === or ---) aren't recognised.
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def normalize(content_md: str) -> str:
    """Line endings and surrounding whitespace, so the same doc saved on two machines hashes
    the same. This is what gets stored, so the stored text always matches its hash."""
    return content_md.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def content_hash(content_md: str) -> str:
    return hashlib.sha256(normalize(content_md).encode()).hexdigest()


def slugify(text: str) -> str:
    """Lowercase words joined by `-`, GitHub-style: inline marks and punctuation dropped,
    unicode letters kept. Never empty."""
    s = re.sub(r"[`*]", "", text).lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s or "section"


def doc_slug(title: str) -> str:
    """The citation key for a doc, from its title: ASCII kebab-case, at most 100 characters
    (`on-call-runbook`). It matches `agent.types.SLUG`, so it is safe in URLs and prompts."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:100].strip("-")
    return slug or "doc"


def parse_sections(content_md: str) -> list[DocSection]:
    """Every heading outside a code fence, in document order, with a unique anchor.

    A repeated heading gets `-2`, `-3`, … so two "Impact" sections stay distinct, and the
    suffix loop also covers a heading that literally slugs to an already-issued suffix."""
    sections: list[DocSection] = []
    used: set[str] = set()
    fence: str | None = None
    for line in normalize(content_md).split("\n"):
        marker = _FENCE.match(line)
        if fence is None:
            if marker:
                fence = marker.group(1)
                continue
        else:
            closes = (
                marker
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and line.strip() == marker.group(1)
            )
            if closes:
                fence = None
            continue
        heading = _HEADING.match(line)
        if heading is None:
            continue
        text = re.sub(r"[`*]", "", heading.group(2)).strip()
        base = slugify(text)
        anchor, n = base, 1
        while anchor in used:
            n += 1
            anchor = f"{base}-{n}"
        used.add(anchor)
        sections.append(DocSection(anchor=anchor, heading=text))
    return sections


def doc_set_hash(docs: Iterable[tuple[str, str]]) -> str:
    """Hash of a doc set from its (slug, content_hash) pairs, independent of order. The slug is
    in it because lessons cite docs by slug: a rename changes what a lesson says."""
    lines = sorted(f"{slug}:{digest}" for slug, digest in docs)
    if not lines:
        raise ValueError("a doc set needs at least one doc")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
