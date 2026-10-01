ROOT := $(abspath .)
API := $(ROOT)/apps/api
WEB := $(ROOT)/apps/web

.PHONY: install infra migrate seed api worker web generate check test-db integration e2e acceptance
install:
	uv sync --frozen --project "$(API)"
	pnpm --dir "$(WEB)" install --frozen-lockfile
infra:
	docker compose -p mianshiya-learning -f "$(ROOT)/infra/compose.yaml" up -d
migrate:
	cd "$(API)" && uv run --frozen alembic upgrade head
seed:
	cd "$(API)" && uv run --frozen python -m mianshiya.cli seed
api:
	cd "$(API)" && uv run --frozen uvicorn mianshiya.main:app --host 127.0.0.1 --port 18000 --no-access-log --no-proxy-headers
worker:
	cd "$(API)" && uv run --frozen python -m mianshiya.search
web:
	pnpm --dir "$(WEB)" run dev --port 33017
generate:
	cd "$(API)" && uv run --frozen python -m mianshiya.cli openapi "$(ROOT)/packages/api-client/openapi.json"
	pnpm --dir "$(WEB)" run generate
check:
	uv run --frozen --project "$(API)" ruff check "$(API)/mianshiya" "$(API)/tests" "$(ROOT)/scripts"
	uv run --frozen --project "$(API)" ruff format --check "$(API)/mianshiya" "$(API)/tests" "$(ROOT)/scripts"
	python3 "$(ROOT)/scripts/test_fixture_lock.py"
	python3 "$(ROOT)/docs/plans/2026-10-01-full-rebuild/check_plan.py"
	uv run --frozen --project "$(API)" python "$(ROOT)/scripts/check_contract.py"
	pnpm --dir "$(WEB)" run typecheck
	pnpm --dir "$(WEB)" run format:check
test-db:
	uv run --frozen --project "$(API)" python "$(ROOT)/scripts/prepare_test_db.py"
integration:
	cd "$(API)" && uv run --frozen pytest -q --tb=no
e2e:
	pnpm --dir "$(WEB)" exec playwright test
acceptance:
	python3 "$(ROOT)/scripts/acceptance.py" --step "$(STEP)"
