.PHONY: install test lint typecheck format check build

install:
	uv sync --all-groups

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run pyright

format:
	uv run ruff format .

check: lint typecheck test

build:
	uv build
