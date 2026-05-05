.PHONY: dev-help lint typecheck format check validate-pr build

dev-help:
	@printf 'Loom development targets\n'
	@printf '\n'
	@printf 'Checks and formatting:\n'
	@printf '  make lint          Run Ruff checks\n'
	@printf '  make typecheck     Run Pyright with config extras\n'
	@printf '  make format        Format Python sources with Ruff\n'
	@printf '  make check         Run lint, typecheck, and default tests\n'
	@printf '\n'
	@printf 'Validation and packaging:\n'
	@printf '  make validate-pr   Run the local PR validation gate\n'
	@printf '  make build         Build source and wheel distributions\n'

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
