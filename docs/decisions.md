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

## ADR-0016: `courses.template_plan` holds every course's base map
**Context:** A generated concept map needs a home before the learner accepts it. `plan_versions` belong to an enrollment (ADR-0004), and a personal course has no enrollment until accept (PC1.4). `template_plan` was documented as "org courses only: the admin-accepted map".
**Decision:** `template_plan` is the course's **base `ConceptMap`** for both scopes: proposed while the course is `mapped`, and final once accepted (`active`). Accepting copies it into the learner's plan v1. For org courses, every assigned learner's enrollment copies it. `courses.status` says which state it's in.
**Alternatives:**
- A new `proposed_plan` column: a migration, and two columns for the same idea.
- A plan version 0 with no enrollment: breaks the "plans belong to an enrollment" rule.
- Creating the enrollment before accept: the dashboard would list courses the learner never committed to.
**Consequences:** No migration, and personal and org courses follow one path: generate → (edit) → accept → copy into the enrollment. Edits before accept (PC1.4) change `template_plan`; after accept, they're plan versions.
**One-liner:** The course owns the starting map; each learner's enrollment owns their copy of it.

## ADR-0017: Cutting a prerequisite rewires its dependents
**Context:** The spec lets a learner cut concepts before accepting, with a warning naming what depends on the cut concept (§4.4). It doesn't say what happens to those dependents. A dangling prereq would break the graph rules (ADR-0013 validators).
**Decision:** Each dependent inherits the removed concept's own prereqs (A ← B ← C, cut B ⇒ A ← C), deduplicated and in order (`plan.remove_concept`). The warning names the direct dependents and says the course won't teach the cut concept. Edits are allowed only before accept; afterwards, changes are plan versions.
**Alternatives:**
- Drop the edge only: C could then come before A, losing ordering the map relied on.
- Cascade-remove the dependents: one cut could wipe out much of the map.
**Consequences:** The edited map is always a valid DAG, and the old order minus the cut concept is still a valid order, so the instructor's sequence survives edits. The learner can skip a topic, but not the ordering that made the rest teachable.
**One-liner:** Cut what you like; what came after it still comes after what came before it.

## ADR-0018: FSRS runs on a day scale for quiz-graded concepts
**Context:** The defaults in `fsrs` 6.3.2 (MIT) are tuned for flashcards: 1 min / 10 min learning steps, a 10 min relearning step, and random fuzzing. Our "card" is a whole concept reviewed by a quiz. Under the defaults, a Good first quiz is due again in 10 minutes, which floods "N due for review" right after every lesson. Fuzzing also makes tests nondeterministic, and it only helps spread load across large decks.
**Decision:**
- `pedagogy.SCHEDULER = Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False)`.
- Every graded attempt is one FSRS review, retakes included. The first attempt creates the card. With default parameters, first intervals are Again/Hard 1 day, Good 2 days, Easy 8 days.
- Times are normalized to UTC (fsrs rejects other zones).
- Failing in the moment is handled by remediation (§4.8), not by short FSRS steps.
**Alternatives:**
- Library defaults: these flood the due list.
- Scheduling only once a concept is solid: this throws away the evidence from weak attempts, which FSRS handles natively as Again/Hard.
- Fuzzing on: tests become nondeterministic, with no benefit at ≤ 20 concepts per course.
**Consequences:** Reviews start at least a day out. Default FSRS parameters stay until the P2 optimizer, which needs review logs we don't store yet.
**One-liner:** Spaced review is measured in days; same-day failure is remediation's job.

