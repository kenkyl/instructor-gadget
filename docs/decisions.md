# Decisions

Short ADR-style records of every non-obvious choice. New entries are appended with the `adr` skill.
Format: **Context**, then **Decision**, **Alternatives**, **Consequences**, and a **One-liner** (how to explain the decision in one sentence).

---

## ADR-0001: Python (FastAPI) backend + Next.js frontend
**Context:** The agent needs structured LLM calls, a Redis semantic cache, local embeddings, a spaced-repetition scheduler and an eval harness. The UI needs to be plain and fast to build.
**Decision:**
- Backend: Python 3.12 + FastAPI, with the agent as an in-process package.
- Frontend: Next.js (App Router) + TypeScript + Tailwind + shadcn/ui.
- Next rewrites `/api/*` to FastAPI, so cookies stay same-origin and no CORS setup is needed.
- TypeScript types are generated from FastAPI's OpenAPI schema, so the Pydantic models are the single contract.
**Alternatives:** All-TypeScript (Next.js API routes + a TS agent SDK) gives one language, shared types and a simple Vercel deploy.
**Consequences:**
- RedisVL (`SemanticCache`, the HF vectorizer, tag filters), sentence-transformers, py-fsrs and pytest are all Python-native.
- The cost is two languages, mitigated by the generated types.
**One-liner:** The hardest parts (the semantic cache, embeddings, evals) live in the Python ecosystem, so the backend goes there and the UI stays thin.

## ADR-0002: Hand-rolled agent on the Anthropic SDK (no LangGraph, no Claude Agent SDK)
**Context:** The course lifecycle is a fixed sequence of stages: intake → probe → assess → map → per concept (teach → quiz → grade → adapt).
**Decision:**
- The lifecycle is an explicit state machine in code, making structured LLM calls through one client wrapper.
- That wrapper handles model choice, schema-validated output, one retry and logging.
**Alternatives:**
- LangGraph adds a graph runtime and a learning curve, and buys nothing for a fixed sequence.
- The Claude Agent SDK is built for autonomous tool loops, and this is not one.
**Consequences:**
- Every step is inspectable and testable.
- Revisit for the P2 chat agent if its orchestration becomes complex.
**One-liner:** The workflow is deterministic, so the code owns the flow and the model only fills in language.

## ADR-0003: Product skills architecture
**Context:** Each teaching ability (diagnose, map, teach, quiz, grade, remediate, ground) needs its own prompt, contract, cache policy and evals.
**Decision:**
- Each skill is a folder: `SKILL.md` (frontmatter: version, and per-call cache policy, streaming and max tokens), `calls/<call>.md`, `schema.py`, `references/`, `evals/`.
- A registry discovers the folders on disk and composes each prompt: shared conduct rules + skill + call (+ grounding for org courses).
- `prompt_version = name@semver+sha8(prompt files)`, and it feeds both the cache key and `llm_calls`.
- "Skills do language; code does decisions": scoring, gating and scheduling live in `pedagogy.py`.
**Alternatives:** Inline prompt strings, or one large prompt module.
**Consequences:**
- Editing a prompt automatically invalidates its cache entries.
- Cache policy is declared in the skill, not hidden in code.
- Course-type playbooks and org-authored skills can plug in later.
**One-liner:** Each teaching ability is a versioned, testable, swappable unit, and its version is part of the cache key.

## ADR-0004: Enrollments; org courses are admin templates
**Context:** Adaptation is per learner. If one learner fails a quiz, the remediation concept must not appear in another learner's copy of the same org course.
**Decision:**
- Plans, progress, lessons, misconceptions, overrides and quiz attempts all belong to an **enrollment** (course × user).
- The org admin builds a template: intake with the cohort's target level + docs → grounded map → accept. There is no admin diagnostic probe.
- Each assigned learner's enrollment starts from a copy of the template plan.
- A per-learner probe for org courses is P1+.
**Alternatives:**
- A single plan per course would leak adaptations across learners.
- Having the admin take the probe would diagnose the wrong person.
**Consequences:** One extra table. Shared lesson content still deduplicates through the cache.
**One-liner:** The course is shared; the learning path is personal.

