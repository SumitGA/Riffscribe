# Developer shortcuts. Run `make` (or `make help`) to list targets.

.DEFAULT_GOAL := help
.PHONY: help setup setup-separation run view up down migrate api worker token check lint fmt typecheck test test-accuracy test-separation rust clean

PIPELINE_DIR := packages/pipeline
FILE ?=
INSTRUMENT ?= guitar
OUT ?= out
ARGS ?=
# make doesn't expand a leading ~ (and zsh doesn't after FILE=), so do it here.
FILE_PATH = $(patsubst ~/%,$(HOME)/%,$(FILE))
OUT_PATH = $(patsubst ~/%,$(HOME)/%,$(OUT))
LOCAL_DATABASE_URL ?= postgresql+psycopg://tabscribe:tabscribe@localhost:5433/tabscribe
# Local dev auth (TD-17). Throwaway values, like the dev credentials in docker-compose.yml.
LOCAL_JWT_ISSUER ?= http://localhost/dev-issuer
LOCAL_JWT_DEV_SECRET ?= tabscribe-local-dev-only-not-a-real-secret
TTL ?= 3600
# Everything the API and worker read, pointing at the `make up` services (dev values only).
LOCAL_ENV = DATABASE_URL=$(LOCAL_DATABASE_URL) REDIS_URL=redis://localhost:6379/0 \
	S3_BUCKET=tabscribe S3_ENDPOINT_URL=http://localhost:8333 S3_REGION=us-east-1 \
	AWS_ACCESS_KEY_ID=dev-access-key AWS_SECRET_ACCESS_KEY=dev-secret-key \
	JWT_ISSUER=$(LOCAL_JWT_ISSUER) JWT_DEV_SECRET=$(LOCAL_JWT_DEV_SECRET)

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install dependencies and build the Rust extension
	uv sync

setup-separation: ## Also install optional Demucs source separation (~630 MB, torch)
	uv sync --group separation

run: ## Transcribe FILE=<audio> [INSTRUMENT=guitar|piano] [OUT=out] [ARGS="--force"]
	@test -n "$(FILE)" || { echo 'usage: make run FILE=path/to/audio.m4a [INSTRUMENT=piano] [ARGS="--force"]'; exit 1; }
	uv run python -m pipeline transcribe "$(FILE_PATH)" --out "$(OUT_PATH)" --instrument $(INSTRUMENT) $(ARGS)

view: ## Preview OUT (default out/) as notation + tab with playback, in the browser
	uv run python tools/preview/serve.py --out "$(OUT_PATH)"

up: ## Start local Postgres, Redis (Valkey) and S3 (SeaweedFS) in Docker
	docker compose up -d --wait

down: ## Stop the local services (data is kept; `docker compose down -v` wipes it)
	docker compose down

migrate: ## Apply database migrations to the local Postgres
	DATABASE_URL=$(LOCAL_DATABASE_URL) uv run alembic -c packages/platform/alembic.ini upgrade head

api: ## Run the API on http://localhost:8000 against the local services (reloads on change)
	$(LOCAL_ENV) uv run uvicorn api.main:app --reload --port 8000

worker: ## Run a worker (both queues) against the local services
	$(LOCAL_ENV) uv run python -m worker

token: ## Print a local dev access token: make token [USER=alice] [TTL=3600]
	@JWT_ISSUER=$(LOCAL_JWT_ISSUER) JWT_DEV_SECRET=$(LOCAL_JWT_DEV_SECRET) \
		uv run --quiet python -m api.devtoken "$(USER)" --ttl $(TTL)

check: lint typecheck test rust ## Run everything CI runs

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-fix lint issues and format Python and Rust
	uv run ruff check . --fix
	uv run ruff format .
	cd $(PIPELINE_DIR) && cargo fmt

typecheck: ## mypy --strict
	uv run mypy

test: ## Fast tests (skips the accuracy suite)
	uv run pytest

test-accuracy: ## Accuracy suite (mir_eval vs annotated clips); prints a table
	uv run pytest -m accuracy -s -q

test-separation: ## Demucs tests (needs make setup-separation)
	uv run --group separation pytest -m separation

rust: ## cargo fmt check, clippy and cargo test
	cd $(PIPELINE_DIR) && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

clean: ## Remove caches, Rust build output and the output dir (OUT=out)
	rm -rf "$(OUT_PATH)" .mypy_cache .ruff_cache .pytest_cache $(PIPELINE_DIR)/target
