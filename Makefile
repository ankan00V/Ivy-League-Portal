.PHONY: up down dev dev-api dev-web slim-up slim-down doctor

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