## ADR-0005: Recency-weighted mastery (spec §4.9 change)
**Context:** Under the original update (0.5 × previous + 0.5 × evidence), a 3 on a retake after a 2 gives 0.65, which is "learning", while §4.8 says a 3 means solid. The learner would stay locked after doing well.
**Decision:**
- Later attempts use mastery = 0.3 × previous + 0.7 × evidence; the first attempt equals the evidence.
- Adaptation branches on the score; bands come from mastery.
**Alternatives:**
- A score-based floor, where a 3 guarantees solid. This makes the formula decorative on the way up.
- Keeping 0.5/0.5. This risks remediation loops.
**Consequences:**
- 2 then 3 → 0.71 (solid). 1 then 3 → 0.62 (needs one more attempt).
- The constants are still initial guesses until we have outcome data (P2).
**One-liner:** The newest evidence counts most, but one good answer doesn't erase a wrong one.

## ADR-0006: A score of 4 offers test-out, not skip
**Context:** The brief says a 4 offers to "compress or skip" the next concept. The core rule says mastery comes only from graded retrieval.
**Decision:**
- A 4 offers to **test out** of the next concept: skip its lesson and go straight to its quiz.
- A 3 or higher on that quiz unlocks its dependents.
- Accepting the offer creates plan v(n+1) with a diff and a why.
**Alternatives:**
- A true skip breaks "demonstrated, not declared" and the prerequisite gate.
- A compressed lesson costs an extra LLM call that can't be cached.
**Consequences:** Strong learners move faster without inflating mastery.
**One-liner:** You can skip the reading, not the proof.

## ADR-0007: Cache scoping for personalized content
**Context:** Lessons are personalized (analogy domain, formats, org docs), but most of each lesson is shareable across learners. A false or cross-bucket hit is worse than a miss.
**Decision:**
- **Lesson input:** first-pass `teach-concept` input excludes the per-learner assessment, which already shaped the map.
- **Semantic filter bucket:** org_id (or public), target level, formats, analogy domain, prompt version and the doc-set hash.
- **Quizzes:** `design-assessment` uses the exact tier keyed on the lesson's content hash. A semantic hit on a lesson therefore becomes an exact hit on that same lesson's quiz.
- **Never cached:** `diagnose`, `grade`, `remediate`, and any request that includes the learner's logged misconceptions.
**Alternatives:**
- Caching the full personalized input gives near-zero hits.
- Caching without buckets risks serving one org's content to another org.
**Consequences:** Hit rates depend on how often learners share bucket values. The §6 cache eval measures the false-hit rate before a threshold is chosen.
**One-liner:** Share what's shareable, never what's personal, and measure the false hits.

## ADR-0008: Async stack, Alembic migrations, generated client types
**Context:** The app streams SSE while awaiting the LLM, Redis and Postgres, and the schema will change during the build.
**Decision:**
- Async end to end: `AsyncAnthropic`, `redis.asyncio`, RedisVL's async methods, SQLAlchemy 2.x async with psycopg 3.
- Alembic for schema changes.
- `openapi-typescript` for the frontend types.
- ruff and pytest for Python; strict TypeScript and ESLint for the web app.
- CI on GitHub Actions, running only the deterministic tests.
**Alternatives:**
- Sync SQLAlchemy is simpler, but blocks a worker during streams.
- `create_all` gives no upgrade path.
**Consequences:** A little more setup at CP0, in exchange for standard, explainable patterns.
**One-liner:** These are the standard patterns a platform team expects to see.

