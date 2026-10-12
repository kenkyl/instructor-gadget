"""A fake AsyncAnthropic for tests: replays scripted responses and records every request.

Only `client.beta.messages.create` and `.stream` are faked, because that's all the wrapper
calls. Responses are real SDK `BetaMessage` objects, so the wrapper is exercised against the true
types. `.stream` replays the same scripted message, chunking its text like the SDK's text_stream.
"""

import json
from collections.abc import AsyncIterator
from typing import Any, Self, cast

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

    def stream(self, **kwargs: Any) -> "_FakeStream":
        return _FakeStream(self.create(**kwargs))


CHUNK = 7  # characters per text delta: small enough to split fields mid-string


class _FakeStream:
    """Async context manager shaped like the SDK's BetaAsyncMessageStream."""

    def __init__(self, pending: Any) -> None:
        self._pending = pending  # the create() coroutine: raises scripted errors on enter
        self._message: BetaMessage | None = None

    async def __aenter__(self) -> Self:
        self._message = await self._pending
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def chunks() -> AsyncIterator[str]:
            assert self._message is not None
            text = "".join(b.text for b in self._message.content if b.type == "text")
            for i in range(0, len(text), CHUNK):
                yield text[i : i + CHUNK]

        return chunks()

    async def get_final_message(self) -> BetaMessage:
        assert self._message is not None
        return self._message


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
