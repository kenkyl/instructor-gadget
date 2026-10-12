.DEFAULT_GOAL := help
.PHONY: help install models up down nuke doctor logs psql redis-cli migrate migration seed api web dev test eval-cache lint fmt types

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------
install: ## Install backend (uv) and web (npm) dependencies, and download the embedding model
	cd backend && uv sync
	cd web && npm install
	$(MAKE) models

models: ## Download the local embedding model (MiniLM, ~90 MB) used by the semantic cache
	cd backend && uv run python -c "from agent.semantic import MODEL; from sentence_transformers import SentenceTransformer; SentenceTransformer(MODEL); print('model ready:', MODEL)"

# --- data stores (Docker) ----------------------------------------------------
up: ## Start Postgres + Redis and wait until healthy
	docker compose up -d --wait

down: ## Stop the data stores (data is kept)
	docker compose down

nuke: ## Stop the data stores AND delete their data volumes
	docker compose down -v

doctor: ## Check that the local stack is healthy
	@./scripts/doctor.sh

logs: ## Tail data-store logs
	docker compose logs -f

psql: ## Open a Postgres shell
	docker compose exec postgres psql -U instructor -d instructor

redis-cli: ## Open a Redis shell
	docker compose exec redis redis-cli

# --- database ----------------------------------------------------------------
migrate: ## Apply Alembic migrations to the dev DB
	cd backend && uv run alembic upgrade head

migration: ## Autogenerate a migration from model changes: make migration m="add foo"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

seed: ## Seed the sample org and users (idempotent)
	cd backend && uv run python -m seed.seed

# --- app processes (native, hot reload) --------------------------------------
api: ## Run FastAPI on :8000; reloads on .py AND skill prompt (.md/.yaml) edits
	cd backend && uv run uvicorn app.main:app --port 8000 --reload --reload-include '*.md' --reload-include '*.yaml'

web: ## Run Next.js on :3000
	cd web && npm run dev

dev: ## Run api + web together (Ctrl-C stops both)
	@trap 'kill 0' INT TERM EXIT; $(MAKE) api & $(MAKE) web & wait

# --- quality -----------------------------------------------------------------
test: ## Backend tests against a throwaway instructor_test DB (needs `make up`)
	cd backend && uv run pytest -q

eval-cache: ## Semantic-cache threshold sweep + intake-guard re-check on the real MiniLM model (needs `make up`)
	cd backend && uv run python -m evals.cache_eval

lint: ## ruff + pyright + eslint + tsc
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
	cd web && npm run lint && npm run typecheck

fmt: ## Auto-format backend
	cd backend && uv run ruff format . && uv run ruff check --fix .

types: ## Regenerate web/src/lib/api-types.ts from FastAPI's OpenAPI schema
	cd backend && uv run python -m app.export_openapi > ../web/openapi.json
	cd web && npx openapi-typescript openapi.json -o src/lib/api-types.ts