## ADR-0009: License: PolyForm Noncommercial 1.0.0
**Context:** The repo is public, and the project may be monetized later.
**Decision:**
- License the code under PolyForm Noncommercial 1.0.0: anyone may view, run and modify it for noncommercial purposes.
- External contributions are not accepted, so no contributor license agreement is needed.
**Alternatives:**
- No license ("all rights reserved") leaves it unclear whether people can run the code.
- AGPL doesn't prevent resale.
- The Business Source License has more parameters to set.
**Consequences:**
- The project is "source-available", not open source under the OSI definition.
- The copyright holder can still dual-license it.
**One-liner:** Anyone can read it and learn from it; nobody else can sell it.

## ADR-0010: Schema conventions: string enums, JSONB for evolving shapes, UUIDs, test DB
**Context:** The schema must absorb the roadmap (new knobs, triggers, course types) without risky migrations, and stay easy to review.
**Decision:**
- **Enums:** Python `StrEnum`s stored as VARCHAR(32), not native Postgres enum types. Values are validated in Python.
- **JSONB for evolving shapes:** course config, mission, plans, quiz questions and the FSRS card are JSONB, validated by Pydantic models at the service boundary.
- **UUID primary keys** and timezone-aware timestamps.
- **A naming convention for constraints**, so Alembic autogenerate output is deterministic.
- **Tests** run against a separate `instructor_test` database that is recreated and migrated each run.
**Alternatives:**
- Native PG enums. Adding a value needs `ALTER TYPE`, which is awkward in transactions and migrations.
- Fully normalized tables for plans and questions. Many more migrations for shapes that are still changing.
- Running tests against the dev DB. Flaky, and destroys local data.
**Consequences:**
- The database won't reject an invalid enum value written by raw SQL. Only the app writes, so this is acceptable.
- JSONB fields aren't queryable with foreign keys. Fine for documents we read whole.
**One-liner:** Rigid where integrity matters (FKs, uniques, the scope check), flexible where the product is still evolving (JSONB + Pydantic).

## ADR-0011: Redis data types: hash for sessions, native JSON for documents
**Context:** The first plan stored every app-managed Redis value as a serialized JSON string. Redis 8 ships native JSON and the Query Engine.
**Decision:**
- `sess:{token}` is a **hash**: flat, tiny, read whole on every request.
- `dash:{user_id}` and `llm:exact:{sha256}` are **native JSON**.
- `llm:exact:*` gets a Query Engine index (`idx:llm_exact`) on its metadata: skill, prompt version, cost, latency, hits.
- A cache hit increments `$.hits` atomically with `JSON.NUMINCRBY`.
- The dashboard cache is still deleted on writes, never patched in place.
**Alternatives:**
- Strings everywhere: simplest, but opaque to Redis. No path reads, no indexing.
- JSON for sessions too: uniform, but no benefit for a flat, two-field value.
**Consequences:**
- We can purge cache entries by prompt version, and report cache inventory (entries, reuse, cost held) inside Redis.
- Slightly more client code: `r.json()` and an index definition at startup.
- Serialization still happens on the wire; the gain is that the server understands the structure.
**One-liner:** Pick the Redis type by access pattern: hashes for flat records, JSON for documents you need to query or update by path.

## ADR-0012: Two safety nets for missing `await`
**Context:** In PC0.5 a missing `await` on an async Redis call silently skipped the `DEL`. Ruff doesn't detect this.
**Decision:**
- Pyright runs in standard mode in `make lint` and CI. It flags unused coroutines from any `async def`.
- pytest turns `RuntimeWarning` (including "coroutine … was never awaited") and unraisable-exception warnings into test failures. This covers redis-py, whose commands are typed `Awaitable[int]`, which pyright's coroutine rule doesn't check.
**Alternatives:**
- `reportUnusedCallResult`: far too noisy.
- Code review alone: it's what missed this bug.
**Consequences:** One more dev dependency (pyright). Static coverage for our own and typed libraries, runtime coverage for redis-py on any tested path.
**One-liner:** Catch the classic async bug statically where the types allow, and at test time where they don't.


