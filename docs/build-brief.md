# Build brief: "Instructor", an adaptive learning-course agent

This is the product and engineering brief for Phase 1. How the instructor teaches is specified in
[`learning-design.md`](learning-design.md). Refinements made during planning (mastery weighting,
test-out on a 4, org-course templates, stack choices) are recorded in [`decisions.md`](decisions.md),
and the full product vision lives in [`roadmap.md`](roadmap.md).

**Sample org:** a fictional engineering org, "Acme AI", needs to ramp new engineers onto
on-call faster, using courses grounded in its own runbooks and postmortems. The sample course topic is
incident investigation and on-call fundamentals.

## 1. Product

**One-liner:** an AI instructor that diagnoses where you really are, maps the concepts and prerequisites you need, teaches them one at a time with zero-hint quizzes, and re-plans as it learns what you actually know, not what you say you know. It works for individuals and for organizations, whose courses can be grounded in internal docs.

**Vision:** think Udemy + MasterClass + an all-in-one expert personal trainer. It covers any topic, technical or not, at both the individual and org level. Phase 1 sample content focuses on technical topics.

**Users**
- **Learner:** creates personal courses and takes assigned org courses. Can run 1–N courses at a time.
- **Org admin** (eng manager or enablement lead): creates org courses grounded in internal docs and assigns them to members.

**Pedagogy: `docs/learning-design.md` is the source of truth.** Read all of it before planning. It's our own spec, inspired by the `deep-learn` Claude skill and by learning-science research; it isn't a copy of that skill, and nothing from the skill is vendored into this repo. Its core rule:

> **Understanding is demonstrated, not declared.** Mastery is only ever recorded from a graded retrieval attempt, never from "makes sense, I get it" or from finishing a reading.

This brief covers *what to build and when*. The spec covers *how the instructor teaches*. If they conflict, ask me.

