.DEFAULT_GOAL := help
.PHONY: help up down nuke doctor logs psql redis-cli

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

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
