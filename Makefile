UV_CACHE_DIR ?= /tmp/uv-cache
export UV_CACHE_DIR
.DEFAULT_GOAL := install

.PHONY: help

help:
	@printf 'Loom make targets\n'
	@printf '\n'
	@printf 'Target groups:\n'
	@printf '  make setup-help    List setup and dependency targets\n'
	@printf '  make dev-help      List development, validation, and build targets\n'
	@printf '  make test-help     List test run and summary targets\n'

include make/setup/*.mk
include make/dev/*.mk
include make/test/*.mk