**Course lifecycle (the instructor agent's job)**
`intake → diagnostic probe → assessment → concept map (prereqs) → learner edits/accepts → per-concept loop (explain → example → diagram/prototype → zero-hint quiz → grade 1–4 → mastery + review schedule → adapt) → completion badge → spaced review`

**Course config knobs (set at intake)**
| Knob | Values | MVP behavior |
|---|---|---|
| Topic / goal | free text | required |
| What "expert" means to you for this topic | free text, with a suggested default | shapes the concept map's end state |
| Deadline / mode | **cram** (e.g. an interview tomorrow) vs. **foundation** (building over weeks) | cram: fewer concepts, prioritize must-knows, fewer reviews; foundation: full map, spaced review on |
| Analogy domain / interests | free text (e.g. "cooking", "basketball", "databases") | explanations reach for analogies from this domain |
| Target length | estimated hours (e.g. 1–20) | plan must fit within ±15% |
| Target level | beginner / intermediate / advanced / expert | shapes depth |
| Self-reported current level | novice / intermediate / strong / expert | **confirmed or overridden** by the diagnostic probe |
| Learner style (a format preference; see spec §6) | reading, quizzes, hands-on, visual, audio, writing | MVP implements **reading, quizzes, hands-on exercises**. Others are accepted and stored, and the UI labels them "coming soon". |
| Grounding docs (org only) | uploaded markdown/text | stuffed into context (see §4, design decision 4) |

**Use cases (context only, not all built):**
- Preparing for certifications and tests
- Technical enablement and onboarding (e.g. new engineers, on-call ramp)
- Non-technical enablement and onboarding (e.g. GTM new-hire training)
- Org-specific training using custom context: internal documentation, processes, playbooks
- Replacing existing paid learning subscriptions (Udemy and similar)
- Learning new domains
- Preparing for interviews, for meetings, and learning about customers

## 2. Phase 1 journeys

### J1: Create a course with diagnosis and concept map
1. Learner logs in (seeded user) and lands on the dashboard.
2. Clicks **New course**. **Round 1, intake** (spec §4.1): a single form with the knobs in §2, each pre-filled with a recommended default so the learner can accept most of them in one click.
3. **Round 2, diagnostic probe** (spec §4.2): the instructor generates **3–4 real questions at the level the learner claimed**. The learner answers them all on one screen (free text). Self-reported level is unreliable in both directions, so the answers decide.
4. **Assessment:** assessed level, confidence, evidence (which answers drove it), and gaps. If the claimed level and the evidence disagree, the instructor **says so plainly**, e.g. "You said intermediate, but your answer on X suggests we start a step earlier. Here's why." No silent re-sequencing and no flattery.
5. **Concept map** (spec §4.4): 6–12 concepts in Phase 1. Each concept has an id, title, a one-line **mastery statement** with an objective level, **prerequisites**, estimated minutes, and a concept type. They're shown as a **dependency-ordered list with the instructor's reasoning for the sequence**. Total time fits the target hours.
6. Learner can **remove concepts** (P1; reordering is P1+), then clicks **Accept**. The course appears on the dashboard.

**Done when:**
- A fresh course goes from intake to accepted map in under about 90 seconds of LLM time.
- The prerequisite graph is valid: no unknown prereqs, no cycles (checked in code).
- A learner who claims "intermediate" but answers like a novice gets a lower assessed level *and* an explicit explanation.

### J2: Learn, check, adapt
1. Learner opens the next **unlocked** concept. A concept unlocks when every prerequisite is **solid or better** (spec §4.8).
2. **Lesson** (spec §4.5) streams in:
   - explanation (counterintuitive part first, learner's analogy domain)
   - worked example
   - Mermaid diagram
   - **prototype**, if the learner chose hands-on. P1 renders a **pre-seeded** prototype in a sandboxed iframe (`srcdoc`, `sandbox="allow-scripts"`). Live generation is P1+.
3. **Quiz** (spec §4.6): 4 zero-hint transfer questions; distractors tagged with the misconception each represents, including this learner's logged ones; plus an optional "explain it in your own words" item.
4. **Grading** (spec §4.7): the 1–4 rubric, the multiple-choice mapping, the LLM-graded short answer, and the "lower of the two" combination rule. Feedback names the misconception, and it's logged.
5. **Mastery estimate and bands** (spec §4.9) and the **review schedule** via the `fsrs` package (spec §4.10) update in the database.
6. **Adaptation is visible** (spec §4.8). Deterministic rules decide; the LLM only writes the "why" and the remediation content.
   - A **4** offers to compress or skip the next concept.
   - A **1–2** inserts a remediation concept that targets the named misconception from a different angle.
   - Opening a locked concept shows a specific warning and allows a logged override.
   - Every change creates **plan v(n+1)** with a **diff** and a plain-English **why**.

7. Learner continues. When every concept is at least solid, the course is complete and a **badge** appears on the dashboard. The dashboard also shows each course's **mastery bands per concept** and **"N concepts due for review"**, computed from the review dates. The review *session* itself is P2.

**Done when:**
- A deliberately bad quiz attempt reliably inserts remediation that names the misconception.
- A transfer-quality short answer reliably earns a 4 and offers a skip.
- Both cases show the diff and the why.
- Mastery and due dates update in the database.

### J3: Org course grounded in internal docs
1. Org admin (seeded) creates an org course, e.g. "Technical readiness at Acme AI", and uploads or selects Acme's internal docs.
2. The same J1 flow runs, but the concept map, lessons, and quizzes are **grounded in the docs**. (spec §5) Lessons cite the doc and section they draw from. If something isn't in the docs, the instructor says so instead of inventing it.
3. Admin assigns the course to a learner, and it appears on that learner's dashboard as an org course.

**Done when:** lesson content cites real sections of the seeded docs, and one question about something absent from the docs is clearly flagged as "not in your docs".

### Also in Phase 1
- **Dashboard:** active courses (1–N) with progress bars, completed courses with badges, org vs. personal labels.
- **Agent trace (minimal):** every LLM call is logged (see §4). Show a simple per-course "Instructor trace" page listing skill, model, tokens, latency, estimated cost, status, and **cache result** (exact hit / semantic hit with similarity score / miss).
- **Cache impact tile** on the trace page or an admin view: hit rate, LLM calls avoided, estimated $ and seconds saved. The value story: the cost per learner falls as an org scales because later learners reuse earlier generations.

## 3. Phase 1 checkpoints (build order)

| CP | Scope |
|---|---|
| CP0 | Plan approved. Repo scaffold, CLAUDE.md, BUILD_LOG.md, `.claude/skills/` (`checkpoint`, `new-instructor-skill`; see `roadmap.md`), product skills registry stub, docker-compose (Postgres + Redis 8), FastAPI + Next.js hello-world talking to each other, DB schema, seed users, simple login (pick seeded user → session in Redis) |
| CP1 | J1: intake form (with defaults) → batch diagnostic probe → assessment (with transparent level adjustment) → concept map with prereqs + DAG validation → remove/accept |
| CP2 | J2: JIT lesson (explanation, example, Mermaid diagram, seeded prototype iframe) with SSE streaming + exact-match Redis cache; zero-hint quiz + 1–4 grading + misconception logging; `pedagogy.py` (scoring, mastery, bands, `fsrs` due dates); prereq unlock gate; rules-based adaptation; plan versioning + diff UI |
| CP3 | LLM client wrapper logging to `llm_calls`; **semantic cache tier** (RedisVL); trace page with cache results + cache impact tile |
| CP4 | J3: org, docs upload/select, grounded generation with citations, assignment |
| CP5 | Dashboard (mastery bands, "N due for review", badges) + mini eval harness (§6) |
| CP6 | Hardening: sample data + warm cache, `make reset`, README, `docs/` deliverables (§8), tag `v0.1.0` |
| P1+ | Only if time allows, in this order: live LLM-generated prototypes (sandboxed), thin MCP surface (learn from Claude Code), instructor chat (thin), concept reordering in the map editor, Dockerfiles for `web`/`api`, cloud deploy |

**Protected (never cut):** J1, J2 with the plan diff, and the semantic cache with visible hits in the trace.

**If behind, cut in this order:** trace page polish (keep logging and cache results) → badges → seeded prototype iframe (keep the diagram) → J3 assignment step (keep grounding) → LLM-as-judge grounding eval (keep the deterministic, grader-calibration, and cache evals).

## 4. Architecture and stack

**Stack decision:** Python (FastAPI) backend with an in-process agent package, plus a Next.js frontend. Rationale in `decisions.md`.

- **Frontend:** Next.js (App Router) + TypeScript + Tailwind + shadcn/ui. Clean and plain; no design time.
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x (or SQLModel). `create_all` is fine for MVP; no migrations needed.
- **Agent:** a Python package (`backend/agent/`) **in-process with the backend**, with a clean module boundary so it could become a separate service later. **Hand-rolled on the Anthropic Python SDK, no LangGraph.** The course lifecycle is an explicit state machine with LLM calls inside each stage, so a graph framework adds learning curve without buying anything here. Document this in `decisions.md`.
  - Every LLM call returns **structured output** (a JSON schema via `output_config.format`; ADR-0013) validated by Pydantic. On validation failure, retry once with the error, then surface a friendly error.
  - Model from env `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`). Prompts live in the product skill folders (§4.1) as versioned files, not inline strings.
- **Postgres 16:** durable source of truth.
- **Redis 8 Open Source** (official `redis:8` image; Redis 8 includes the Query Engine with vector search, so no Redis Stack is needed; verify with `FT._LIST` at CP0). Each use has a specific job:
  1. **Session store:** session token → user, with TTL.
  2. **User data cache at and after login:** on login, warm the user's dashboard data (courses, progress, badges) into Redis. Serve reads cache-aside with TTL, and invalidate on writes.
  3. **Two-tier LLM response cache in front of generation.**
     - **Tier 1, exact match:** hash of (skill, normalized inputs, model, skill version) → response. Catches identical requests, e.g. every learner in an org course opening the same concept.
     - **Tier 2, semantic:** use **RedisVL's `SemanticCache`** (verify the current API in the RedisVL docs). Embed the concept request (title + mastery statement) and look up the nearest cached generation **within a filter bucket** of `org_id` (or `public`), `target_level`, `learner_style`, `prompt_version`, and a grounding-doc-set hash. A personalized or org-grounded lesson must never leak across buckets.
     - **Embeddings:** run locally with a small sentence-transformers model through RedisVL's HF vectorizer (e.g. `all-MiniLM-L6-v2`), so the Anthropic API stays the only external dependency. Make the vectorizer swappable.
     - **Distance threshold** is configurable via env, starting conservative. Every lookup records hit/miss, tier, and similarity in `llm_calls`.
     - **Apply it to** first-pass `teach-concept` and `design-assessment` output for a concept in P1, and to the P2 `coach-chat` `explain_concept` call (the classic FAQ-style semantic cache case). **Bypass the cache** whenever the request includes the learner's own logged misconceptions (remediation lessons, misconception-targeted quizzes), and never cache `diagnose`, `grade`, or `remediate`: they're learner-specific by definition. This split between shared and personal content is a key design point.
     - The design rationale goes in `decisions.md`: the model is the slowest, most expensive, and least predictable component, so the engineering is in deciding what reaches it. The risk is a **false hit** (serving a lesson on liveness probes for a readiness-probe concept), which is why the threshold, the filter buckets, and the eval in §6 exist.
  - **Not** pub/sub or Streams in Phase 1. It's a single process, so SSE straight from FastAPI is enough. Note pub/sub and Streams as the Phase 3 path when generation moves to background workers.
- **Streaming:** SSE from FastAPI for lesson generation.
- **Local dev:** `docker compose up -d` runs Postgres and Redis only. The app processes run natively with hot reload. One command each (`make api`, `make web`) or `make dev`.
- **Containers:** the target is containerized services: `web`, `api` (with the agent package inside it for now), `postgres`, and `redis`. For Phase 1 speed, only the data stores run in Docker. If CP6 finishes early, add Dockerfiles for `web` and `api` and a `docker compose --profile full up` path. Otherwise this is Phase 2.
- **External dependencies in the MVP:** only the Anthropic API. Everything else runs locally (the embedding model is downloaded once).

### 4.1 Product skills architecture (the instructor's teaching abilities)
Each instructor capability is a **product skill**: a folder in `backend/agent/skills/<name>/` containing
- `SKILL.md` (instructions)
- `schema.py` (Pydantic input/output contract)
- optional `references/` (e.g. prototype patterns by concept type)
- `evals/` (cases for this skill)

A small **registry/loader** composes the shared conduct rules (spec §7), the skill's `SKILL.md`, and, for org courses, the `ground-in-sources` skill into the system prompt. It then calls the LLM client wrapper (structured output, cache, logging) and validates against the schema.
- **P1 skills:** `diagnose`, `map-concepts`, `teach-concept`, `design-assessment`, `grade`, `remediate`, `ground-in-sources` (spec §10).
- **Skills do language; code does decisions.** Scoring, gating, mastery, adaptation rules, and scheduling stay in `pedagogy.py`.
- **Why skills:** each teaching ability is versioned (its version feeds the cache key and `llm_calls.prompt_version`), testable on its own, and swappable. Course-type playbooks and org-authored skills plug in later without code changes. Record this in `decisions.md`.

**Data model (starting sketch; refine it)**
- `orgs`, `users`, `memberships(user_id, org_id, role)`
- `courses(id, owner_user_id NULL, org_id NULL, title, config JSONB, status, current_plan_version, created_at)`
- `course_assignments(course_id, user_id, assigned_by)`
- `assessments(course_id, user_id, transcript JSONB, assessed_level, confidence, evidence JSONB, gaps JSONB)`
- `courses.config` holds the knobs. `courses.mission JSONB` holds goal, "what expert means", mode, deadline, and analogy domain (spec §4.1).
- `plan_versions(course_id, version, plan JSONB, trigger ENUM[diagnosis|quiz_result|prereq_override|user_request], reason TEXT, created_at)`. `plan` is the **concept map**: concepts with prereqs, plus a sequence and its rationale.
- `concept_progress(course_id, user_id, concept_id, mastery, band ENUM[shaky|learning|solid|mastered], status ENUM[locked|unlocked|in_progress|complete], last_score, attempts, last_attempt_at, fsrs_card JSONB, due)`: the learner model in spec §3.
- `misconceptions(course_id, user_id, concept_id, note, source_question, created_at, resolved_at NULL)`: fed into later quiz distractors (spec §4.6).
- `lessons(course_id, concept_id, plan_version, explanation_md, example_md, diagram_mermaid, prototype_html NULL, citations JSONB)`
- `quiz_attempts(course_id, user_id, concept_id, questions JSONB, answers JSONB, score_1_4, graded_feedback JSONB, misconceptions_named JSONB)`
- `prereq_overrides(course_id, user_id, concept_id, warned_about TEXT, created_at)`
- `org_docs(org_id, title, content_md)`
- `llm_calls(id, course_id, skill, call, model, prompt_version, cache_result ENUM[miss|exact_hit|semantic_hit|bypass], similarity NULL, input_tokens, output_tokens, latency_ms, est_cost_usd, status, error, prompt_excerpt, response_excerpt, created_at)`. Cache hits are logged too, with zero tokens and cost, so the trace shows what was avoided.

**Key design decisions to implement and document**
1. **Plan versioning:** every plan change writes a new version with `trigger` + `reason`. The diff UI reads from this table.
2. **Just-in-time generation:** generate the concept map up front, and generate lesson content only when a concept is opened. This is faster to first value, cheaper, and the only way adaptation can change what comes next.
3. **Rules-then-LLM adaptation** (see J2).
4. **Context stuffing, not RAG, for grounding:** org docs are small (under about 50k tokens), so put them directly in context with section anchors and require citations. RAG is the documented upgrade path for large doc sets. Since Redis vector search is already in the stack for the semantic cache, prefer **Redis as the vector store** for that upgrade over adding pgvector, and document the tradeoff.
5. **Two-tier cache with filter buckets** (see the Redis section above): what's cached, what's never cached, and why.
6. **Learning design** (`docs/learning-design.md`):
   - Mastery comes only from graded retrieval, using the 1–4 rubric.
   - The prerequisite gate is "solid".
   - Scheduling uses the `fsrs` package instead of a hand-rolled algorithm.
   - Explain why this beats "watch a video, click next" (the Udemy model): retrieval practice and transfer questions, not completion clicks.
   - Honest gaps: the mastery constants are initial guesses until we have outcome data, and "learner type" is a format preference, not a learning-efficacy claim.
7. **Prototypes run sandboxed:** LLM-generated HTML/JS only renders in a sandboxed iframe (`srcdoc`, scripts allowed, no same-origin). Explain why it's never injected into the app's DOM.

## 5. Skill contracts

| Skill → call | Input | Output (Pydantic) |
|---|---|---|
| `diagnose` → `probe` | config, mission | `{questions[3–4]{id, prompt, targets_concept, level}}` at the claimed level |
| `diagnose` → `assess` | config, mission, probe Q&A | `{assessed_level, claimed_level, confidence 0–1, evidence[], gaps[], adjustment_message?}` (a message is required when assessed ≠ claimed) |
| `map-concepts` | config, mission, assessment, org_docs? | `{concepts[{id, title, mastery_statement, objective_level, prereqs[], est_minutes, concept_type, cites?[]}], sequence[], sequence_rationale}`. Validate in code: unknown prereqs, cycles, total time vs. target (±15%). Re-ask once with the errors. |
| `teach-concept` | concept, mission (analogy domain), format prefs, assessment, misconceptions?, org_docs? | `{explanation_md, example_md, diagram_mermaid, citations[{doc, section}]}`, streamed. `prototype_html` is P1+ (`build-prototype`). |
| `design-assessment` | concept, lesson, logged misconceptions | `{questions[4]{type: mcq \| short, prompt, options?[{text, misconception?}], answer, transfer_situation, objective_level, rubric?}], explain_item?}` |
| `grade` | question, rubric, answer | `{score_1_4, feedback, misconception?}`. A 4 requires transfer. |
| `remediate` → `explain_change` | rule outcome, score, misconceptions, plan diff | `{why, remediation_concept?{title, mastery_statement, angle, targets_misconception}}` |
| `remediate` → `prereq_warning` | locked concept, unmet prereqs | `{what_will_break}` |
| `ground-in-sources` | composed into the others for org courses | citation and "not in your docs" rules (spec §5) |

Intake defaults can be static in P1; a `suggest-defaults` call is optional.

**Shared system prompt:** every skill inherits the instructor conduct rules in spec §7.

**Deterministic logic lives in code, not skills:** `backend/agent/pedagogy.py` holds scoring, the multiple-choice mapping, the combination rule, mastery and bands, the unlock gate, adaptation rules, and `fsrs` integration (spec §4.7–4.10), all with unit tests. Verify the current `fsrs` API and license before using it.

**Grounding rule (J3):** the system prompt must require a citation for every factual claim drawn from org docs, and require saying "This isn't covered in your docs" rather than guessing.

## 6. Mini eval harness (CP5)

`make evals` runs every product skill's `evals/` cases plus the cross-cutting checks below, and prints a small table. Keep it small and honest.
1. **Diagnosis accuracy:** 4 scripted learner personas with canned probe answers, including one who **claims intermediate but answers like a novice**. Does `assess` land within one level of the expected answer, and does it produce an adjustment message for the over-claimer? Run each 3× and report consistency.
2. **Concept map constraints (deterministic):** for 3 configs, is the prereq graph valid (no unknown prereqs, no cycles), does total time land within ±15% of target, and does every concept have a mastery statement?
3. **Pedagogy rules (deterministic, unit tests):** scores 1 / 2 / 3 / 4 fire the right adaptation branch; the multiple-choice mapping and the lower-of-two combination rule behave per spec §4.7; mastery and bands match spec §4.9; the unlock gate holds dependents until prereqs are solid; the rating map into `fsrs` is correct.
4. **Grader calibration against human labels:** A human hand-labels about 8 short answers on the 1–4 rubric, including fluent restatements that should *not* get a 4. Report agreement with the human labels and consistency over 3 runs. This partly closes the "unvalidated judge" gap.
5. **Grounding (LLM-as-judge):** for 2 J3 lessons, does every cited section exist in the docs, and does the judge find any uncited claims? Note in `decisions.md` that the judge itself is unvalidated against human labels. That's the honest gap.
6. **Semantic cache correctness:** a small labeled set of request pairs.
   - ~6 **should-hit** pairs (paraphrases, e.g. "Intro to Kubernetes pods" / "Kubernetes pod basics")
   - ~6 **should-miss near-misses** (e.g. "liveness probes" / "readiness probes", "connection pool exhaustion" / "thread pool exhaustion", same topic at a different level)

   Report the hit rate and **false-hit rate** at 3 distance thresholds, and pick the default threshold from the results. It's the same correctness-vs-cost tradeoff as an AI agent deciding when it's confident enough to answer.

## 7. Seed and sample data

- **Org:** "Acme AI" (fictional). Write 4 short, realistic internal docs:
  1. On-call runbook
  2. Service map: `inference-gateway`, `model-router`, Postgres, Redis, Kafka, on Kubernetes
  3. A postmortem: connection-pool exhaustion in `model-router` causing inference 5xx during a traffic spike
  4. Escalation policy
- **Users:** `kyle` (individual learner), `dana` (new backend engineer at Acme AI, learner), `priya` (Acme AI eng manager, org admin).
- **Pre-seeded learner state, so a fresh install shows a course mid-flight without waiting on the LLM:**
  - kyle: "Incident investigation fundamentals for on-call engineers", about 40% complete, with plan v1 → v2 history already present. It has a mix of mastery bands (two solid, one shaky with a logged misconception such as "thinks a liveness-probe failure removes the pod from the load balancer", one locked behind it, one due for review).
  - kyle: one completed course with a badge
  - dana: an assigned Acme AI org course
- **One seeded interactive prototype** (spec §4.5 bar: the learner can change something and be surprised): a **connection-pool exhaustion simulator** for the Acme AI postmortem concept. It has sliders for request rate, pool size, and query latency, plus live counters for queue wait, timeouts, and 5xx rate. The surprise: the system looks fine until utilization crosses a threshold, then latency explodes. Build it once during development, check it by hand, and store it as the concept's `prototype_html`.
- `make seed`, `make warm-cache` (pre-generate and cache lessons for the seeded courses), `make reset`.

## 8. Project docs (in `docs/`)

- `architecture.md`: Mermaid component diagram, plus a sequence diagram for J2 (open concept → unlock check → cache check → LLM stream → quiz → grade 1–4 → FSRS update → rules → plan v2).
- `decisions.md`: short ADR-style entries for every non-obvious choice.
- `walkthrough.md`: exact click path for J1–J3, including which seeded user to use and the "bad quiz" answers to give.
- `ai-workflow.md`: how this was built with AI tooling (Claude Code, plan mode, CLAUDE.md, skills), key prompts, where the AI got it wrong, and what we'd do differently. Drafted from `BUILD_LOG.md`.
- `overview.md`: a one-page overview: problem, the three journeys, architecture, key tradeoffs, known gaps.
- `BUILD_LOG.md` (ongoing) and `README.md` (one-command setup) at the repo root.
