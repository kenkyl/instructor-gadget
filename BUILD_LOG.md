# Build log

> **Current status:** CP0 in progress. PC0.1–PC0.4 done (foundations, data stores, wiring + CI, data model + migrations + seed).
> **Branch:** `cp0/data-model-auth` (draft PR #1). **Next:** PC0.5: login (choose a seeded user, session in Redis), `get_current_user`, dashboard cache-aside stub.

One entry per checkpoint. Each entry covers what we built, the key prompts and decisions, where the AI went wrong or needed correcting, and the tradeoffs we accepted.

---

## CP0 notes (in progress; folded into the CP0 entry when CP0 closes)
- **AI mistake:** CI referenced `astral-sh/setup-uv@v10`, but that action publishes no floating major tag. Pinned to `v10.3.0`.
- **AI design flaw caught through pairing:** the health check used `except Exception: pass`. During Kyle's ★ task, a typo and a misplaced `.scalar()` were swallowed and reported as "Postgres: error" while Postgres was healthy. The checks now log the exception.
- **Next.js 16** ships `AGENTS.md`, which warns that its APIs differ from older versions. The AI read the bundled docs before writing the rewrite config.
- **PC0.4:** Alembic's generated migration failed our own lint rules (old `typing` imports). Fixed the template so every future migration is generated clean. SQLAlchemy 2.1 deprecated `Result.tuples()`; the AI used it from older-version habit and the deprecation warning caught it.
- **Kyle's ★ (PC0.3):** added `postgres_version` end to end: failing test → Pydantic model → endpoint → `make types` → UI. `tsc` caught the stale types before regeneration.

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
