# Phase 1 build plan (pair checkpoints)

How Phase 1 is being built, step by step. Scope comes from [`build-brief.md`](build-brief.md), pedagogy from [`learning-design.md`](learning-design.md), and decisions from [`decisions.md`](decisions.md). Progress and lessons learned go in [`../BUILD_LOG.md`](../BUILD_LOG.md).

## How we work
- **Checkpoints (CP)** are split into **pair checkpoints (PC)**. Each PC ends with a short summary:
  - **Built**
  - **Architecture now** (a diagram, if it changed)
  - **Your turn ★** (Kyle writes a targeted piece against a test that's already written)
  - **Verify** (exact commands or clicks)
  - **Check** (2–3 understanding questions)
  - **Next**

  Then wait for "go".
- **One branch per CP** (`cpN/<slug>`), with a draft PR opened at the start. Commit and push after each PC. At the end of a CP, mark the PR ready; once CI passes, Kyle reviews and merges it (merge commit). `main` is protected: it needs a PR and passing `backend` + `web` checks.
- Use the `checkpoint` skill to close a PC or CP, the `adr` skill for decisions, and `new-instructor-skill` for every product skill.

## Status
| CP | Scope | State |
|---|---|---|
| CP0 | Foundations: repo, Postgres + Redis 8, FastAPI + Next.js wiring, CI, data model + migrations + seed, login + Redis sessions + dashboard cache, skill registry + `diagnose` scaffold | ✅ merged |
| CP1 | J1: create a course (intake → probe → assess → concept map → accept) | ✅ merged (PR #2) |
| CP2 | J2: learn, check, adapt | ✅ merged (PR #3) |
| CP3 | Redis deep dive: semantic cache, trace, cache impact | ✅ merged (PR #4) |
| CP4 | J3: org course grounded in docs | ✅ merged (PR #6) |
| CP5 | Dashboard + eval harness | ✅ merged (PR #7) |
| CP6 | Hardening + sample data, docs, tag `v0.1.0` | ✅ built, PR #8 ready for review (branch `cp6/hardening`): PC6.1 ✅, PC6.2 ✅, PC6.3 ✅; tag after both merge |

## CP1: J1, create a course
**Before starting:**
- Kyle adds `ANTHROPIC_API_KEY` to `.env`.
- Load the `claude-api` skill and confirm the current structured-output and streaming APIs before writing any LLM code.

| PC | Build | ★ Kyle |
|---|---|---|
| PC1.1 | **LLM client wrapper** (`agent/llm.py`): `AsyncAnthropic`; structured output via `output_config.format` (ADR-0013: forced tool use is a 400 on current models), validated against the call's Pydantic output model; one retry that feeds back the validation error; every call logged to `llm_calls` (tokens, latency, cost, status, prompt_version). Then `diagnose.probe` end to end and the intake form with recommended defaults. | — |
| PC1.2 | `diagnose.assess`: answers on one screen → assessed level, evidence, gaps, and a plain **adjustment message** when the assessment differs from the claim. | — |
| PC1.3 | `map-concepts` skill + `agent/plan.py` (`structure_errors`, `time_error`) as `ConceptMap` validators: unknown prereqs, cycles, a topological sequence, total time within ±15% of target. Re-ask once with the errors. | Write the cycle and unknown-prereq check against the tests |
| PC1.4 | Map editor: remove a concept (warns about its dependents), accept → enrollment + plan v1 + `concept_progress` rows; invalidate the dashboard. | — |

**CP1 done when:** intake → accepted map in under ~90s of LLM time; the prerequisite graph is valid; an over-claimer gets a lower level *and* an explanation.

## CP2: J2, learn, check, adapt
| PC | Build | ★ Kyle |
|---|---|---|
| PC2.1 | `agent/pedagogy.py` + tests: MCQ score, the lower-of-two combine rule, recency-weighted mastery (ADR-0005), bands, the unlock gate, `fsrs` scheduling (1–4 → Again/Hard/Good/Easy) | `update_mastery`, `band`, `mcq_score`/`combine` |
| PC2.2 | `teach-concept` with SSE streaming (partial JSON → `field_delta` events), the exact-match cache (`llm:exact:*` native JSON + `idx:llm_exact`), Mermaid rendering. **Check that SSE streams through the Next rewrite**; if it buffers, call FastAPI directly for this endpoint. ✅ Checked live: Next's gzip buffered it, so the route sends `Cache-Control: no-transform` instead (ADR-0020). | — |
| PC2.3 | Connection-pool simulator prototype in a sandboxed iframe (`srcdoc`, `sandbox="allow-scripts"`). ✅ Seeded by `make seed`; shown on matching lessons for hands-on learners | Find and explain its "surprise" threshold (done by the AI at Kyle's request) |
| PC2.4 | `design-assessment` (4 MCQ + 1 short transfer item; answer keys stay server-side), `grade`, submit, misconception logging. ✅ Two quiz calls, shared vs targeted (ADR-0021) | — |
| PC2.5 | Adaptation rules, `remediate`, plan versions + the diff UI. ✅ Remediation as an inserted prerequisite (ADR-0022) | The `adapt` branch table (done by the AI at Kyle's request) |
| PC2.6 | Prerequisite gate, override warning, test-out offer (ADR-0006). Draft 8 grader answers for Kyle to label. ✅ `backend/evals/grader_calibration.yaml` | Label the 8 answers (1–4): ✅ done by Kyle, used by `make evals` |

## CP3: Redis deep dive
| PC | Build | ★ Kyle |
|---|---|---|
| PC3.1 | RedisVL `SemanticCache` with filter buckets (ADR-0007) and the local MiniLM vectorizer. ✅ In the LLM wrapper, exact → semantic → model (ADR-0023) | The bucket and filter construction (done by the AI at Kyle's request) |
| PC3.2 | Cache eval: should-hit and should-miss pairs, a threshold sweep, choose the default threshold. Also re-check the intake guard's threshold on its calibration set. ✅ `make eval-cache`: default 0.12, guard 0.40 confirmed (ADR-0026) | — |
| PC3.3 | **Intake guard** (added by Kyle): a RedisVL `SemanticRouter` rejects crude, off-topic, dangerous or prompt-injection course requests before anything is stored or sent to the model. Block routes only, shared MiniLM, minimal code. ✅ ADR-0024 | — |
| PC3.4 | Trace page (`llm_calls`, cache result, similarity) + cache impact tile. ✅ `/trace` (all courses or one), the learner's own calls only (ADR-0027); a stored quiz result recomputes its "Next" and drops a stale test-out offer | — |

## CP4: J3, org course grounded in docs
| PC | Build |
|---|---|
| PC4.1 | The 4 Acme AI docs; `org_docs` with section anchors; upload/select. ✅ `agent/sources.py` (anchors, hashes), org docs API + page, org course drafts pinned to a doc set (ADR-0028); no migration needed (the columns existed) |
| PC4.2 | `ground-in-sources` (a modifier skill): citations on every claim, and "This isn't covered in your docs". ✅ Docs composed first in the prompt with code-computed anchors; `[n]` markers + citations with verbatim quotes checked by code (one retry on a bad one); grounded lessons, remediation lessons and quizzes; the composed docs' hash keys both cache tiers (ADR-0029); `make eval-grounding` |
| PC4.3 | Admin template flow (ADR-0004), then assign to dana. ✅ A docs-grounded map with no probe (`grounding: docs` call mode), accept = assignable template, assign = one enrollment per learner with a copy of the plan, the admin's course page (build → edit → accept → assign), and an org-wide cache impact view for admins (ADR-0030); `make eval-grounding` gained a template-map case |

## CP5: Dashboard + evals
| PC | Build |
|---|---|
| PC5.1 | Dashboard: mastery bands, "N due for review", badges. ✅ Per-concept band strip with a due ring (`pedagogy.band_counts`, `is_due`); the admin's "Org courses you manage" (`GET /api/orgs/{slug}/courses`) |
| PC5.2 | `make evals`: diagnosis personas, map constraints, pedagogy, grader calibration (Kyle's labels), grounding judge, cache false-hit rate. ✅ Through the wrapper, no cache tier; `judge-grounding` skill; first run $0.58 (ADR-0031) |

## CP6: Hardening + sample data
| PC | Build |
|---|---|
| PC6.1 | Sample learner state (kyle's course ~40% done with plan v1→v2), `make warm-cache`, `make reset` + `reset-sample-data` skill. ✅ Built through the real services; reset never flushes; warm-cache stores kyle's lessons and caches dana's |
| PC6.2 | `architecture.md`, `walkthrough.md`, `overview.md`, `ai-workflow.md`, README. ✅ |
| PC6.3 | Full run-through from `make reset`, then tag `v0.1.0`. ✅ Run-through done (live J1–J3); tag after merges |

## P1+ (only after CP6, in order)
1. **Outside knowledge in org courses** (designed, not built; see below)
2. Live LLM-generated prototypes (sandboxed)
3. Thin MCP surface: learn from Claude Code (`next_concept`, `get_lesson`, `submit_quiz`)
4. Instructor chat (thin)
5. Concept reordering in the map editor
6. Per-learner diagnostic probe for org courses
7. Dockerfiles for `web`/`api` + `docker compose --profile full`
8. Cloud deploy

### P1+ 1: outside knowledge in org courses
**Why:** today an org course is the docs and nothing else (ADR-0029: the map's concepts come only from the docs, and lessons allow general knowledge only as background or as an optional note on a gap). A good instructor would also add best practice and supplementary context. **Principle:** docs stay authoritative and cited; general knowledge is added in its own structured place and always labelled, so it can't be mistaken for the org's practice.
- **Lessons:** `LessonOutput.general_notes: list[{kind: background | best_practice | differs_from_docs, topic, note_md}]`, default `[]` (stored lessons still load; personal courses keep it empty). Validator: no `[n]` markers inside a note; a `differs_from_docs` note requires the lesson to cite the doc's side ("Acme does X; common practice is Y"). Rules in `ground-in-sources/SKILL.md`: the org's practice first, then up to ~3 notes, hedged and non-numeric, never invented org detail.
- **Map:** `Concept.basis: docs | general` (default `docs`). The template map may add concepts the docs assume or the goal's best practice requires, marked `general`. **Code enforces the cap** (≤30% of the map, at most 3 of 12), and the admin can already remove any concept.
- **Cite rules:** a lesson or quiz for a `general` concept needs no citation or gap (it still cites any doc that touches it).
- **Web:** a "Beyond your docs" section in the lesson, labelled "General knowledge, not from your docs"; a "General knowledge" badge on the template map.
- **Eval and docs:** three `make eval-grounding` cases (best-practice note on a covered concept; a general-basis concept; a doc-vs-practice conflict where the docs win), validator and cap tests, ADR-0032 amending ADR-0029, `data-model.md` for the two JSONB shape changes, `make types`. About one PC; ~$0.20 live.
- **Not part of it:** live web search for supplementary facts. It adds cost, latency and a new capability, and compatibility with structured outputs is unverified. Evaluate separately, with Kyle's OK.

## Known follow-ups
- ~~`StarletteDeprecationWarning`~~: resolved in PC1.1. The Anthropic SDK 1.x depends on `httpx2`, and Starlette's test client picks it up automatically.
- Draft courses aren't listed on the dashboard (it lists enrollments, which start at accept in PC1.4). Navigating away from a draft loses the link to it until then.
- Probe idempotency is check-then-insert: two truly concurrent POSTs could both call the model. The UI fires it once from the submit handler; add a lock or a unique constraint if that changes.
- ~~`assessments.answers` shape~~: resolved in PC1.2. Stored as `{question_id: answer}`; sent to the model as an ordered list.
- `docs/architecture/` (generated by `/visualizer:architecture`) is a CP1 snapshot; `docs/architecture.md` is current. Rerun the visualizer to refresh it (it's generated; don't hand-edit it).
- Data written back from Redis must be validated with Pydantic (`model_validate`), as in `auth.py` and `dashboard.py`.
- A lesson stream the client abandons (navigates away) is cancelled and **not logged** in `llm_calls`: under anyio's level cancellation, the log write would need a shielded cancel scope. The PC3.4 trace doesn't need them yet (it shows completed calls); add the shielded scope if abandoned spend should show.
- SSE payload models (`FieldDeltaEvent`, `DoneEvent`) aren't in the OpenAPI schema, because the route yields `ServerSentEvent`. The web mirrors `FieldDeltaEvent` by hand in the lesson page.
- The override's `warning` is echoed back by the client on confirm, so a client could log different text from what the server generated. Low stakes (it's the learner's own record); store the generated warning server-side if it matters.
- The quiz is designed in ~20 s. The lesson page prefetches it after a fresh lesson; a click during the prefetch can trigger a second design call (the first stored attempt wins, so there's no duplicate, only the cost).
- Submit holds no DB connection during the `grade` and `explain_change` calls (reads, release, model calls, then a row-locked write). The quiz-open path does the same.
- ~~Stale "Next" on a stored quiz result~~: resolved in PC3.4. `next_concept` is recomputed on read and a test-out offer that's been acted on is dropped; the rule, scores and why stay as recorded. A "retake" result read after a pass still says retake (it's history).
- The trace is the learner's own calls (ADR-0027). ~~An org admin's view of org-wide cache impact~~: resolved in PC4.3 (`/org/impact`, ADR-0030), counts and dollars only.
- Intake guard limits (ADR-0024): code smuggled into a request and chat-style subject requests ("Tell me about the weather in Seattle") pass, because embeddings judge subject, not intent. Deferred fix: a `not_a_learning_goal` flag on the existing `diagnose.probe` call (no extra model call).
- Intake guard misses found by the PC3.2 eval: "how to cook meth at home" (0.518) and "what's the score of the Lakers game" (0.552) pass. Not fixed by adding references (that fits the test set); the deferred probe flag above covers them too.
- Semantic-cache recall with MiniLM is ~33% of genuine paraphrases at the safe threshold (ADR-0026). Levers to try with `make eval-cache`: a stronger local embedding model (needs Kyle's OK), or embedding the title + mastery statement without the topic.
- Org docs are immutable via the API (ADR-0028), so a revised doc is a new doc and a new course. If admins need real revisions, versioned docs (`doc_versions`) are the upgrade; the grounded-prompt composer hashes the docs it actually sends (✔︎ PC4.2), because `make seed` upserts seeded docs.
- Grounding checks are deterministic (real sections, verbatim quotes, markers ↔ citations), but prose can still make an uncited claim. ✔︎ CP5's judge measures it (`make evals`); its first run found a couple of uncited Acme statements in one lesson. The judge itself needs human-labelled claims to be trusted (ADR-0031).
- Grader calibration: relabelled to follow the item rubric (a2→1, a5/a6→2); now exact 19/24, within one 24/24. Two gaps: no answer is labelled 3 (add one that explains setup cost, reuse **and** what breaks at 5,000, without numbers), and the terse transfer answer a8 scores 3 against a label of 4.
- Grounding: the second `make evals` run caught a lesson inventing "CPU and memory were never the constraint" (uncited, not in any doc). Levers: a rule in `ground-in-sources` against uncited causal claims about the org, or a per-sentence marker check for sentences that name an Acme service.
- Grounded calls re-send the docs every time (~10k input tokens for the seeded set). They're first in the system prompt, so API prompt caching (a `cache_control` breakpoint after the docs, and cache-read tokens in `llm_calls`) is a small change if doc sets grow.
- ~~PC4.3: the admin's template map needs `course_grounding` too~~: resolved in PC4.3. `grade` and `remediate.explain_change` aren't grounded (the rubric and the lesson already are).
- The template map isn't checked against the docs by code: nothing proves each concept is covered. A concept → docs mapping (and a coverage view for admins) would make it checkable (ADR-0030); until then it's the CP5 grounding judge's job.
- An admin can't edit an accepted template or un-assign a learner. Both are small changes on top of ADR-0004 if wanted (a new course is the workaround today, since docs are immutable).
- Org courses are docs-only by design today (ADR-0029). Adding outside knowledge (best practices, supplementary concepts, always labelled and docs-win) is designed under P1+ 1.
- The org docs page and the org-course form use the caller's first org membership (Phase 1 has one org per user). A multi-org picker comes with real multi-tenancy.
