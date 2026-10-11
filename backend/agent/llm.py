"""LLM client wrapper: the only way the app calls the model (CLAUDE.md hard rule).

One `run()` does, for a registered skill call:
1. compose the system prompt and prompt_version from the registry,
2. request structured output (`output_config.format`, a JSON schema built from the call's
   Pydantic output model), with server-side refusal fallback where the model supports it,
3. validate the reply with Pydantic, including the model's own validators (e.g. "an adjusted
   level needs an explanation"), with the input as validation context so validators can check
   the reply against the request, and on failure retry once, feeding the errors back,
4. record every API request (ok or not) through a CallSink, which the app writes to llm_calls.

Cacheable calls (`cache: exact | semantic` in SKILL.md) check the exact tier first (agent/cache.py)
and store the validated output after a miss. A hit is logged too, with zero tokens and the cost
and time it saved. `stream()` yields the raw JSON text as it arrives (for SSE); `run()` drains
the same generator and returns the validated output.

Why not forced tool use: current models (Sonnet 5.5, Opus 5.5) reject `tool_choice` any/tool
with a 400. Why not `messages.parse()`: it raises on invalid output, which loses the raw text
and token usage we need for the retry and the log (ADR-0013).

The agent package doesn't import `app`: logging goes through the CallSink protocol, so this
module can be tested with a fake client and an in-memory sink, and could move to a service.
"""

import json
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaOutputConfigParam
from pydantic import BaseModel, ValidationError

from agent.cache import ExactCache, ExactEntry, exact_key
from agent.registry import Call, Registry, SkillError

# USD per million tokens (input, output). Source: Anthropic pricing, checked 2026-10-11.
# The fallback model is listed too, since a rescued request is billed at its rates.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Server-side refusal fallback (`fallbacks: "default"`) is only accepted for these models.
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"

EXCERPT_CHARS = 2000


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated cost of one request. Unknown models cost 0 rather than failing a paid call."""
    in_price, out_price = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    return round((input_tokens * in_price + output_tokens * out_price) / 1_000_000, 6)


@dataclass(frozen=True)
class CallContext:
    """Who and what a call is for; becomes the llm_calls foreign keys."""

    user_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CallRecord:
    """One API request. A retried call produces two records."""

    skill: str
    call: str
    model: str  # the model that actually served the request (differs after a fallback)
    prompt_version: str
    cache_result: Literal["miss", "exact_hit", "bypass"]  # semantic_hit arrives in CP3
    attempt: int
    status: Literal["ok", "error"]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    est_cost_usd: float
    error: str | None
    prompt_excerpt: str | None
    response_excerpt: str | None
    context: CallContext
    cache_key: str | None = None
    saved_cost_usd: float = 0.0  # on a hit: what generating the entry cost
    saved_latency_ms: int = 0


class CallSink(Protocol):
    async def record(self, rec: CallRecord) -> None: ...


class LLMError(Exception):
    """The call failed. Safe to show the message to a developer, not to a learner."""


class LLMRefusal(LLMError):
    """The model (and its fallback) declined the request. Not retried."""


class LLMInvalidOutput(LLMError):
    """The output still failed validation after the one retry."""


def _format_errors(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        lines.append(f"- {loc}: {e['msg']}")
    return "\n".join(lines)


def _text(msg: BetaMessage) -> str:
    # With output_config.format the JSON arrives as a text block; thinking blocks come first.
    return "".join(b.text for b in msg.content if b.type == "text")


@dataclass(frozen=True)
class TextDelta:
    """A chunk of the output's JSON text, as the model writes it."""

    text: str


@dataclass(frozen=True)
class Restart:
    """The output failed validation; the retry starts over, so discard the text so far."""

    errors: str


@dataclass(frozen=True)
class Done[T: BaseModel]:
    output: T
    cache_result: Literal["miss", "exact_hit", "bypass"]
    cache_key: str | None


type StreamEvent[T: BaseModel] = TextDelta | Restart | Done[T]


@dataclass(frozen=True)
class _Final:
    message: BetaMessage


