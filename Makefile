.PHONY: install dev backend frontend test test-backend test-frontend lint lint-backend lint-frontend typecheck format check build

install:
	cd backend && uv sync
	cd frontend && npm ci

dev:
	cd frontend && node scripts/dev.mjs

backend:
	cd backend && uv run uvicorn cyber_interview.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .

lint-frontend:
	cd frontend && npm run lint

typecheck:
	cd frontend && npm run typecheck

format:
	cd backend && uv run ruff check . --fix
	cd backend && uv run ruff format .
	cd frontend && npm run lint -- --fix

build:
	cd frontend && npm run build
	cd backend && uv build

check: lint typecheck test build