## ADR-0019: Redis search indexes live on DB 0; tests that need one use a `test:` prefix there
**Context:** The Redis 8 Query Engine refuses indexes on any other logical DB (`Cannot create index on db != 0`). The tests isolate Redis on DB 15 (ADR-0010). `idx:llm_exact` needs an index now, and the CP3 semantic cache needs a vector index.
**Decision:**
- Data keys stay where they are. The exact cache's `JSON.GET`/`JSON.SET` work on any DB.
- `ensure_index` creates an index only on DB 0, and skips with a warning elsewhere. The cache still works there; only the inventory index is missing.
- A test that needs a real index uses DB 0 with a unique `test:` index name and key prefix, and drops it (with its documents) afterwards.
**Alternatives:**
- Moving all tests to DB 0 under a namespace: every key would need a prefix, and flushing a whole DB would no longer be safe.
- Faking the Query Engine: it would prove nothing about the real index.
**Consequences:** API tests run without `idx:llm_exact`. CP3's RedisVL tests follow the same DB-0, `test:`-prefix pattern.
**One-liner:** Keys can live anywhere; indexes only on DB 0, so index tests borrow DB 0 under a throwaway prefix.
**Addendum (PC3.3):** on Redis 8, `FLUSHDB` on *any* DB drops every search index, DB 0's included. The test setup flushed DB 15, so each `make test` silently removed a running dev server's indexes. Tests now delete DB 15's keys (`SCAN` + `UNLINK`) instead; never `FLUSHDB`/`FLUSHALL` while indexes matter.

