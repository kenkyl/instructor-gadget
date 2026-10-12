# Roadmap: full product vision

Only Phase 1 is being built; everything here is designed for. Keep this current as items move between phases.

Phase tags: **[P1]** MVP · **[P1+]** only if time allows after CP6 · **[P2]** next · **[P3]** later · **[Explore]** an open idea to evaluate. Items marked *(suggested)* are additions from planning, not the original notes.

## Phase 1 extensibility hooks (cheap to do now, expensive to retrofit)
- **Course config is a JSONB blob validated by a Pydantic model,** so new knobs don't require migrations. The learner-style values form an extensible enum.
- **Course scope** is `owner_user_id` or `org_id` from day one, so per-user and org courses share one model.
- **Plan versions carry a `trigger`.** `user_request` exists in the enum now even though chat ships in P2.
- **Each agent stage is a product skill** (§5.1) loaded through one registry (name → SKILL.md, schema, evals). The P2 chat agent can then call the same skills as tools, and course-type and org-authored skills plug in without code changes.
- **One LLM client wrapper** handles all model calls: model selection, structured output, retries, and logging to `llm_calls`. Swapping models or providers touches one file.
- **Auth sits behind a single `get_current_user` dependency,** so swapping seeded-user login for Google OAuth is a local change.
- **Delivery surfaces are an interface:** `surfaces/web` now, with `surfaces/claude_code` and others later. Lessons and exercises are stored as surface-neutral content, and each surface renders them.
- **A content source abstraction for grounding:** `org_docs` now. Later sources (uploaded files, Google Drive, GitHub repos, wikis) plug into the same interface.

