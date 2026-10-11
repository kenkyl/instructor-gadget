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
| CP2 | J2: learn, check, adapt | ✅ ready for review (PR #3) |
| CP3 | Redis deep dive: semantic cache, trace, cache impact | |
| CP4 | J3: org course grounded in docs | |
| CP5 | Dashboard + eval harness | |
| CP6 | Hardening + sample data, docs, tag `v0.1.0` | |

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
| PC2.6 | Prerequisite gate, override warning, test-out offer (ADR-0006). Draft 8 grader answers for Kyle to label. ✅ `backend/evals/grader_calibration.yaml` | Label the 8 answers (1–4): still open, needed by CP5 |

## CP3: Redis deep dive
| PC | Build | ★ Kyle |
|---|---|---|
| PC3.1 | RedisVL `SemanticCache` with filter buckets (ADR-0007) and the local MiniLM vectorizer | The bucket and filter construction |
| PC3.2 | Cache eval: should-hit and should-miss pairs, a threshold sweep, choose the default threshold | — |
| PC3.3 | Trace page (`llm_calls`, cache result, similarity) + cache impact tile | — |

## CP4: J3, org course grounded in docs
| PC | Build |
|---|---|
| PC4.1 | The 4 Acme docs; `org_docs` with section anchors; upload/select |
| PC4.2 | `ground-in-sources` (a modifier skill): citations on every claim, and "This isn't covered in your docs" |
| PC4.3 | Admin template flow (ADR-0004), then assign to dana |

## CP5: Dashboard + evals
| PC | Build |
|---|---|
| PC5.1 | Dashboard: mastery bands, "N due for review", badges |
| PC5.2 | `make evals`: diagnosis personas, map constraints, pedagogy, grader calibration (Kyle's labels), grounding judge, cache false-hit rate |

## CP6: Hardening + sample data
| PC | Build |
|---|---|
| PC6.1 | Sample learner state (kyle's course ~40% done with plan v1→v2), `make warm-cache`, `make reset` + `reset-sample-data` skill |
| PC6.2 | `architecture.md`, `walkthrough.md`, `overview.md`, `ai-workflow.md`, README |
| PC6.3 | Full run-through from `make reset`, then tag `v0.1.0` |

## P1+ (only after CP6, in order)
1. Live LLM-generated prototypes (sandboxed)
2. Thin MCP surface: learn from Claude Code (`next_concept`, `get_lesson`, `submit_quiz`)
3. Instructor chat (thin)
4. Concept reordering in the map editor
5. Per-learner diagnostic probe for org courses
6. Dockerfiles for `web`/`api` + `docker compose --profile full`
7. Cloud deploy

## Known follow-ups
- ~~`StarletteDeprecationWarning`~~: resolved in PC1.1. The Anthropic SDK 1.x depends on `httpx2`, and Starlette's test client picks it up automatically.
- Draft courses aren't listed on the dashboard (it lists enrollments, which start at accept in PC1.4). Navigating away from a draft loses the link to it until then.
- Probe idempotency is check-then-insert: two truly concurrent POSTs could both call the model. The UI fires it once from the submit handler; add a lock or a unique constraint if that changes.
- ~~`assessments.answers` shape~~: resolved in PC1.2. Stored as `{question_id: answer}`; sent to the model as an ordered list.
- After CP1, consider rerunning `/visualizer:architecture` so `docs/architecture/` gains the assess and map flows (it's generated; don't hand-edit it).
- Data written back from Redis must be validated with Pydantic (`model_validate`), as in `auth.py` and `dashboard.py`.
- A lesson stream the client abandons (navigates away) is cancelled and **not logged** in `llm_calls`: under anyio's level cancellation, the log write would need a shielded cancel scope. Add one if the trace page (PC3.3) needs abandoned calls.
- SSE payload models (`FieldDeltaEvent`, `DoneEvent`) aren't in the OpenAPI schema, because the route yields `ServerSentEvent`. The web mirrors `FieldDeltaEvent` by hand in the lesson page.
- The override's `warning` is echoed back by the client on confirm, so a client could log different text from what the server generated. Low stakes (it's the learner's own record); store the generated warning server-side if it matters.
- The quiz is designed in ~20 s. The lesson page prefetches it after a fresh lesson; a click during the prefetch can trigger a second design call (the first stored attempt wins, so there's no duplicate, only the cost).
- Submit holds no DB connection during the `grade` and `explain_change` calls (reads, release, model calls, then a row-locked write). The quiz-open path does the same.