## ADR-0020: SSE through the Next proxy: `Cache-Control: no-transform`
**Context:** The lesson streams as SSE from FastAPI through Next's `/api` rewrite. Measured live, a browser-like client (`Accept-Encoding: gzip`) received all 332 events in one burst at 13 s. Without gzip, the same request through Next streamed: the first event at 1.5 s, 286 distinct arrival times. The rewrite streams; Next's response compression buffers.
**Decision:** The SSE route sends `Cache-Control: no-transform` (alongside FastAPI's `no-cache`), set in a dependency so it's there before the headers go out. Next's compression skips responses marked `no-transform`. A regression test asserts the header.
**Alternatives:**
- `compress: false` in `next.config`: turns compression off for every page.
- Calling FastAPI directly for this endpoint (the build plan's fallback): cross-origin cookies and CORS for one route.
**Consequences:** Lesson events arrive as they're written (first text ~1.3 s, the full lesson ~12 s), and every other response is still compressed. Any future streaming endpoint must send the same header.
**One-liner:** The proxy wasn't the problem, gzip was; `no-transform` opts the stream out of it.

## ADR-0021: Two quiz calls: a shareable, exact-cached `design` and a never-cached `design_targeted`
**Context:** ADR-0007 says quizzes are exact-cached on the lesson's content, and also that any request carrying a learner's logged misconceptions is never cached. §4.6 wants distractors drawn from *this learner's* misconceptions, so after a miss, the next quiz is personal. A retake of the same lesson must also not return the same questions.
**Decision:**
- `design-assessment` has two calls. `design` (cache `exact`) takes the concept, the lesson's text and a `round` number, with no learner data. `design_targeted` (cache `never`) adds the open misconceptions for the concept and its prereqs, and a validator requires at least one question to target one of them.
- The service picks the call: any open misconception → `design_targeted`. The cache policy stays declared per call in `SKILL.md`, not decided in code.
- `round` (prior submitted attempts + 1) is part of the input, so a retake is a new quiz while round 1 of a shared lesson stays an exact hit across learners.
**Alternatives:**
- One call with a code-side "skip the cache if personal" flag: hides the policy from the skill's declaration, which is what reviewers and the trace read.
- Never caching quizzes: about 3.5¢ and 20 s per quiz for every learner, including the ones a shared lesson already served.
**Consequences:** A learner with no logged beliefs gets a shared quiz. After any miss, quizzes are personal and slower. The quiz is prefetched while the learner reads the lesson, to hide the ~20 s.
**One-liner:** The quiz is shared until you've shown a misconception; then it's yours and never cached.

## ADR-0022: Remediation is an inserted prerequisite; only structural changes version the plan
**Context:** §4.8 inserts a remediation concept after a score of 1–2 and says every plan change creates a new version. We have to decide where the remediation goes, how the learner gets back to the original, and which events count as "plan changes" (unlocking happens after almost every quiz).
**Decision:**
- The remediation concept (`{id}-remedy-{n}`) is inserted **before** the failed concept, takes its prereqs, and becomes a new prereq of it. The existing gate then does the rest: the remedy unlocks, the original re-locks, and when the remedy is solid the original reopens for a retake. `pedagogy.adapt` caps remediations at 2 per concept (`MAX_REMEDIATIONS`); after that a low score asks for a retake (no endless loops).
- A remediation for an overridden concept inherits the override: it would otherwise take the concept's unmet prereqs and sit locked behind the gate the learner already skipped.
- Plan-state fields set by code (`Concept.remedy`, `ConceptMap.test_out`) are hidden from the model's output schema (`SkipJsonSchema`), so `map-concepts` can't set them.
- New plan versions only for **structural** changes: an inserted remediation, an accepted test-out, an override. Unlocks and completions are progress state, reported in the result and the diff's `status_changes`, not versions of their own.
- A picked MCQ distractor logs its tagged misconception deterministically. The grader adds one from the short answer, and that one is listed first.
**Alternatives:**
- Remediation as a detour outside the graph: needs a second gating mechanism.
- A version per unlock: the history fills with noise, and the "why" loses its meaning.
**Consequences:** One gating rule covers prereqs, remediation and the retake loop. The plan history reads as decisions (diagnosis, remediation, test-out, override).
**One-liner:** A remediation is just a new prerequisite, so the gate we already trust does the re-locking.

## ADR-0023: The semantic tier lives in the LLM wrapper; the service supplies the text and the bucket
**Context:** ADR-0007 defines what a lesson may share (the bucket) and that only `semantic`-policy calls use the tier. RedisVL's `SemanticCache` gives the vector index, TAG filters and TTLs, but someone has to decide what gets embedded, which fields form the bucket, and where the lookup sits relative to the exact tier and the model call.
**Decision:**
- **Order:** exact → semantic → model, inside `LLMClient`. A semantic hit is a call like any other: logged to `llm_calls` with zero tokens, its similarity, and the cost and latency it saved. A miss stores the validated output in both tiers.
- **Who knows what:** the service passes a `SemanticKey` (text to embed + org, level, formats, analogy, doc-set hash). The wrapper adds skill/call, model and prompt version. A key passed to a non-`semantic` call is ignored, so a personal call can't opt in by mistake.
- **Embedded text:** topic + concept title + mastery statement. The topic is there because a title alone is ambiguous across courses ("pool exhaustion" for DB vs thread pools).
- **Bucket:** eight TAG fields matched exactly *before* the vector range search (not one hashed tag), so the trace, Redis Insight and a future purge-by-prompt-version can read them. Values are normalised (sorted formats joined with `+`, since a comma is RedisVL's tag separator; slugged analogy; `none`/`public` for absent values).
- **Runtime:** MiniLM (`all-MiniLM-L6-v2`, 384 dims) runs locally; embedding (~3 ms) runs in a worker thread because the HF vectorizer has no real async path. The tier needs DB 0 (ADR-0019) and is off elsewhere (API tests). A startup failure disables the tier, not the app.
- **Threshold:** cosine distance 0.15, provisional (now 0.12, set by the PC3.2 eval: ADR-0026). Measured on MiniLM: a paraphrase 0.135; a reworded same concept 0.232; near-misses 0.217–0.269. The bands overlap, so the strict side wins until PC3.2's sweep.
**Alternatives:**
- Semantic lookup in the lesson service: every future semantic call would re-implement logging, validation and storage.
- RedisVL's default `redis/langcache-embed-v1` model: tuned for chat-style Q&A, larger, and not what the brief specified.
- A single hashed bucket tag: smaller, but opaque in the trace and impossible to filter by one dimension.
**Consequences:** Measured live: a reworded lesson request was served in 0.1 s at similarity 0.989, saving $0.021, while "thread pool exhaustion" with the same words in another topic missed. The first startup downloads the model (`make models` does it ahead of time).
**One-liner:** Exact first, then meaning, but only among learners who would have been taught the same way.

## ADR-0024: Intake guard: a semantic router with block routes only
**Context:** Course creation accepts free text (topic, goal) that is later sent to the model. Kyle asked for a simple filter for requests that aren't about learning anything (crude, off-topic like "tell me the weather today?", dangerous like "run this python code snippet", prompt injection), with minimal code.
**Decision:**
- RedisVL's `SemanticRouter` (no new dependency) with four **block** routes of ~5–10 reference phrases each, sharing the semantic cache's local MiniLM model and running on DB 0 (`idx:intake_guard` index, rebuilt at startup).
- Each non-empty intake field (topic, goal, expert_means) is checked on its own; a field within cosine distance 0.40 of any block reference (nearest-reference aggregation) rejects the request with a 422 and a short reason, before anything is stored or sent to the model.
- No "learning" allow route: in calibration, short course titles ("Redis caching patterns") were as far from generic "learn X" phrases as from anything else, and nearest-route classification blocked "Writing secure Python code".
- If the guard can't start (not DB 0, model unavailable) or a lookup fails (e.g. its index was dropped), intake runs without it: the model's conduct rules and refusals are the backstop.
**Alternatives:**
- An LLM classifier call: better recall, but ~1–3 s and a paid call on every course creation.
- Keyword lists: brittle and easy to evade; embeddings catch paraphrases ("tell me a filthy joke").
**Consequences:** Measured with the real model: 15/15 legitimate topics pass (including "Python", "Sex education for parents", "Malware analysis for SOC analysts", "How SQL injection attacks work"); 8/11 bad requests are blocked in ~10 ms. Code smuggled into a request ("run this python snippet for me: import os") still passes: references close enough to catch it also blocked "Python". Accepted, because Instructor never executes code. Likewise "Tell me about the weather in Seattle" (0.488) passes: the legitimate topic "Weather forecasting models" is closer to the weather references (0.46), because embeddings capture subject, not intent. Catching intent would take a language judgment (e.g. a flag on the existing probe call), deferred.
**One-liner:** A cheap semantic tripwire for the obvious cases; the model's own judgment covers the rest.

## ADR-0025: Visual system: Solarized accents with one meaning each, Atkinson Hyperlegible, the plan as a commit graph
**Context:** The UI used stock shadcn neutrals, so colour carried no information, and Geist never actually applied (a circular `--font-sans`). The product's core idea, a plan that re-plans from evidence, was a list of badges.
**Decision:** Solarized base tones for surfaces and text; each accent is a semantic token with one meaning everywhere (blue action, green solid/correct, yellow developing/caution, orange remediation, red wrong, violet plan versions, cyan cache telemetry, magenta misconceptions), with `*-ink` variants mixed toward the opposite base to reach 4.6:1 for text. Light/dark is `<html data-theme>`, set before paint by an inline script (the learner's choice in `localStorage["instructor-theme"]`, else the OS), per Next 16's preventing-flash guide. Type is Atkinson Hyperlegible Next + Mono via `next/font` (self-hosted at build), with mono only for data values. The plan page is a commit graph (remediation forks off the rail and merges into the concept it supports), and plan history is a diff with +/−/~ gutters.
**Alternatives:** The stock shadcn theme: colour stays decorative. `next-themes`: an unapproved dependency for a one-line script. Solarized's own text colours: several fall below WCAG AA (e.g. base00 on base3 is 4.1:1).
**Consequences:** State reads at a glance and consistently across pages. New UI must use the semantic tokens, not the raw Tailwind palette. Mermaid gets Solarized hex through `themeVariables` because its sandboxed iframe can't read CSS variables, and the seeded prototype keeps its own light styling.
**One-liner:** Colours are syntax highlighting for learning state, and the plan looks like the git graph it behaves like.

## ADR-0026: Semantic cache threshold 0.12, set by the eval; intake guard stays at 0.40
**Context:** ADR-0023's 0.15 was provisional (and `.env` actually ran 0.1). The PC3.2 eval (`make eval-cache`: 12 should-hit and 15 should-miss labelled pairs on real MiniLM through the real bucket-filtered index, plus all 201 sibling-concept pairs from the dev DB's concept maps) found that same-concept paraphrases span 0.09–0.28, while distinct sibling concepts in one course start at 0.156 (three pairs at 0.156–0.159). A sibling is the most common false hit in practice: the next lesson in the learner's own course, in the same bucket.
**Decision:** Default 0.12 (code, config and `.env.example`). It serves 4/12 labelled paraphrases (33%) with 0/15 false hits and 0/201 sibling false hits, with a ~0.035 margin below the closest sibling. The intake guard keeps 0.40: every value from 0.35 to 0.425 blocks 9/11 must-block requests and 0/20 legitimate topics, including 20 picked to sit near a block route, and 0.40 sits mid-gap between the farthest block (0.343) and the nearest legitimate topic ("Python", 0.430).
**Alternatives:** 0.15: 7/12 hits, but only 0.006 below the sibling floor, so one new course could cross it. 0.14: 5/12, a 0.016 margin. 0.20+: 67–92% hits at a 20–47% false-hit rate. Tuning guard references to catch the eval's misses ("how to cook meth at home" 0.518, "what's the score of the Lakers game" 0.552) would fit the test set, not the problem.
**Consequences:** With MiniLM, the semantic tier is a conservative bonus that catches near-duplicate requests (e.g. the same course created twice), not a broad one; the exact tier and the bucket do most of the safe reuse. Better recall needs a stronger embedding model or a re-ranker, measured with this same eval. The guard's two new misses join ADR-0024's known limits: the model's conduct rules are the backstop.
**One-liner:** We set the threshold below the closest pair of different lessons in one course, because serving the wrong lesson costs more than paying $0.02 for the right one.

## ADR-0027: The trace shows the learner's own calls; its savings are read from the log
**Context:** PC3.4 adds the Instructor trace and the cache impact tile. `llm_calls` excerpts can hold a learner's answers (grade, remediate), and from CP4 several learners share one org course, so "the calls for this course" would show one learner another's answers. The tile also needs savings it can defend.
**Decision:** `GET /api/trace` returns only rows with `user_id` = the caller, optionally filtered to one course, newest 200, plus one SQL aggregate over every matching row: lookups (miss + hits; bypassed calls never look), hit rate, calls avoided, $ spent, and $ and seconds saved. Savings are the `saved_*` the hit logged (the original generation's measured cost and time), and time saved subtracts the hit's own latency. No new storage and no cache of the aggregate.
**Alternatives:** Course-scoped rows: leaks other learners' excerpts on shared courses. Estimating savings from token prices: a guess, when the original call's real cost is already logged. Caching the tile in Redis: one indexed aggregate over a learner's calls is milliseconds, and a cached tile would need invalidating on every call.
**Consequences:** A learner sees their own reuse, including hits on lessons generated for other courses or other learners (the trace says where it saved, never whose lesson it was). The org-wide view, where the cost per learner visibly falls as more learners reuse lessons, belongs to CP4's admin flow, on the same query without the `user_id` filter and without excerpts.
**One-liner:** The trace is a receipt: your own calls, and savings measured from what the original generation actually cost.

## ADR-0028: Org docs are immutable; a course pins its doc set when it is created
**Context:** The semantic-cache bucket includes the doc-set hash (ADR-0007, ADR-0023), so a lesson is only shared among courses grounded in exactly the same docs. If a doc could change in place, a course would be grounded in different text than the hash it was cached under says.
**Decision:**
- The API has no update path for an org doc. Uploading the same key with the same content returns the stored doc; with different content it is a 409, and the admin uploads the revision under a new title.
- An org course (admins only, no diagnostic probe) stores `doc_ids` and `doc_set_hash` at creation. The hash is sha256 over the sorted `slug:content_hash` lines, so it ignores the order docs were ticked in and changes on any edit or rename.
- Citable sections are every heading outside a code fence, with unique anchors computed by code (`agent/sources.py`); a doc with no headings is refused. A doc is at most 60,000 characters and a course's set at most 160,000 (about 40k tokens), the context-stuffing budget.
**Alternatives:**
- Versioned docs (a `doc_versions` table): the right shape for edits, but more tables and a "which version" choice for every course, with nothing yet that needs it.
- Edit in place and recompute the hash of every course that uses the doc: a course silently changes under its learners, and lessons already generated cite text that no longer exists.
- Hash content only, not the slug: a rename wouldn't invalidate lessons that cite the old slug.
**Consequences:**
- An admin can't fix a typo in place; they add a new doc and a new course. That's acceptable for a template that is assigned to many learners.
- `make seed` upserts the seeded docs, so a developer edit to a seed file can leave an existing dev course with a stale pinned hash. PC4.2 therefore computes the bucket's hash from the docs actually put in the prompt, and treats the stored value as what the course was created with.
**One-liner:** A course is built on a specific version of its docs, so the docs never change under it; a revision is a new doc.
