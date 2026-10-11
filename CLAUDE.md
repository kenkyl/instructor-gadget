# CLAUDE.md

Instructor is an adaptive learning-course agent. It diagnoses where a learner really is, maps concepts and prerequisites, teaches one concept at a time with zero-hint quizzes, and re-plans from graded evidence. Org courses are grounded in internal docs.

## Source-of-truth docs
- `docs/learning-design.md`: **how it teaches**. Pedagogy rules win; any change goes in an ADR.
- `docs/build-brief.md`: what to build in Phase 1.
- `docs/roadmap.md`: the full vision. Build Phase 1 only, but design for everything listed there.
- `docs/decisions.md`: ADRs. Add one (with the `adr` skill) for every non-obvious choice.
- The approved implementation plan (pair-checkpoint sequence) is summarized in `BUILD_LOG.md`.

## Working agreement (pair programming)
Kyle wants a deep working understanding of every component, so understanding matters as much as working code.
- Work in small **pair checkpoints (PC)**. At the end of each PC, post: **Built** / **Architecture now** (a Mermaid diagram if it changed) / **Your turn** (a targeted task against a pre-written test) / **Verify** (exact commands or clicks + expected result) / **Check** (2–3 questions) / **Next**. Then wait for "go".
- Keep instructions short and imperative, and say why. Ask clarifying questions instead of guessing.
- Use current best practice: check library APIs against current docs (the `claude-api` skill for Anthropic, plus the RedisVL and fsrs docs) before writing integration code.
- Commit and push at the end of each PC, using Conventional Commits.

## Hard rules
- **Public repo.** Never commit `docs/private/` (personal planning material) or anything that isn't about the product and how it's built. Before every push, run the privacy scan in the `checkpoint` skill.
- **No secrets in code.** Use `.env` (gitignored); `.env.example` is committed.
- **Skills do language; code does decisions.** Scoring, mastery, gating, adaptation and FSRS live in `backend/agent/pedagogy.py`, with unit tests.
- **Every LLM call goes through the client wrapper**: structured output validated by Pydantic, one retry with the error, then logged to `llm_calls`.
- **Never cache** `diagnose`, `grade`, `remediate`, or any request that includes the learner's misconceptions (ADR-0007).
- LLM-generated HTML only ever renders in a sandboxed iframe (`srcdoc`, `sandbox="allow-scripts"`, no same-origin).
- Only add dependencies beyond the approved list after asking Kyle.
- License: PolyForm Noncommercial 1.0.0. Don't add code copied from incompatible sources.

## Architecture (summary)
- `web/`: Next.js App Router + TS + Tailwind + shadcn/ui. `/api/*` is rewritten to FastAPI.
- `backend/app/`: FastAPI routers (the web surface adapter), surface-neutral services, SQLAlchemy async models, Alembic migrations, and auth via `get_current_user`.
- `backend/agent/`: an in-process package containing:
  - `lifecycle` (the state machine)
  - `registry` (product skills)
  - `llm` (the client wrapper)
  - `cache` (exact + RedisVL semantic tiers)
  - `pedagogy` (deterministic rules)
  - `plan` (DAG validation and diff)
  - `sources` (grounding)
- `backend/agent/skills/<name>/`: `SKILL.md`, `calls/<call>.md`, `schema.py`, `references/`, `evals/`.
- **Postgres 16** is the source of truth.
- **Redis 8** holds sessions, the dashboard cache-aside, the exact LLM cache, and the semantic LLM cache (vector index + tag filters).
- **Anthropic API** (`ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) is the only external dependency. Embeddings run locally (MiniLM).

## Commands
Filled in as they come to exist (PC0.2+).
| Command | What it does |
|---|---|
| `docker compose up -d` | Start Postgres + Redis |

## Conventions
- Python 3.12 with uv; ruff for lint and format; pytest; type hints everywhere; Pydantic v2 models at every boundary.
- TypeScript strict; generated API types live in `web/lib/api-types.ts` (never hand-edit).
- Prompts live in skill folders, never inline in Python.
