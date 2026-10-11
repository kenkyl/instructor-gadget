# Build log

> **Current status:** CP1 ✅ merged to `main` (PR #2). Next: **CP2 / PC2.1** (`agent/pedagogy.py`: scoring, mastery, bands, unlock gate, FSRS; ★ Kyle: `update_mastery`, `band`, `mcq_score`/`combine`) on branch `cp2/learn-check-adapt`.
> **Resuming in a new session:** read `CLAUDE.md`, this file, `docs/build-plan.md`, and `docs/decisions.md`, then start the next PC listed above. Load the `claude-api` skill before writing LLM code.

One entry per checkpoint. Each entry covers what we built, the key prompts and decisions, where the AI went wrong or needed correcting, and the tradeoffs we accepted.

---

## CP1: Create a course (Sun 2026-10-11, PR #2)

**What we built**
- **PC1.1, LLM client wrapper + probe + intake:** `agent/llm.py` is the only way to call the model: structured output via `output_config.format`, Pydantic validation, one retry with the errors (`_shared/retry.md`), server-side refusal fallback, and one `llm_calls` row per API request, written in its own transaction through a `CallSink`. `diagnose.probe` end to end (idempotent), plus the intake form with recommended defaults.
- **PC1.2, assess:** answers on one screen → assessed level, evidence per question, gaps, and a plain adjustment message. The input is passed as validation context (ADR-0015), the assessment is final (ADR-0014), and answers are treated as evidence, never instructions.
- **PC1.3, concept map:** the `map-concepts` skill, and `agent/plan.py` pure graph rules (unknown prereqs and cycle detection by Kyle; order; ±15% time in integer math) running as `ConceptMap` validators, so a bad map earns one re-ask. The map is stored as the course's base map (ADR-0016).
- **PC1.4, edit + accept:** cutting a concept rewires its dependents (ADR-0017). Accept creates the enrollment, plan v1 and `concept_progress` in one transaction (`pedagogy.initially_unlocked`), then invalidates the dashboard. Dashboard cards link to the course.
- **Numbers (live, end to end):** intake → accepted map = **24.5 s of LLM time** (probe 5.8, assess 6.5, map 12.2; target < 90 s) and **$0.045 per course**. The over-claimer was re-levelled with a specific reason. 70 deterministic tests.

**Key prompts**
- "Resume the Instructor build… Load the claude-api skill before writing any LLM code." Loading it is what exposed the forced-tool-use 400 before any code depended on it.
- "On verify step 1: should we fix this?" (9 high npm advisories). The AI traced all 9 to one unpatched `braces` advisory in dev-only tooling, where npm's "fix" is a breaking downgrade. Kyle chose no change.
- "I see two entries, but I refreshed twice." This exposed AI test data left in the dev DB. Live checks now use an in-memory sink or the throwaway test DB.
- The cut-a-prerequisite question (rewire / drop edge / cascade): Kyle chose rewire (ADR-0017).
- "I added an arch diagram via visualizer in another session and want to keep it in this PR." Kept as a generated artifact, not hand-edited.

**Decisions:** ADR-0013 (structured outputs, own validation), ADR-0014 (the assessment is final), ADR-0015 (input as validation context), ADR-0016 (`template_plan` is every course's base map), ADR-0017 (rewire on cut).

**Where the AI went wrong or was corrected**
- **AI mistake (PC0.6 verify step):** the AI told Kyle to edit a prompt file and re-curl `/api/skills`. The hash didn't change, because the registry is cached at startup and `fastapi dev` only reloads on `.py` changes. Fix: `make api` now runs uvicorn with `--reload-include '*.md' --reload-include '*.yaml'`, so prompt edits hot-reload in dev.
- **AI mistake (while testing that fix):** the AI started a test server on port 8001 without checking whether the port was free. It was in use by an unrelated local process, and the AI's cleanup (`kill` on whatever listened on 8001) stopped that process. Rule: check that a port is free before using it, and only kill PIDs the AI itself started.
- **PC1.1, plan vs. current API:** the plan said "structured output via forced tool use". Loading the `claude-api` skill before coding showed that current models (Sonnet 5.5, our default) reject forced `tool_choice` with a 400, and that `messages.parse()` raises on invalid output, losing the text and usage we log. The wrapper uses `output_config.format` and validates with Pydantic itself (ADR-0013). Checking the docs first avoided building on a dead API.
- **AI near-miss (PC1.1):** the registry loads `schema.py` by file path, so a normal `import agent.skills.diagnose.schema` would have created a second `ProbeOutput` class, and the wrapper's `isinstance`/contract checks would have failed at runtime. Caught while writing the service; the registry now shares one module via `sys.modules` (checked in both import orders).
- **AI mistake caught by a test (PC1.1):** `POST /courses/{id}/probe` returned 503 ("LLM not configured") to a user who doesn't own the course, because FastAPI resolves dependencies before the handler body. Ownership is now a dependency declared before `LlmDep`, so 401 → 404 → 503 is the order.
- **Process hygiene (PC1.1):** the AI verified that port 8765 was free before starting a test API. `pgrep` matched both the `uv` wrapper and its Python child, so the first `kill` failed harmlessly. The AI checked both command lines before stopping them. Nothing else was touched.
- **AI mistake (PC1.1 verify step):** the Verify step said "your call shows `ok`", but Kyle saw two rows. The second was the AI's own end-to-end test course, left in the dev DB without saying so. Rule: any live test data the AI creates is called out in Verify, or goes in-memory or under a throwaway user (PC1.2's live runs used an in-memory sink).
- **PC1.2, the prompt failed live runs that fakes would have passed:** the three `assess` eval cases (over-claimer, prompt injection, under-claimer) passed their asserts on the first live run, but reading the outputs showed three problems. The model promised a reassessment the product doesn't offer (→ ADR-0014). It listed untested topics as "gaps". And it said "start at intermediate" for a learner assessed *strong* (it mixed up the starting level with the target level). Each fix was one prompt line, re-run live. Lesson: asserts check the fields; a human still has to read the words.
- **AI mistake caught by its own test (PC1.3):** `time_error` used floats, and `180 * 1.15 == 206.99999999999997`, so a map at exactly +15% would have been rejected and sent for a pointless re-ask. Now integer math.
- **AI near-miss (PC1.3):** the AI wrote a developer note about cache policy into `SKILL.md`'s body, which is sent to the model as instructions. Moved to a YAML comment; the `new-instructor-skill` skill now warns about it.

- **AI near-miss (PC1.4):** a new test asserted kyle's dashboard was empty before accept, which only held because of test order. Caught on review and rewritten to filter by the course under test.

**Tradeoffs accepted**
- `diagnose` and `map-concepts` are never cached: about 4.5¢ and 25 s per new course, in exchange for never serving one learner's diagnosis to another. Revisit `map-concepts` for org templates (CP4).
- Generated maps chain early concepts more linearly than they need to. Noted as a CP5 judge ("is each prereq a real dependency?"), not fixed by prompt guesswork now.
- Probe idempotency is check-then-insert (a true double-POST race could make two calls); the UI fires it once.
- Draft courses aren't listed on the dashboard until accepted.
- npm audit: one unpatched advisory in dev tooling, left as is (Kyle's call).

**Kyle's ★:** `find_unknown_prereqs` + `find_cycle` (iterative three-state DFS), plus an extra test the AI missed: a path *into* a loop must be trimmed from the reported cycle.

**How to verify:** `make up && make migrate && make seed && make test` (70 pass). Then `make dev` → log in as kyle → New course → answer the probe badly → see the re-level message → Build my concept map → remove a concept that others need (warning, then rewire) → Accept → the course appears on the dashboard.

## CP0: Foundations (Sat 2026-10-10 → Sun 2026-10-11, PR #1)

**What we built**
- **PC0.1, repo foundations:** public repo (PolyForm Noncommercial), a product-only brief, roadmap, ADRs, CLAUDE.md, build skills (`checkpoint`, `adr`, `new-instructor-skill`), and private material kept in gitignored `docs/private/`.
- **PC0.2, data stores:** Postgres 16 + Redis 8.10 in Docker (bound to localhost, with healthchecks), plus `make doctor`, which proves the Query Engine is present via `FT._LIST`.
- **PC0.3, app wiring:** FastAPI (lifespan-managed async engine + Redis) behind a Next.js 16 `/api` rewrite, `/api/health`, OpenAPI → TypeScript types, and CI (ruff, pytest against real stores, OpenAPI drift check, eslint, tsc).
- **PC0.4, data model:** 15-table async SQLAlchemy model, with per-learner state on `enrollments` (ADR-0004). The first Alembic migration, an idempotent seed (Acme; kyle, dana, priya), an isolated `instructor_test` DB, and `alembic check` in CI. `docs/data-model.md` was written by a forked subagent.
- **PC0.5, login:** seeded-user login, sessions as a Redis **hash** with TTL (atomic `MULTI/EXEC`), an opaque HttpOnly cookie, `get_current_user` as the single auth seam, and a native-**JSON** dashboard cache-aside (ADR-0011). On the web side: Next `proxy.ts` (optimistic cookie check), login, dashboard, status pages, and shadcn/ui.
- **Between PCs:** branch-per-CP with draft PRs, and `main` protected (PR + passing checks). Pyright (standard mode) plus pytest failing on un-awaited coroutines (ADR-0012).
- **PC0.6, skill registry:** `agent/registry.py` discovers and strictly validates skill folders, enforces the never-cache list, composes conduct + skill + call (+ grounding) prompts, and computes `prompt_version = name@semver+sha8`. Includes the `diagnose` skill scaffold (probe + assess contracts and validators), `/api/skills`, and fail-fast loading at startup. **16 tests.**

**Key prompts**
- Planning: "Follow §0 of the brief and reply with everything in §11", then add pair programming, a public repo, best practice, and a license.
- "Let's make a feature branch for continued work if it makes sense", which led to branch-per-CP with draft PRs and branch protection.
- "Use the Redis native JSON data type instead of serialized strings… if you disagree, tell me." The AI partly disagreed: a hash for sessions, JSON for documents (ADR-0011).
- "Any rules added should capture schema changes elsewhere… and any data stores that could eventually be added," which became the persisted-data rule in CLAUDE.md.

**Decisions:** ADR-0010 (schema conventions), ADR-0011 (Redis types by access pattern), ADR-0012 (two safety nets for a missing `await`).

**Where the AI went wrong or was corrected**
- **CI action tag:** CI referenced `astral-sh/setup-uv@v10`, but that action publishes no floating major tag. Now pinned to `v10.3.0`.
- **Swallowed health-check errors:** the health check used `except Exception: pass`. During Kyle's ★ task, a typo and a misplaced `.scalar()` were swallowed and reported as "Postgres: error" while Postgres was healthy. Checks now log the exception.
- **Old Alembic template:** Alembic's generated migration failed our own lint rules (old `typing` imports). The template is fixed so future migrations come out clean.
- **Deprecated SQLAlchemy call:** SQLAlchemy 2.1 deprecated `Result.tuples()`. The AI used it from older-version habit, and the deprecation warning caught it.
- **Unverified dependency:** shadcn init added an unfamiliar `cn` dependency. The AI checked that it's shadcn's own package (repo shadcn-ui/cn, MIT) before accepting it.
- **Commit on a failing lint:** the AI's commit script ran `make lint`, which failed, but didn't stop, and committed anyway. CI caught it. Fix: checks now gate the commit (`make lint && make test && git commit`).
- **Overclaim about pyright:** the AI said pyright would catch Kyle's missing `await`. Tested in PC0.6, it didn't: redis-py types its commands as `Awaitable[int]`, not as coroutines. Fix: pytest now fails on "coroutine … was never awaited" (ADR-0012), proven with a throwaway failing test.
- **Unfounded data-model details:** the forked subagent's data-model doc stated a few details that hadn't been decided yet (cache TTL, cookie flags). They were reconciled against the code in PC0.5.

**Kyle's ★ tasks**
- **PC0.3:** added `postgres_version` end to end (failing test → model → endpoint → `make types` → UI). `tsc` caught the stale types.
- **PC0.4:** used `psql` to show the scope check rejecting a bad course, and that string enums accept invalid values (the ADR-0010 tradeoff), which the seed repaired.
- **PC0.5:** implemented `invalidate_dashboard`. The first attempt was missing `await`, and the test caught it.

**Tradeoffs accepted**
- String enums: easy to evolve, but not enforced by the DB.
- JSONB for shapes that are still evolving.
- Server-side sessions: one Redis lookup per request.
- Delete-not-patch cache invalidation.
- Redis-py `await` bugs are caught at test time, not statically.

**How to verify:** `make up && make migrate && make seed && make doctor && make lint && make test`, then `make dev`, open http://localhost:3000, log in as kyle and check the "served from cache" badge. `/status` shows the stack health, and `/api/skills` lists `diagnose` with its prompt versions.

---

## Planning: Sat 2026-10-10

**What we did**
- Wrote the build brief and the learning-design spec in a separate Claude project, then started Claude Code (Opus 5.5) in plan mode pointed at both.
- Claude replied with clarifying questions, a stack recommendation, a repo layout, a refined data model, the API, Pydantic sketches of the skill contracts, and a checkpoint plan with time estimates.
- Two more rounds of plan revision before approval (below).

**Key prompts**
- "Read docs/build-brief.md and docs/learning-design.md in full. Follow §0 of the brief and reply with everything in §11. Don't write any code yet."
- Second round: make the repo public, show a Mermaid architecture diagram before sign-off, run the build as **pair programming** with frequent review checkpoints, follow current best practice, relax the time box, and plan a Google Slides deck alongside.
- Third round: choose a license that stops others from monetizing the project.

**Decisions** (ADR-0001 to ADR-0009 in `docs/decisions.md`)
- Python/FastAPI + Next.js. A hand-rolled agent on the Anthropic SDK. The product-skills architecture.
- Enrollments (per-learner plans), with org courses built as admin templates.
- Recency-weighted mastery. Test-out instead of skip.
- Cache scoping. Async stack + Alembic. PolyForm Noncommercial license.

**Where the AI went wrong or was corrected**
- **Missed in the first plan:** it optimized for speed. The user redirected to pair programming, so they'd understand and be able to explain every component. The first plan had no checkpoints for learning or review.
- **Caught by the AI:** two conflicts inside the spec. The mastery formula contradicted the "a 3 means solid" rule, and "skip on a 4" contradicted "mastery only from graded retrieval". Both went to the user as questions instead of being silently resolved.
- **Caught by the AI:** a caching gap in the brief. Analogy domain and per-learner assessment were inputs to lesson generation but not part of the cache bucket, which would have served personalized lessons to the wrong learners.
- **Blocked by the safety classifier:** the AI tried to build a mermaid.live link to render the diagram; the auto-mode classifier blocked it as a public upload. That was the right call, and the diagram was shown inline instead.
- **Caught late by the AI:** planned to commit the brief verbatim until the public-repo decision. It contained personal planning notes, so a product-only copy is public and the original moved to a gitignored `docs/private/`.

**Tradeoffs accepted**
- Two languages (Python + TS), in exchange for RedisVL and local embeddings. Generated types limit the cost.
- A stricter, slower mastery path (test-out, never skip), in exchange for honest mastery.
- Source-available rather than OSI open source, in exchange for keeping commercial rights.
