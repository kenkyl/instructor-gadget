# Architecture

How Instructor is put together in Phase 1: the components, the learning loop as a sequence, where state lives, and the four ways it uses Redis. Decisions are linked to their ADRs in [`decisions.md`](decisions.md); every table, JSONB shape and key is in [`data-model.md`](data-model.md).

A generated overview with the three main request flows, rendered from a reviewed model, is in [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md). This page is the hand-written explanation; the two are kept consistent.

## Components

```mermaid
flowchart LR
  B(["Browser"]) -->|"/api/* (same origin)"| W["Next.js 16<br/>App Router, :3000"]
  W -->|"rewrite /api/*"| A["FastAPI, :8000<br/>routers = web surface adapter"]
  A --> S["Services<br/>surface-neutral rules: courses, learning, quiz, org docs, trace"]
  S --> P["agent.pedagogy<br/>scoring, mastery, bands, gate,<br/>adaptation, FSRS (pure code)"]
  S --> L["agent.llm<br/>the only model client"]
  L --> R["agent.registry<br/>skills: SKILL.md + calls/*.md + schema.py"]
  L --> C["agent.cache + agent.semantic<br/>exact tier, RedisVL semantic tier"]
  L --> SRC["agent.sources<br/>org docs: anchors, grounding, citation checks"]
  L -->|"structured output, 1 retry"| ANT["Anthropic API<br/>claude-sonnet-5-5"]
  S --> PG[("Postgres 16<br/>source of truth")]
  L -->|"every attempt"| PG
  A --> RD[("Redis 8<br/>sessions, dashboard,<br/>LLM caches, intake guard")]
  C --> RD
  S --> RD
```

- **Skills do language; code does decisions.** A skill writes text (a probe, a map, a lesson, a quiz, a grade's feedback, the "why" of a re-plan). Every decision (score, mastery, band, unlock, adaptation rule, review date) is a pure function in `agent/pedagogy.py` with unit tests.
- **One wrapper for every model call** (`agent/llm.py`): structured output validated by the call's Pydantic model, one retry that feeds back the validation error, every attempt logged to `llm_calls` (tokens, latency, cost, cache result) (ADR-0013).
- **Skills are folders** under `backend/agent/skills/`: `diagnose`, `map-concepts`, `teach-concept`, `design-assessment`, `grade`, `remediate`, the `ground-in-sources` modifier, and the eval-only `judge-grounding`. Frontmatter declares each call's cache policy, token budget and effort; the prompt version is the skill version plus a hash of its prompt files.
- **Surfaces are thin.** The FastAPI routers only adapt HTTP (including SSE); ownership, the unlock gate and the rules live in services, so a later MCP surface reuses them.
- **LLM HTML is sandboxed.** The seeded prototype renders in an iframe with `srcdoc` and `sandbox="allow-scripts"`, never same-origin.

## The learning loop (J2)

```mermaid
sequenceDiagram
  autonumber
  actor U as Learner
  participant API as FastAPI + services
  participant PED as pedagogy (code)
  participant LLM as agent.llm
  participant RD as Redis
  participant AN as Anthropic
  participant PG as Postgres

  U->>API: open concept
  API->>PG: plan, progress
  API->>PED: unlocked? (prereqs ≥ solid)
  alt stored lesson
    API-->>U: done (instant)
  else generate
    API->>LLM: teach-concept.teach
    LLM->>RD: exact key (JSON.GET)
    alt exact or semantic hit
      RD-->>LLM: lesson (ms)
    else miss
      LLM->>AN: stream (structured output)
      AN-->>LLM: partial JSON → field deltas
      LLM->>RD: store (exact JSON + RedisVL entry)
    end
    LLM->>PG: llm_calls row
    API-->>U: SSE field_delta… done
  end
  U->>API: quiz answers
  API->>PED: MCQ score
  API->>LLM: grade (never cached)
  API->>PED: combine (lower of two), mastery, band, FSRS review date, adaptation rule
  opt score 1 or 2 with a named belief
    API->>LLM: remediate.explain_change (never cached)
    API->>PED: insert remediation concept, re-run the gate
    API->>PG: plan version N+1 (trigger, rule, why, diff)
  end
  API->>PG: progress, misconception
  API->>RD: DEL dash:{user}
  API-->>U: score, feedback, band, next review, what happens next
```

## Where state lives

| Store | Holds | Rebuildable? |
|---|---|---|
| **Postgres** | Users, orgs, docs, courses, enrollments, plan versions (each with trigger, reason, rule, diff), concept progress (mastery, band, FSRS card, due), lessons, quiz attempts, misconceptions, `llm_calls` | Source of truth |
| **Redis** | `sess:*` sessions; `dash:*` dashboard cache-aside (JSON, TTL, deleted on every progress write); `llm:exact:*` exact LLM cache (JSON + `idx:llm_exact`); `idx:llm_semantic` RedisVL semantic cache; `idx:intake_guard` RedisVL semantic router | Yes: losing it costs speed and money, never data |
| **Browser** | One `sid` cookie (HttpOnly, SameSite=Lax) | — |

Search indexes need Redis DB 0, and `FLUSHDB` on Redis 8 drops every index, so nothing (tests, `make reset`) ever flushes; they delete keys by pattern (ADR-0019).

## Four uses of Redis

1. **Sessions** and the **dashboard** cache-aside: native JSON with a TTL, deleted (never patched) when progress changes (ADR-0011).
2. **Exact LLM cache:** the key is a hash of the skill, call, model, prompt version and inputs (plus the doc-set hash for org calls), never a user id. `diagnose`, `grade`, `remediate` and anything carrying a learner's misconceptions are never cached (ADR-0007).
3. **Semantic LLM cache** (RedisVL `SemanticCache`, local MiniLM embeddings): a reworded request for the same lesson is served if it falls within cosine distance 0.12 **and** matches a bucket of exact tags (model, prompt version, org, level, formats, analogy, doc set). The threshold came from a labelled eval: zero false hits, about a third of paraphrases served (ADR-0023, ADR-0026).
4. **Intake guard** (RedisVL `SemanticRouter`): block routes for crude, off-topic, dangerous and prompt-injection course requests, checked in ~10 ms before anything is stored or sent to a model (ADR-0024).

## Org courses (J3)

- Docs are immutable and split into sections by heading, each with a code-computed anchor; a course pins its doc set by hash (ADR-0028).
- Grounded calls put the docs first in the system prompt and the `ground-in-sources` rules last. Lessons cite with `[n]` markers and `{doc, section, quote}`; code checks every section exists and every quote is verbatim in it, with the one retry on failure. The doc-set hash keys both cache tiers, so two orgs never share a lesson (ADR-0029).
- An admin builds a template (a docs-grounded map, no probe), accepts it, and assigns it; each learner gets their own enrollment with a copy of the plan. The admin's org impact view shows counts and dollars, never a learner's words (ADR-0030).

## Evals

`make test` is deterministic (no API). `make evals` calls the live model through the same wrapper with no cache tier: diagnosis personas, map constraints, pedagogy, grader calibration against human labels, an LLM grounding judge (itself unvalidated), and the semantic cache's false-hit rate (ADR-0031).
