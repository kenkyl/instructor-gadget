"""LLM client wrapper: the only way the app calls the model (CLAUDE.md hard rule).

One `run()` does, for a registered skill call:
1. compose the system prompt and prompt_version from the registry,
2. request structured output (`output_config.format`, a JSON schema built from the call's
   Pydantic output model), with server-side refusal fallback where the model supports it,
3. validate the reply with Pydantic, including the model's own validators (e.g. "an adjusted
   level needs an explanation"), with the input as validation context so validators can check
   the reply against the request, and on failure retry once, feeding the errors back,
4. record every API request (ok or not) through a CallSink, which the app writes to llm_calls.

Why not forced tool use: current models (Sonnet 5.5, Opus 5.5) reject `tool_choice` any/tool
with a 400. Why not `messages.parse()`: it raises on invalid output, which loses the raw text
and token usage we need for the retry and the log (ADR-0013).

The agent package doesn't import `app`: logging goes through the CallSink protocol, so this
module can be tested with a fake client and an in-memory sink, and could move to a service.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaOutputConfigParam
from pydantic import BaseModel, ValidationError

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
    cache_result: Literal["miss", "bypass"]  # hits arrive with the cache tiers (CP2/CP3)
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


class LLMClient:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        registry: Registry,
        sink: CallSink,
        *,
        model: str,
    ) -> None:
        self.client = client
        self.registry = registry
        self.sink = sink
        self.model = model

    async def run[T: BaseModel](
        self,
        skill: str,
        call: str,
        payload: BaseModel,
        output_type: type[T],
        *,
        ctx: CallContext,
    ) -> T:
        c = self.registry.call(skill, call)
        # output_type is only there for static typing; it must match the registered contract.
        if c.output_model is not output_type:
            raise SkillError(f"{skill}.{call} returns {c.output_model.__name__}, not {output_type}")
        if not isinstance(payload, c.input_model):
            raise SkillError(f"{skill}.{call} takes {c.input_model.__name__}")

        version = self.registry.prompt_version(skill, call)
        system = self.registry.system_prompt(skill, call)
        user_msg = payload.model_dump_json(indent=2)
        messages: list[BetaMessageParam] = [{"role": "user", "content": user_msg}]

        for number in (1, 2):
            att = _Attempt(c, version, ctx, number, prompt=str(messages[-1]["content"]))
            message = await self._request(system, messages, att)
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
                continue
            await self._log(att)
            return result
        raise AssertionError("unreachable")

    async def _request(
        self, system: str, messages: Sequence[BetaMessageParam], att: "_Attempt"
    ) -> BetaMessage:
        c = att.call
        output_config: BetaOutputConfigParam = {
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(c.output_model)}
        }
        if c.spec.effort:
            output_config["effort"] = c.spec.effort
        fallback = self.model in FALLBACK_MODELS

        started = time.perf_counter()
        try:
            message = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=c.spec.max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=[FALLBACK_BETA] if fallback else anthropic.omit,
                fallbacks="default" if fallback else anthropic.omit,
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
        return message

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


@dataclass
class _Attempt:
    """One API request within a run(): everything its llm_calls record needs."""

    call: Call
    version: str
    ctx: CallContext
    number: int
    prompt: str  # the user turn this request answers, for the log excerpt
    message: BetaMessage | None = None  # None if the API call itself failed
    latency_ms: int = 0


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
