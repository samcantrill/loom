.PHONY: install test test-no-extra test-config-extra test-package test-unit test-contract test-integration test-e2e test-all test-summary lint typecheck format check validate-pr build

install:
	uv sync --all-groups

test:
	@$(MAKE) test-no-extra

test-no-extra:
	UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run default

test-config-extra:
	UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra

test-package:
	uv run python -m tools.test_harness run package

test-unit:
	uv run python -m tools.test_harness run unit

test-contract:
	uv run python -m tools.test_harness run contract

test-integration:
	uv run python -m tools.test_harness run integration

test-e2e:
	uv run python -m tools.test_harness run e2e

test-all:
	uv run python -m tools.test_harness run all

test-summary:
	UV_CACHE_DIR=/tmp/uv-cache uv run --locked --group dev python -m tools.test_harness summary

lint:
	uv run ruff check .

typecheck:
	uv run --extra config pyright

format:
	uv run ruff format .

check: lint typecheck test

validate-pr: lint typecheck test-no-extra test-config-extra build

build:
	uv build
