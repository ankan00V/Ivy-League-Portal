service ?= backend
PYTHON ?= backend/venv/bin/python
BACKEND_PYTHON ?= venv/bin/python

.PHONY: up down logs dev dev-api dev-web local-prod local-prod-stop smoke-local validate-env ai-provider-check slim-up slim-down doctor seed train test frontend-lint frontend-build startup-check warehouse-refresh ds-gates recommendation-quality-gate assistant-eval weekly-ds-scorecard infra-check backup-restore-drill release-contracts bootstrap-demo-data bootstrap-opportunities seed-test-data validate-data-health dataset-snapshot

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f $(service)

dev:
	slim up

dev-api:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	cd frontend && npm run dev -- --hostname 0.0.0.0 --port 3000

local-prod:
	./scripts/start_local_production.sh

local-prod-stop:
	./scripts/stop_local_production.sh

smoke-local:
	python3 scripts/smoke_test_local.py

validate-env:
	cd backend && venv/bin/python scripts/validate_env.py

ai-provider-check:
	cd backend && venv/bin/python scripts/check_ai_provider.py

slim-up:
	slim start web --port 3000
	slim start api --port 8000

slim-down:
	slim down

doctor:
	slim doctor

seed:
	cd backend && $(BACKEND_PYTHON) scripts/bootstrap_company_seeds.py
	cd backend && $(BACKEND_PYTHON) scripts/bootstrap_ranking_pipeline.py --min-users 20 --days 14

bootstrap-demo-data:
	$(PYTHON) backend/scripts/bootstrap_demo_data.py --refresh-existing

bootstrap-opportunities:
	$(PYTHON) backend/scripts/bootstrap_opportunities.py --sources=all --max-per-source=200

seed-test-data:
	$(PYTHON) backend/scripts/seed_test_data.py --users 20 --employers 5

validate-data-health:
	$(PYTHON) backend/scripts/validate_data_health.py

dataset-snapshot:
	$(PYTHON) backend/scripts/export_dataset_snapshot.py

train:
	cd backend && $(BACKEND_PYTHON) scripts/train_learned_ranker.py --output models/learned_ranker.lgb.txt

test:
	cd backend && $(BACKEND_PYTHON) -m pytest -q tests

release-contracts:
	$(PYTHON) backend/scripts/check_release_contracts.py

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

startup-check:
	./scripts/startup_check.sh

warehouse-refresh:
	cd backend && $(BACKEND_PYTHON) scripts/rebuild_analytics_warehouse.py --lookback-days 30 --traffic-type real
	cd backend && $(BACKEND_PYTHON) scripts/check_warehouse_release_gate.py --json

ds-gates:
	cd backend && $(BACKEND_PYTHON) scripts/check_ds_release_gates.py --fail-on-not-ready

recommendation-quality-gate:
	cd backend && $(BACKEND_PYTHON) scripts/check_recommendation_quality_gate.py --ranking-mode semantic --fail-on-not-ready

assistant-eval:
	cd backend && $(BACKEND_PYTHON) benchmarks/run_assistant_quality_eval.py --fail-on-regression

weekly-ds-scorecard:
	cd backend && $(BACKEND_PYTHON) scripts/publish_weekly_ds_scorecard.py

infra-check:
	cd backend && $(BACKEND_PYTHON) scripts/check_production_infra_readiness.py --include-bi

backup-restore-drill:
	cd backend && $(BACKEND_PYTHON) scripts/test_backup_restore_drill.py --execute
