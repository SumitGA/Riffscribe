# Developer shortcuts. Run `make` (or `make help`) to list targets.

.DEFAULT_GOAL := help
.PHONY: help setup setup-separation run view check lint fmt typecheck test test-accuracy test-separation rust clean

PIPELINE_DIR := packages/pipeline
FILE ?=
INSTRUMENT ?= guitar
OUT ?= out
ARGS ?=

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install dependencies and build the Rust extension
	uv sync

setup-separation: ## Also install optional Demucs source separation (~630 MB, torch)
	uv sync --group separation

run: ## Transcribe FILE=<audio> [INSTRUMENT=guitar|piano] [OUT=out] [ARGS="--force"]
	@test -n "$(FILE)" || { echo 'usage: make run FILE=path/to/audio.m4a [INSTRUMENT=piano] [ARGS="--force"]'; exit 1; }
	uv run python -m pipeline transcribe "$(FILE)" --out "$(OUT)" --instrument $(INSTRUMENT) $(ARGS)

view: ## Preview OUT (default out/) as notation + tab with playback, in the browser
	uv run python tools/preview/serve.py --out "$(OUT)"

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
	rm -rf "$(OUT)" .mypy_cache .ruff_cache .pytest_cache $(PIPELINE_DIR)/target
