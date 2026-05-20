.PHONY: dev-help lint typecheck format check validate-pr build
.PHONY: lint-weave typecheck-weave test-weave test-weave-examples build-weave validate-weave

dev-help:
	@printf 'Loom development targets\n'
	@printf '\n'
	@printf 'Checks and formatting:\n'
	@printf '  make lint          Run Ruff checks\n'
	@printf '  make typecheck     Run Pyright with config extras\n'
	@printf '  make lint-weave    Run Ruff checks for weave package sources\n'
	@printf '  make typecheck-weave Run Pyright for weave package sources\n'
	@printf '  make format        Format Python sources with Ruff\n'
	@printf '  make check         Run lint, typecheck, and default tests\n'
	@printf '\n'
	@printf 'Validation and packaging:\n'
	@printf '  make validate-pr   Run the local PR validation gate\n'
	@printf '  make build         Build source and wheel distributions\n'
	@printf '  make build-weave    Build the weave package\n'
	@printf '  make validate-weave  Run weave lint/typecheck/tests/examples/build checks\n'

lint:
	uv run ruff check .

typecheck:
	uv run --extra config pyright

lint-weave:
	cd packages/weave && UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --group dev ruff check .

typecheck-weave:
	cd packages/weave && UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --group dev pyright .

format:
	uv run ruff format .

check: lint typecheck test

validate-pr: lint typecheck test-no-extra test-config-extra build

build:
	uv build

build-weave:
	cd packages/weave && UV_CACHE_DIR=$(UV_CACHE_DIR) uv build

validate-weave: lint-weave typecheck-weave test-weave test-weave-examples build-weave
