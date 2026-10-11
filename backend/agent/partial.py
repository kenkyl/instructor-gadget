"""Streamed JSON text → per-field text deltas, so a surface can render fields as they're written.

The model streams its structured output as JSON text. Parsing the buffer so far in partial mode
("trailing-strings": an unfinished string counts with what it has) gives the fields written so
far; diffing against what was already sent gives each string field's new text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_core import from_json


@dataclass(frozen=True)
class FieldDelta:
    field: str
    text: str
    replace: bool = False  # True: `text` is the field's whole value, not an append


class FieldDeltas:
    def __init__(self, fields: Sequence[str]) -> None:
        self.fields = fields  # the top-level string fields to stream, in output order
        self.reset()

    def reset(self) -> None:
        """Start over (the wrapper is retrying after invalid output)."""
        self.buf = ""
        self.sent: dict[str, str] = {}

    def feed(self, text: str) -> list[FieldDelta]:
        self.buf += text
        try:
            partial = from_json(self.buf, allow_partial="trailing-strings")
        except ValueError:
            return []  # nothing parseable yet (e.g. only whitespace)
        if not isinstance(partial, dict):
            return []
        deltas: list[FieldDelta] = []
        for field in self.fields:
            value = partial.get(field)
            if not isinstance(value, str):
                continue
            prev = self.sent.get(field, "")
            if value.startswith(prev):
                if len(value) > len(prev):
                    deltas.append(FieldDelta(field, value[len(prev) :]))
            else:
                # Shouldn't happen with trailing-strings, but never send a wrong append.
                deltas.append(FieldDelta(field, value, replace=True))
            self.sent[field] = value
        return deltas
