.PHONY: up down dev dev-api dev-web slim-up slim-down doctor ds-gates assistant-eval weekly-ds-scorecard

up:
	docker compose up -d mongo redis

down:
	docker compose down

dev:
	slim up

dev-api:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	cd frontend && npm run dev -- --hostname 0.0.0.0 --port 3000

slim-up:
	slim start web --port 3000
	slim start api --port 8000

slim-down:
	slim down

doctor:
	slim doctor

ds-gates:
	cd backend && python3 scripts/check_ds_release_gates.py --fail-on-not-ready

assistant-eval:
	cd backend && python3 benchmarks/run_assistant_quality_eval.py --fail-on-regression

weekly-ds-scorecard:
	cd backend && python3 scripts/publish_weekly_ds_scorecard.py
