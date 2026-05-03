.PHONY: install test test-package test-unit test-contract test-integration test-e2e test-all test-summary lint typecheck format check validate-pr build

install:
	uv sync --all-groups

test:
	uv run python -m tools.test_harness run default

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
	uv run python -m tools.test_harness summary

lint:
	uv run ruff check .

typecheck:
	uv run pyright

format:
	uv run ruff format .

check: lint typecheck test

validate-pr: lint typecheck test build

build:
	uv build