## Instructor agent
| Idea | Phase |
|---|---|
| Takes the learner's inputs (what they want to learn plus config) and asks clarifying and level-set questions | P1 |
| Level-set to gauge current skill (spec §4.1–4.3): one-round intake with recommended answers, then 3–4 probe questions at the claimed level, with a transparent adjustment when evidence and claim disagree | P1 |
| Per-learner diagnostic probe for **org courses** that personalizes the learner's copy of the admin's template plan *(added in planning; ADR-0004)* | P1+ |
| Builds a course plan as a **concept map with prerequisites and mastery statements**; the learner reviews, cuts, and accepts it | P1 (cut) → P1+ (reorder) |
| Builds the course content just-in-time per concept: explanation (counterintuitive part first, learner's analogy domain), example, diagram, prototype, quiz | P1 |
| Interactive **prototypes** per concept (simulators the learner can break; spec §4.5 bar) | P1 (one seeded, sandboxed) → P1+ (live generation) → P2 (prototype types per concept kind: algorithm step-through, systems simulator, math sliders, syntax editor, fake API) |
| **Zero-hint, transfer-based quizzing** with misconception-based distractors; 1–4 rubric | P1 |
| **Misconception tracking:** name it, log it, re-attack it from new angles in later quizzes until it's resolved | P1 (log + feed into distractors) → P2 (resolution tracking, cross-course) |
| **Mastery only from graded retrieval;** prerequisite gate at "solid"; skip-ahead override with an explicit warning | P1 |
| **Spaced repetition** (`fsrs` package): due dates per concept | P1 (computed; "N due" on dashboard) → P2 (review sessions: due reviews first, then one new concept, then a transfer question linking new to old) |
| Session close: "what's due next and when", plus a session log | P2 |
| Per-course **glossary** that grows as the instructor teaches | P2 |
| "Never mark mastered from 'I understand'": the instructor asks the learner to apply the idea instead | P1 (system prompt rule) |
| Ongoing feedback loop through each stage: moves faster through concepts the learner excels at, spends more time where they struggle | P1 (rules-based quiz adaptation) → P2 (richer signals: time on task, exercise results, self-reported confidence) |
| Adjusts the course as prompted by the learner | P2 |
| "Chat with your instructor" at any time to change the course: add a topic, shorten the course, go deeper, change style. Tool-using agent with `get_course_state`, `propose_plan_change` (writes a plan version with `trigger=user_request` after confirmation), and `explain_concept` | P2 (P1+ if time) |
| Recommendations for continued learning **within the active course**: YouTube videos, blogs, tutorials, documentation, workbooks. Each has a one-line note on why it's worth the learner's time. | P2 |
| Recommendations **at the user and/or org level**, based on all courses | P2 |
| Recommends **new courses** for the instructor to build for the user (or org) | P2 |
| All recommendation links come from a real web search tool, never model-invented URLs *(suggested; this guardrail is required)* | P2 |
| **Instructor skills architecture:** every teaching ability is a product skill folder (spec §10) | P1 |
| Course-type playbook skills: cert-prep, onboarding, interview-prep, customer-prep, new-domain (spec §8) | P2 |
| Org-authored custom skills (e.g. "how we teach our runbooks") | P3 |
| Faded worked examples → independent practice; interleaved reviews; confidence calibration (spec §2) | P2 |
| **Cross-course learner model:** shared concept identity, so mastery proven in one course skips that concept in another (spec §3; Redis vector match) | P2 |
| Source-gap report for org admins: questions the docs couldn't answer (spec §5) | P2 |

## Course configuration knobs
| Knob | Phase |
|---|---|
| Course length (estimated hours to complete) | P1 |
| Difficulty / target level | P1 |
| Current level (novice, intermediate, strong, expert, …), confirmed or adjusted by the diagnostic probe | P1 |
| What "expert" means to the learner for this topic | P1 |
| Mode: cram (deadline soon) vs. foundation (long-term), plus a deadline | P1 |
| Analogy domain / interests for personalized explanations | P1 |
| Learner type: **reading, quizzes/tests, hands-on building** | P1 |
| Learner type: **visual, writing, audio**, and others | P2/P3 (accepted and stored in P1, labeled "coming soon") |
| Additional tunable knobs added over time (JSONB config makes this cheap) | P2+ |

## Users, orgs, and auth
| Idea | Phase |
|---|---|
| Per-user courses | P1 |
| Org-level courses, assigned to members | P1 |
| Learner works on 1–N courses at a time | P1 |
| Login (seeded users, session in Redis) | P1 |
| **Federated social login with a Google account.** The original idea was to do this through **Arcade**. Arcade's focus is authorizing an agent's tool calls on a user's behalf rather than app sign-in, so evaluate Arcade vs. Auth.js/NextAuth (Google provider) and recommend one. | P2 |
| Org admin features: assignment, team progress, completion and score by concept | P1 (assignment) → P2 (analytics) |

## Content, grounding, and custom context
| Idea | Phase |
|---|---|
| Any topic, technical or non-technical (Phase 1 sample content is technical) | P1 (no topic restrictions) |
| Org custom context: internal documentation, processes, playbooks | P1 (context stuffing of small docs) → P2 (RAG with Redis vector search for large doc sets) |
| **Outside knowledge in org courses:** best practices, supplementary context and a few general-basis concepts alongside the docs, always labelled and never overriding them *(added after CP4; designed in `docs/build-plan.md` P1+ 1)* | P1+ |
| Web-search-backed supplementary facts for org courses *(needs a cost/latency decision and a structured-output compatibility check)* | Explore |
| Additional context sources: Google Drive, GitHub repos, wikis *(suggested; candidates for Arcade-delegated access)* | Explore |
| Use-case templates: certification/test prep, technical onboarding, GTM new-hire training, interview prep, meeting prep, learning about a customer, learning a new domain | P2 |

## UI
| Idea | Phase |
|---|---|
| Login page | P1 |
| Dashboard of courses (active with progress and mastery bands per concept, completed, "N due for review") | P1 |
| Completion certification badges | P1 |
| Instructor trace page (LLM calls, tokens, latency, cost) *(suggested)* | P1 |
| Plan version diff with the "why" | P1 |
| Instructor chat panel | P2 |
| Recommendations panel (course-level and user/org-level) | P2 |

## Training surfaces
| Idea | Phase |
|---|---|
| HTML/web-app frontend (default surface) | P1 |
| **Claude Code** as a learning surface for coding/dev courses: **our own `instructor` Claude Code skill plus an MCP server** exposing course state, lessons, quizzes, and exercise review from the Instructor backend | P3 |
| **Thin MCP surface** *(added in planning)*: an MCP server over the same surface-neutral services, with tools such as `next_concept`, `get_lesson`, `submit_quiz`, so a learner can study from Claude Code. Uses the official `mcp` Python SDK | P1+ (after CP6) → P3 (full Claude Code surface above) |
| Extensible interface for **other agentic dev tools** (Cursor, Codex, etc.), with Claude Code first | P3 |
| **GitHub repo per learner/course:** the instructor creates a training repo (exercises, starter code, `CLAUDE.md`), then reviews, pairs, and works with the learner in it. GitHub access delegated via **Arcade**. | P3 |
| Built-in code runtime for hands-on concepts | P3 / Explore |
| **Portable lessons:** export any lesson as a self-contained HTML file that still works offline months later | P2 |
| Jupyter or other notebooks for hands-on concepts | P3 / Explore |

## Data, performance, and real-time
| Idea | Phase |
|---|---|
| Course history and all durable state in Postgres (or another OSS SQL option) | P1 |
| Redis OSS as session store | P1 |
| Redis caching of user data at and after login for performance | P1 |
| Redis two-tier LLM cache (exact + semantic via RedisVL) for lessons and quizzes, with cache results in the trace | P1 |
| Semantic cache for instructor chat (`explain_concept`) | P2 |
| Redis as the vector store for org-doc RAG, replacing context stuffing for large doc sets | P2 |
| Redis-backed agent memory: short-term conversation state and a long-term learner profile across courses *(suggested)* | P2 / Explore |
| Streaming lesson generation to the browser (SSE) | P1 |
| Redis pub/sub or Redis Streams for real-time events once generation moves to background workers (e.g. progress events, multi-tab updates, org dashboards) | P3 |
| Background course generation workers | P3 |

## Architecture, infrastructure, and deployment
| Idea | Phase |
|---|---|
| Components: frontend, backend (login, data access), agent (Python; LLM interface; talks to the backend), Postgres, Redis | P1 (agent in-process as its own package) |
| Agent as a separate service | P2/P3, when there's a reason (independent scaling, background workers) |
| Containerized services with Docker: data stores in P1; `web` and `api` Dockerfiles plus a full compose profile | P1+ / P2 |
| Run locally for the MVP, except external components that are required (the Anthropic API) | P1 |
| Cloud hosting. First thought is Vercel (P1+ only if everything else is solid; localhost is fine for Phase 1); research the easiest option for this stack (e.g. Vercel for the frontend plus Render, Railway, or Fly for the API, with managed Postgres and Redis) and recommend one | P2 |
| Hand-rolled agent vs. LangGraph: hand-rolled for P1; revisit if the chat agent's orchestration grows complex | P1 decision, revisit in P2 |
| Language and framework choices based on current industry practice for building agents (see §5) | P1 decision |

## Quality and evals
| Idea | Phase |
|---|---|
| Mini eval harness: diagnosis accuracy (including the over-claimer), concept-map validity, adaptation and scheduling rules, grounding via LLM-as-judge, semantic cache false-hit rate | P1 (CP5) |
| Grader calibration against human hand-labeled 1–4 short answers | P1 (CP5) |
| Larger calibration sets for the grader and the grounding judge; retention outcomes (do "mastered" concepts survive their scheduled reviews?) to tune the mastery constants and FSRS parameters *(suggested)* | P2 |

## Claude Code skills for this build (create at CP0, in `.claude/skills/`)
- **`checkpoint`:** run smoke checks and `make evals` (when it exists), append a `BUILD_LOG.md` entry (what was built, key prompts/decisions, where the AI went wrong, tradeoffs), and commit with a clear message.
- **`new-instructor-skill`:** scaffold a product skill folder (`backend/agent/skills/<name>/` with `SKILL.md`, `schema.py`, `references/`, `evals/`) in the standard shape and register it. Use it for every product skill, so they all follow one pattern.
- **`reset-sample-data`** (✅ CP6): reset the DB, seed sample data, warm the caches (`make reset`, `make warm-cache`).

These are our own skills. Don't vendor or install any third-party skill into this repo. Also added: `adr` (append a numbered decision to `decisions.md`).
