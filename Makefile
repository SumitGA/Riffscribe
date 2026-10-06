# Developer shortcuts. Run `make` (or `make help`) to list targets.

.DEFAULT_GOAL := help
.PHONY: help setup setup-separation run view up stack e2e down migrate api worker token api-types mobile mobile-ios mobile-android mobile-check check lint fmt typecheck test test-accuracy test-separation rust clean

PIPELINE_DIR := packages/pipeline
FILE ?=
INSTRUMENT ?= guitar
OUT ?= out
ARGS ?=
# make doesn't expand a leading ~ (and zsh doesn't after FILE=), so do it here.
FILE_PATH = $(patsubst ~/%,$(HOME)/%,$(FILE))
OUT_PATH = $(patsubst ~/%,$(HOME)/%,$(OUT))
LOCAL_DATABASE_URL ?= postgresql+psycopg://tabscribe:tabscribe@localhost:5433/tabscribe
MOBILE_DIR := apps/mobile
# A phone reaches the backend through this Mac's LAN address (e.g. HOST_IP=192.168.1.20); the
# iOS Simulator and Android Emulator don't need it. Set, it opens the API and S3 to the network.
HOST_IP ?=
PUBLIC_HOST = $(if $(HOST_IP),$(HOST_IP),localhost)
PUBLIC_BIND = $(if $(HOST_IP),0.0.0.0,127.0.0.1)
# Local dev auth (TD-17). Throwaway values, like the dev credentials in docker-compose.yml.
LOCAL_JWT_ISSUER ?= http://localhost/dev-issuer
LOCAL_JWT_DEV_SECRET ?= tabscribe-local-dev-only-not-a-real-secret
TTL ?= 3600
# Readable logs locally; `make worker LOG_FORMAT=json` shows what production logs.
LOG_FORMAT ?= text
# `make api CLERK_ISSUER=https://<instance>.clerk.accounts.dev` makes the API accept the app's
# Clerk sign-ins instead of dev tokens (one or the other; `make token` and e2e need dev tokens).
CLERK_ISSUER ?=
LOCAL_AUTH = $(if $(CLERK_ISSUER),JWT_ISSUER=$(CLERK_ISSUER) \
	JWT_JWKS_URL=$(CLERK_ISSUER)/.well-known/jwks.json,JWT_ISSUER=$(LOCAL_JWT_ISSUER) \
	JWT_DEV_SECRET=$(LOCAL_JWT_DEV_SECRET))
# Everything the API and worker read, pointing at the `make up` services (dev values only).
LOCAL_ENV = DATABASE_URL=$(LOCAL_DATABASE_URL) REDIS_URL=redis://localhost:6379/0 \
	S3_BUCKET=tabscribe S3_ENDPOINT_URL=http://localhost:8333 S3_REGION=us-east-1 \
	AWS_ACCESS_KEY_ID=dev-access-key AWS_SECRET_ACCESS_KEY=dev-secret-key \
	$(LOCAL_AUTH) LOG_FORMAT=$(LOG_FORMAT) $(if $(HOST_IP),S3_PUBLIC_ENDPOINT_URL=http://$(HOST_IP):8333)

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install dependencies (Python, Rust extension, mobile app)
	uv sync
	cd $(MOBILE_DIR) && npm ci

setup-separation: ## Also install optional Demucs source separation (~630 MB, torch)
	uv sync --group separation

run: ## Transcribe FILE=<audio> [INSTRUMENT=guitar|piano] [OUT=out] [ARGS="--force"]
	@test -n "$(FILE)" || { echo 'usage: make run FILE=path/to/audio.m4a [INSTRUMENT=piano] [ARGS="--force"]'; exit 1; }
	uv run python -m pipeline transcribe "$(FILE_PATH)" --out "$(OUT_PATH)" --instrument $(INSTRUMENT) $(ARGS)

view: ## Preview OUT (default out/) as notation + tab with playback, in the browser
	uv run python tools/preview/serve.py --out "$(OUT_PATH)"

up: ## Start local Postgres, Redis (Valkey) and S3 (SeaweedFS) in Docker
	PUBLIC_BIND=$(PUBLIC_BIND) docker compose up -d --wait
	docker compose run --rm seaweedfs-init

stack: ## Build and run the whole backend in Docker: API on :8000, a worker (needs ports free)
	$(MAKE) up
	docker compose run --rm migrate
	PUBLIC_HOST=$(PUBLIC_HOST) PUBLIC_BIND=$(PUBLIC_BIND) \
		docker compose --profile app up -d --wait --build api worker

e2e: ## End-to-end test against the running stack: upload, transcribe, download (`make stack` first)
	JWT_ISSUER=$(LOCAL_JWT_ISSUER) JWT_DEV_SECRET=$(LOCAL_JWT_DEV_SECRET) uv run python tools/e2e.py

down: ## Stop everything (data is kept; `docker compose down -v` wipes it)
	docker compose --profile app --profile init down

migrate: ## Apply database migrations to the local Postgres
	DATABASE_URL=$(LOCAL_DATABASE_URL) uv run alembic -c packages/platform/alembic.ini upgrade head

api: ## Run the API on :8000 against the local services, reloading [CLERK_ISSUER=... for app sign-in]
	$(LOCAL_ENV) uv run uvicorn api.main:app --reload --host $(PUBLIC_BIND) --port 8000

worker: ## Run a worker (both queues) against the local services
	$(LOCAL_ENV) uv run python -m worker

token: ## Print a local dev access token: make token [USER=alice] [TTL=3600]
	@JWT_ISSUER=$(LOCAL_JWT_ISSUER) JWT_DEV_SECRET=$(LOCAL_JWT_DEV_SECRET) \
		uv run --quiet python -m api.devtoken "$(USER)" --ttl $(TTL)

check: lint typecheck test rust mobile-check ## Run everything CI runs (except e2e)

mobile: ## Start the Expo dev server for the app's dev build [HOST_IP=<LAN IP> to use a phone]
	cd $(MOBILE_DIR) && $(if $(HOST_IP),EXPO_PUBLIC_API_URL=http://$(HOST_IP):8000) npx expo start

mobile-ios: ## Build the dev build and run it in the iOS Simulator (needs Xcode)
	cd $(MOBILE_DIR) && npx expo run:ios

mobile-android: ## Build the dev build and run it in the Android Emulator (needs Android Studio)
	cd $(MOBILE_DIR) && npx expo run:android

api-types: ## Regenerate the app's API types from the API's OpenAPI schema (after API changes)
	uv run --quiet python -m api.openapi $(MOBILE_DIR)/src/api/openapi.json
	cd $(MOBILE_DIR) && npx openapi-typescript src/api/openapi.json -o src/api/schema.d.ts --default-non-nullable false

mobile-check: ## App: API types current, TypeScript, ESLint + Prettier, Jest, iOS + Android bundle
	cd $(MOBILE_DIR) && npx openapi-typescript src/api/openapi.json -o src/api/schema.d.ts --default-non-nullable false --check \
		&& npx tsc --noEmit && CI=1 npx expo lint && npx jest --ci \
		&& CI=1 npx expo export --platform ios --platform android --output-dir dist >/dev/null

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-fix lint issues and format Python and Rust
	uv run ruff check . --fix
	uv run ruff format .
	cd $(PIPELINE_DIR) && cargo fmt
	cd $(MOBILE_DIR) && npx prettier --write --log-level warn .

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
