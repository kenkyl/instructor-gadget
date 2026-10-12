"""agent/partial.py: streamed JSON text → per-field deltas."""

import json

from agent.partial import FieldDelta, FieldDeltas

LESSON = {
    "explanation_md": "A pool \"max\" isn't a target.\n\nIt's a ceiling — 🚦.",
    "example_md": "Set max=10 and send 50 requests.",
    "diagram_mermaid": "flowchart LR\n  A --> B",
    "citations": [],
}


def stream(text: str, size: int) -> list[FieldDelta]:
    d = FieldDeltas(["explanation_md", "example_md", "diagram_mermaid"])
    out: list[FieldDelta] = []
    for i in range(0, len(text), size):
        out += d.feed(text[i : i + size])
    return out


def rebuild(deltas: list[FieldDelta]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for d in deltas:
        fields[d.field] = d.text if d.replace else fields.get(d.field, "") + d.text
    return fields


def test_deltas_rebuild_every_field_at_any_chunk_size() -> None:
    text = json.dumps(LESSON)  # escapes quotes, newlines and non-ASCII
    for size in (1, 2, 3, 7, 50, len(text)):
        fields = rebuild(stream(text, size))
        assert fields == {k: LESSON[k] for k in fields} and len(fields) == 3, size


def test_fields_arrive_in_order_and_only_grow() -> None:
    deltas = stream(json.dumps(LESSON), 5)
    order = [d.field for d in deltas]
    assert order == sorted(order, key=["explanation_md", "example_md", "diagram_mermaid"].index)
    assert not any(d.replace for d in deltas)


def test_whitespace_and_reset() -> None:
    d = FieldDeltas(["explanation_md"])
    assert d.feed("  ") == []
    assert d.feed('{"explanation_md": "ab') == [FieldDelta("explanation_md", "ab")]
    d.reset()  # a retry starts a new document
    assert d.feed('{"explanation_md": "xy') == [FieldDelta("explanation_md", "xy")]