class LLMClient:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        registry: Registry,
        sink: CallSink,
        *,
        model: str,
        cache: ExactCache | None = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.sink = sink
        self.model = model
        self.cache = cache

    async def run[T: BaseModel](
        self,
        skill: str,
        call: str,
        payload: BaseModel,
        output_type: type[T],
        *,
        ctx: CallContext,
    ) -> T:
        """One validated output (from the cache or the model)."""
        async for event in self._generate(skill, call, payload, output_type, ctx, stream=False):
            if isinstance(event, Done):
                return event.output
        raise AssertionError("unreachable")

    def stream[T: BaseModel](
        self,
        skill: str,
        call: str,
        payload: BaseModel,
        output_type: type[T],
        *,
        ctx: CallContext,
    ) -> AsyncIterator[StreamEvent[T]]:
        """TextDelta chunks as the model writes, Restart before a retry, then Done.

        A cache hit yields Done straight away. Errors raise, as in run().
        """
        return self._generate(skill, call, payload, output_type, ctx, stream=True)

    async def _generate[T: BaseModel](
        self,
        skill: str,
        call: str,
        payload: BaseModel,
        output_type: type[T],
        ctx: CallContext,
        *,
        stream: bool,
    ) -> AsyncIterator[StreamEvent[T]]:
        c = self.registry.call(skill, call)
        # output_type is only there for static typing; it must match the registered contract.
        if c.output_model is not output_type:
            raise SkillError(f"{skill}.{call} returns {c.output_model.__name__}, not {output_type}")
        if not isinstance(payload, c.input_model):
            raise SkillError(f"{skill}.{call} takes {c.input_model.__name__}")

        version = self.registry.prompt_version(skill, call)
        user_msg = payload.model_dump_json(indent=2)

        key: str | None = None
        if c.spec.cache != "never" and self.cache is not None:
            key = exact_key(skill, call, self.model, version, payload)
            started = time.perf_counter()
            entry = await self.cache.get(key)
            if entry is not None:
                # The stored output was validated when it was written; re-validate anyway, as
                # with any data read back from Redis. A stale shape is a miss, not an error.
                try:
                    output = output_type.model_validate(entry.output)
                except ValidationError:
                    output = None
                if output is not None:
                    await self._log_hit(c, version, ctx, key, entry, user_msg, started)
                    yield Done(output, "exact_hit", key)
                    return

        system = self.registry.system_prompt(skill, call)
        messages: list[BetaMessageParam] = [{"role": "user", "content": user_msg}]
        spent_usd, spent_ms = 0.0, 0  # across attempts: what this output cost to generate

        for number in (1, 2):
            att = _Attempt(c, version, ctx, number, prompt=str(messages[-1]["content"]), key=key)
            message: BetaMessage | None = None
            async for event in self._request(system, messages, att, stream=stream):
                if isinstance(event, _Final):
                    message = event.message
                else:
                    yield event
            assert message is not None
            spent_usd += att.cost_usd()
            spent_ms += att.latency_ms
            try:
                # The input is validation context, so output validators can check the reply
                # against the request (e.g. assess: claimed_level must match the claim).
                result = output_type.model_validate_json(_text(message), context={"input": payload})
            except ValidationError as err:
                errors = _format_errors(err)
                await self._log(att, error=f"invalid output:\n{errors}")
                if number == 2:
                    raise LLMInvalidOutput(
                        f"{skill}.{call} output invalid after retry:\n{errors}"
                    ) from err
                # Append-only history: the model's own reply (thinking blocks included, which
                # current models require unchanged), then the errors as the next user turn.
                messages.append({"role": "assistant", "content": message.content})
                retry = self.registry.retry_template.replace("{errors}", errors)
                messages.append({"role": "user", "content": retry})
                yield Restart(errors)
                continue
            await self._log(att)
            if key is not None and self.cache is not None:
                await self.cache.put(
                    key,
                    ExactEntry(
                        skill=skill,
                        call=call,
                        prompt_version=version,
                        model=message.model,
                        cost_usd=round(spent_usd, 6),
                        latency_ms=spent_ms,
                        created_at=int(time.time()),
                        output=result.model_dump(mode="json"),
                    ),
                )
            yield Done(result, "bypass" if c.spec.cache == "never" else "miss", key)
            return

    async def _request(
        self,
        system: str,
        messages: Sequence[BetaMessageParam],
        att: "_Attempt",
        *,
        stream: bool,
    ) -> AsyncIterator[TextDelta | _Final]:
        """One API request: TextDelta chunks when streaming, then _Final with the message."""
        c = att.call
        output_config: BetaOutputConfigParam = {
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(c.output_model)}
        }
        if c.spec.effort:
            output_config["effort"] = c.spec.effort
        fallback = self.model in FALLBACK_MODELS

        betas = [FALLBACK_BETA] if fallback else anthropic.omit
        fallbacks = "default" if fallback else anthropic.omit
        started = time.perf_counter()
        try:
            if stream:
                # With output_config.format the text deltas are the JSON output. After a
                # mid-stream refusal fallback the substitute model continues the same text.
                async with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=c.spec.max_tokens,
                    system=system,
                    messages=messages,
                    output_config=output_config,
                    betas=betas,
                    fallbacks=fallbacks,
                ) as s:
                    async for text in s.text_stream:
                        yield TextDelta(text)
                    message = await s.get_final_message()
            else:
                message = await self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=c.spec.max_tokens,
                    system=system,
                    messages=messages,
                    output_config=output_config,
                    betas=betas,
                    fallbacks=fallbacks,
                )
        except anthropic.APIError as err:
            # The SDK has already retried 429/5xx/connection errors; this one is final.
            att.latency_ms = _elapsed_ms(started)
            await self._log(att, error=f"{type(err).__name__}: {err}")
            raise LLMError(f"{c.skill}.{c.name}: API error ({type(err).__name__})") from err
        att.message, att.latency_ms = message, _elapsed_ms(started)

        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            await self._log(att, error=f"refusal ({category})")
            raise LLMRefusal(f"{c.skill}.{c.name}: the model declined ({category})")
        if message.stop_reason == "max_tokens":
            # Truncated JSON; a retry would truncate again. The fix is a bigger budget.
            await self._log(att, error="hit max_tokens")
            raise LLMError(
                f"{c.skill}.{c.name}: hit max_tokens={c.spec.max_tokens}; raise it in SKILL.md"
            )
        yield _Final(message)

    async def _log(self, att: "_Attempt", *, error: str | None = None) -> None:
        m = att.message
        model = m.model if m else self.model
        in_tok = m.usage.input_tokens if m else 0
        out_tok = m.usage.output_tokens if m else 0
        await self.sink.record(
            CallRecord(
                skill=att.call.skill,
                call=att.call.name,
                model=model,
                prompt_version=att.version,
                cache_result="bypass" if att.call.spec.cache == "never" else "miss",
                cache_key=att.key,
                attempt=att.number,
                status="error" if error else "ok",
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=att.latency_ms,
                est_cost_usd=estimate_cost_usd(model, in_tok, out_tok),
                error=error,
                prompt_excerpt=att.prompt[:EXCERPT_CHARS],
                response_excerpt=_text(m)[:EXCERPT_CHARS] if m else None,
                context=att.ctx,
            )
        )

    async def _log_hit(
        self,
        c: Call,
        version: str,
        ctx: CallContext,
        key: str,
        entry: ExactEntry,
        prompt: str,
        started: float,
    ) -> None:
        """A cache hit is a call too: zero tokens, plus what it saved (for the trace page)."""
        await self.sink.record(
            CallRecord(
                skill=c.skill,
                call=c.name,
                model=entry.model,
                prompt_version=version,
                cache_result="exact_hit",
                attempt=1,
                status="ok",
                input_tokens=0,
                output_tokens=0,
                latency_ms=_elapsed_ms(started),
                est_cost_usd=0.0,
                error=None,
                prompt_excerpt=prompt[:EXCERPT_CHARS],
                response_excerpt=json.dumps(entry.output)[:EXCERPT_CHARS],
                context=ctx,
                cache_key=key,
                saved_cost_usd=entry.cost_usd,
                saved_latency_ms=entry.latency_ms,
            )
        )


@dataclass
class _Attempt:
    """One API request within a run(): everything its llm_calls record needs."""

    call: Call
    version: str
    ctx: CallContext
    number: int
    prompt: str  # the user turn this request answers, for the log excerpt
    key: str | None = None  # the exact-cache key, for cacheable calls
    message: BetaMessage | None = None  # None if the API call itself failed
    latency_ms: int = 0

    def cost_usd(self) -> float:
        m = self.message
        if m is None:
            return 0.0
        return estimate_cost_usd(m.model, m.usage.input_tokens, m.usage.output_tokens)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
