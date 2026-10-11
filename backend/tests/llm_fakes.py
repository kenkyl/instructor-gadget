"""A fake AsyncAnthropic for tests: replays scripted responses and records every request.

Only `client.beta.messages.create` is faked, because that's all the wrapper calls. Responses
are real SDK `BetaMessage` objects, so the wrapper is exercised against the true types.
"""

import json
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel


def message(
    output: BaseModel | dict[str, Any] | str,
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5-5",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    refusal_category: str | None = None,
) -> BetaMessage:
    if isinstance(output, BaseModel):
        text = output.model_dump_json()
    elif isinstance(output, dict):
        text = json.dumps(output)
    else:
        text = output
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [
                # Current models return thinking blocks first; the retry must echo them back.
                {"type": "thinking", "thinking": "", "signature": "sig_test"},
                {"type": "text", "text": text},
            ],
            "stop_reason": stop_reason,
            "stop_details": (
                {"type": "refusal", "category": refusal_category} if refusal_category else None
            ),
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


class _Messages:
    def __init__(self, script: list[BetaMessage | Exception]) -> None:
        self.script = script
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        # Snapshot the messages list: the wrapper appends to it after this call returns.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _Beta:
    def __init__(self, messages: _Messages) -> None:
        self.messages = messages


class FakeAnthropic:
    def __init__(self, *script: BetaMessage | Exception) -> None:
        self.messages = _Messages(list(script))
        self.beta = _Beta(self.messages)

    def reply(self, *script: BetaMessage | Exception) -> None:
        """Queue the next responses."""
        self.messages.script.extend(script)

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.messages.requests

    def as_client(self) -> anthropic.AsyncAnthropic:
        return cast(anthropic.AsyncAnthropic, self)


class MemorySink:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def record(self, rec: Any) -> None:
        self.records.append(rec)
