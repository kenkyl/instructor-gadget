# Architecture changelog

Changes to the architecture model, newest first. Written by `viz.py update`. The version each entry replaced is kept under [archive/](archive/).

## 2026-10-12 · `dd0d0ce` → `104e5af`

Refreshed from the CP1 snapshot to v0.1.0: added pedagogy rules, the two-tier LLM cache, grounding and the intake guard as modules; Redis now holds the dashboard, both LLM cache tiers and the guard index; added the lesson and quiz-grading flows. README embed turned off pending a decision.

**System**

- Changed `summary`: reworded; `highlights`: added Skills do language; code does decisions: scoring, mastery, gating, adaptation and FSRS are pure functions in agent/pedagogy.py., diagnose, grade and remediate are never cached, and neither is any request that carries a learner's misconceptions., ANTHROPIC_API_KEY is read by the API process only, and both data stores bind to 127.0.0.1.; removed The browser only talks to Next.js, which proxies /api/* to FastAPI, so the session cookie stays same-origin., ANTHROPIC_API_KEY lives in .env and is read by the API process only; the browser never sees it., Both data stores bind to 127.0.0.1, so they are not exposed on the network.

**Components**

- Added **Pedagogy rules** (`pedagogy`): Decides scores, mastery, bands, the unlock gate, adaptation rules and review dates; no model involv…
- Added **LLM cache tiers** (`cache`): Serves a repeated or reworded request without a model call: exact key first, then a tag-filtered se…
- Added **Grounding** (`sources`): Splits org docs into anchored sections and checks every citation's section and verbatim quote.
- Added **Intake guard** (`guard`): Rejects crude, off-topic, dangerous and prompt-injection course requests before anything is stored…
- Changed **Learner** (`learner`): `responsibility`: Takes a course through the browser: intake, diagnostic, lessons and quizzes. → Takes a course through the browser: intake, diagnostic, lessons and quizzes; admins also manage org docs and courses.
- Changed **API** (`api`): `responsibility`: Authenticates the user, enforces ownership, runs services and routes skill calls to the agent. → Authenticates the user, enforces ownership and the unlock gate, and runs the services that call the agent.; `members`: added Routers (web surface), Services
- Changed **Agent package** (`agent`): `members`: added Skills; removed diagnose skill
- Changed **Postgres** (`postgres`): `responsibility`: Source of truth for users, courses, enrollments, assessments, progress and the LLM call log. → Source of truth for users, orgs, docs, courses, plans, progress, lessons, quizzes and the LLM call log.; `holds`: added {"data": "Orgs, users, courses, enrollments, plan versions, progress, lessons, quiz attempts, misconceptions", "lifetime": "Durable"}, {"data": "Org docs: immutable, sectioned, hashed", "lifetime": "Durable"}, {"data": "llm_calls: one row per model attempt", "lifetime": "Durable"}; removed {"data": "Orgs, users, courses, enrollments, assessments, plans, progress", "lifetime": "Durable"}, {"data": "llm_calls: one row per model request", "lifetime": "Durable"}
- Changed **Redis** (`redis`): `responsibility`: Holds login sessions and the dashboard cache; LLM response caches are planned for CP2/CP3. → Holds sessions, the dashboard cache and both LLM cache tiers; everything in it can be rebuilt.; `evidence`: added backend/agent/cache.py, backend/agent/semantic.py, backend/agent/guard.py; `holds`: added {"data": "Exact LLM cache (llm:exact:{sha256}, JSON)", "lifetime": "7 day TTL"}, {"data": "Semantic LLM cache (idx:llm_semantic, vector index)", "lifetime": "7 day TTL per entry"}, {"data": "Intake guard routes (idx:intake_guard, vector index)", "lifetime": "Rebuilt at startup"}
- Changed **Anthropic API** (`anthropic`): `responsibility`: Generates structured diagnostic, lesson and grading output for the skills. → Generates structured probe, map, lesson, quiz, grading and re-plan output for the skills.

**Edges**

- Added `api` → `pedagogy` (sync): scores, gates, adapts
- Added `api` → `guard` (sync): screens new courses
- Added `agent` → `cache` (sync): lookup, then store
- Added `agent` → `sources` (sync): grounds and checks
- Added `cache` → `redis` (sync): exact + vector entries
- Added `guard` → `redis` (sync): route vectors

**Flows**

- Added **Open a concept's lesson** (`open-lesson`): 11 steps
- Added **Grade a quiz and adapt the plan** (`submit-quiz`): 10 steps
- Changed **Generate diagnostic questions** (`course-probe`): `description`: After a learner creates a course, the API asks the diagnose skill for probe questions and stores them. → After a learner creates a course, the API asks the diagnose skill for probe questions and stores them. Diagnose is never cached.

**Notes**

- Added added 2026-10-12: output to docs/architecture; keep consistent with docs/architecture.md (current hand-written doc);…

Previous version: [archive/2026-10-11-dd0d0ce/](archive/2026-10-11-dd0d0ce/)
