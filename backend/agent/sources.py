"""Grounding sources (spec §5): what makes an org doc citable, and when two doc sets are the same.

Org docs are markdown. A citation names a doc and a section anchor, so anchors must be stable,
unique within a doc and computed by code: the model only ever chooses among them. The doc-set
hash is part of the semantic-cache bucket (ADR-0007), so the same set must hash the same
whatever order an admin ticked the docs in, and any edit must change it (ADR-0028).

Grounded calls (PC4.2, ADR-0029): `compose()` renders a doc set into the prompt with every
citable section tagged by its anchor, and hashes exactly the docs it rendered. The output checks
(`agent/types.py`) then hold each citation to a real section and a verbatim quote from it.

Pure functions, no I/O: `app/` stores and loads docs, `agent/` composes them into prompts.
"""

import hashlib
import html
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

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


def _scan(content: str) -> list[tuple[DocSection, int]]:
    """Every heading outside a code fence with its line number in `content` (normalized)."""
    found: list[tuple[DocSection, int]] = []
    used: set[str] = set()
    fence: str | None = None
    for number, line in enumerate(content.split("\n")):
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
        found.append((DocSection(anchor=anchor, heading=text), number))
    return found


def parse_sections(content_md: str) -> list[DocSection]:
    """Every heading outside a code fence, in document order, with a unique anchor.

    A repeated heading gets `-2`, `-3`, … so two "Impact" sections stay distinct, and the
    suffix loop also covers a heading that literally slugs to an already-issued suffix."""
    return [section for section, _ in _scan(normalize(content_md))]


def split_sections(content_md: str) -> tuple[str, list[tuple[DocSection, str]]]:
    """(text before the first heading, [(section, its text)]). A section's text runs from its
    heading to the next heading of any level, so a citation points at the words under exactly
    that heading, not at a parent that merely contains them."""
    lines = normalize(content_md).rstrip("\n").split("\n")
    found = _scan("\n".join(lines))
    preamble = "\n".join(lines[: found[0][1]] if found else lines).strip()
    starts = [n for _, n in found] + [len(lines)]
    parts = [
        (section, "\n".join(lines[starts[i] : starts[i + 1]]).strip())
        for i, (section, _) in enumerate(found)
    ]
    return preamble, parts


def doc_set_hash(docs: Iterable[tuple[str, str]]) -> str:
    """Hash of a doc set from its (slug, content_hash) pairs, independent of order. The slug is
    in it because lessons cite docs by slug: a rename changes what a lesson says."""
    lines = sorted(f"{slug}:{digest}" for slug, digest in docs)
    if not lines:
        raise ValueError("a doc set needs at least one doc")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# --- grounded prompts (PC4.2, ADR-0029) --------------------------------------------------------
@dataclass(frozen=True)
class SourceDoc:
    slug: str
    title: str
    content_md: str


@dataclass(frozen=True)
class Grounding:
    """The doc set one grounded call is answered from.

    `text` goes in the system prompt; `doc_set_hash` is the hash of exactly those docs (not the
    value stored on the course, which a re-seeded doc can leave stale: ADR-0028), and keys both
    cache tiers; `sections` holds each citable section's text, so a citation can be checked."""

    org_id: str
    text: str
    doc_set_hash: str
    sections: Mapping[str, Mapping[str, str]]  # doc slug -> anchor -> section text

    def section_text(self, doc: str, anchor: str) -> str | None:
        return self.sections.get(doc, {}).get(anchor)


def compose(org_id: str, docs: Iterable[SourceDoc]) -> Grounding:
    """Render a doc set for the prompt. Docs are sorted by slug, so the same set always renders
    to the same bytes (stable cache keys, and a prompt prefix the API could cache). Each
    section is wrapped in a tag carrying its anchor: the model copies anchors, never invents
    them."""
    by_slug = {d.slug: d for d in docs}
    if not by_slug:
        raise ValueError("a grounded call needs at least one doc")
    rendered: list[str] = []
    sections: dict[str, dict[str, str]] = {}
    hashes: list[tuple[str, str]] = []
    for slug in sorted(by_slug):
        doc = by_slug[slug]
        content = normalize(doc.content_md)
        hashes.append((slug, content_hash(content)))
        preamble, parts = split_sections(content)
        sections[slug] = {section.anchor: text for section, text in parts}
        out = [f'<document slug="{slug}" title="{html.escape(doc.title)}">']
        if preamble:
            out.append(preamble)
        for section, text in parts:
            out.append(f'<section anchor="{section.anchor}">\n{text}\n</section>')
        out.append("</document>")
        rendered.append("\n".join(out))
    return Grounding(
        org_id=org_id,
        text="<documents>\n" + "\n\n".join(rendered) + "\n</documents>",
        doc_set_hash=doc_set_hash(hashes),
        sections=sections,
    )


# Formatting that a quote may drop or change without changing its words: emphasis and code
# marks, table pipes, heading and quote markers, curly quotes and long dashes.
_QUOTE_STRIP = re.compile(r"[*_`|#>]")
_QUOTE_CHARS = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)
MIN_QUOTE_CHARS = 8


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)
    return " ".join(_QUOTE_STRIP.sub(" ", text).lower().split())


def quote_in(quote: str, section_text: str) -> bool:
    """Is `quote` really in the section? Compared as plain words (case, whitespace and markdown
    formatting ignored), because the check is about the words, not how they were typeset."""
    q = _plain(quote).strip(" .…")
    return len(q) >= MIN_QUOTE_CHARS and q in _plain(section_text)


_FENCED_BLOCK = re.compile(r"^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1[ \t]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"(`+).+?\1", re.DOTALL)
# `[3]` cites citations[2]. Not when it's a link's text (`[3](…)`): that isn't a citation.
CITATION_MARKER = re.compile(r"\[(\d{1,2})\](?!\()")


def citation_markers(markdown: str) -> list[int]:
    """The `[n]` citation markers in prose, in order. Code is skipped: `rows[1]` in a snippet
    isn't a citation."""
    prose = _INLINE_CODE.sub(" ", _FENCED_BLOCK.sub(" ", markdown))
    return [int(m) for m in CITATION_MARKER.findall(prose)]