## ADR-0013: Structured outputs (not forced tool use), validated by our own wrapper
**Context:** The plan said "structured output via forced tool use". Current models (Sonnet 5.5, our default, and Opus 5.5) reject forced `tool_choice` (`any`/`tool`) with a 400. The SDK's `messages.parse()` raises on invalid output, which loses the raw text and token usage that the retry and `llm_calls` need.
**Decision:**
- `agent/llm.py` calls `beta.messages.create` with `output_config.format` = a JSON schema built from the call's Pydantic output model (`anthropic.transform_schema`), then validates the text itself with `model_validate_json`, including model validators such as "an adjusted level needs an explanation".
- On a validation error it retries once: the model's reply goes back unchanged (thinking blocks included), followed by the errors rendered through `_shared/retry.md`. Refusals and `max_tokens` truncation are not retried.
- Every API request is one `llm_calls` row (a retried call is two), written in its own transaction through a `CallSink` protocol, so `agent/` never imports `app/` and the log survives a failed request.
- Server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) on models that support it; the log records the model that actually served the request.
- Per-call `effort` and `max_tokens` live in the skill's `SKILL.md` frontmatter. Thinking tokens count toward `max_tokens`, so the default is 8000.
**Alternatives:**
- Forced tool use: a 400 on current models.
- `messages.parse()`: less code, but there's nothing to log or feed back when validation fails.
- `tool_choice: auto` + `strict: true`: the model may still answer in text, so it adds a failure mode for no gain.
**Consequences:**
- JSON-schema keywords the API can't enforce (`maxItems: 4`, `minimum`) are moved into descriptions by `transform_schema`. Pydantic enforces them, and the retry absorbs the rare miss.
- The cost of a failed attempt is visible in the trace instead of hidden.
- The fallback beta is Claude API only; on Bedrock or Vertex it would need the SDK's client-side middleware.
**One-liner:** The API guarantees the JSON shape, Pydantic guarantees the meaning, and every attempt (good or bad) lands in the trace.

## ADR-0014: The diagnostic assessment is final; quizzes correct a wrong start
**Context:** After seeing their assessed level, a learner could resubmit better-worded answers until the level came out higher. That would turn the diagnosis back into a self-report, the thing §4.2 says is unreliable.
**Decision:**
- One assessment per course and learner. Resubmitting returns the stored result unchanged.
- A start that turns out too low is corrected by the learning loop, not by a retake: every concept ends in a quiz, and a strong result offers a test-out of the next concept (ADR-0006).
- `assess.md` tells the model not to promise a reassessment, and to describe the quiz and test-out path instead. A live run showed it promising "I can reassess and move you up".
**Alternatives:**
- Allow one retake: gameable, and it doubles the uncached `assess` calls.
- Silently drop the level and let quizzes sort it out: breaks "never re-level silently" (§4.3).
**Consequences:** The diagnosis keeps its meaning, and a learner who under-performs on the probe pays a few extra test-outs, not a wrong course.
**One-liner:** You can't re-roll the diagnosis, but the quizzes will move you up if it started you too low.

## ADR-0015: The call's input is Pydantic validation context
**Context:** Some output rules depend on the request. `assess` echoes `claimed_level`; if it echoes the wrong value, the "an adjusted level needs an explanation" rule compares against the wrong claim. Evidence must also cite real question ids. Self-contained model validators can't see the input.
**Decision:** The LLM wrapper validates with `model_validate_json(text, context={"input": payload})`. Output validators read `info.context["input"]` and raise on a mismatch, which feeds the normal one-retry path (ADR-0013). Without context (reading JSONB back), those checks are skipped.
**Alternatives:**
- Overwrite `claimed_level` from the input after validation: it hides the model's mistake, and its other fields (the message) may be built on the wrong claim.
- Check in the service after the call: no retry, so a fixable error becomes a 502.
**Consequences:** Request-aware rules stay next to the schema they protect, are unit-testable, and get a retry for free. `map-concepts` can use the same hook (e.g. concept ids referenced by gaps).
**One-liner:** The output is checked against the question it was answering, and a mismatch earns one retry instead of a silent fix.
