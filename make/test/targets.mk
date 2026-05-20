.PHONY: test-help test test-no-extra test-config-extra test-package test-unit
.PHONY: test-contract test-integration test-e2e test-all test-weave
.PHONY: test-package-summary test-unit-summary test-contract-summary
.PHONY: test-integration-summary test-e2e-summary test-config-extra-summary
.PHONY: test-summary

TEST_HARNESS := python -m tools.test_harness
TEST_UV_RUN := uv run
WEAVE_TEST_DIR := packages/weave
TEST_UV_DEV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --isolated --locked --group dev
TEST_UV_DEV_CONFIG := UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --isolated --locked --group dev --extra config
TEST_UV_LOCKED_DEV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv run --locked --group dev

test-help:
	@printf 'Loom test targets\n'
	@printf '\n'
	@printf 'Suite runs:\n'
	@printf '  make test                 Run the default no-extra test suite\n'
	@printf '  make test-no-extra        Run baseline tests without optional extras\n'
	@printf '  make test-config-extra    Run optional config dependency tests\n'
	@printf '  make test-package         Run package/API tests\n'
	@printf '  make test-unit            Run unit tests\n'
	@printf '  make test-contract        Run contract tests\n'
	@printf '  make test-integration     Run integration tests\n'
	@printf '  make test-e2e             Run end-to-end tests\n'
	@printf '  make test-all             Run all local non-network, non-SLURM tests\n'
	@printf '  make test-weave           Run package-local weave tests\n'
	@printf '\n'
	@printf 'Summary reports:\n'
	@printf '  make test-summary                 Write all suite summaries to build/test-summary.md\n'
	@printf '  make test-package-summary         Write package suite summary\n'
	@printf '  make test-unit-summary            Write unit suite summary\n'
	@printf '  make test-contract-summary        Write contract suite summary\n'
	@printf '  make test-integration-summary     Write integration suite summary\n'
	@printf '  make test-e2e-summary             Write end-to-end suite summary\n'
	@printf '  make test-config-extra-summary    Write config-extra suite summary\n'

test:
	@$(MAKE) test-no-extra

test-no-extra:
	$(TEST_UV_DEV) $(TEST_HARNESS) run default

test-config-extra:
	$(TEST_UV_DEV_CONFIG) $(TEST_HARNESS) run config-extra

test-package:
	$(TEST_UV_RUN) $(TEST_HARNESS) run package

test-unit:
	$(TEST_UV_RUN) $(TEST_HARNESS) run unit

test-contract:
	$(TEST_UV_RUN) $(TEST_HARNESS) run contract

test-integration:
	$(TEST_UV_RUN) $(TEST_HARNESS) run integration

test-e2e:
	$(TEST_UV_RUN) $(TEST_HARNESS) run e2e

test-all:
	$(TEST_UV_RUN) $(TEST_HARNESS) run all

test-weave:
	cd $(WEAVE_TEST_DIR) && UV_CACHE_DIR=$(UV_CACHE_DIR) PYTHONPATH=src uv run --group dev python -m pytest

test-package-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary package --output build/test-package-summary.md

test-unit-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary unit --output build/test-unit-summary.md

test-contract-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary contract --output build/test-contract-summary.md

test-integration-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary integration --output build/test-integration-summary.md

test-e2e-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary e2e --output build/test-e2e-summary.md

test-config-extra-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary config-extra --output build/test-config-extra-summary.md

test-summary:
	$(TEST_UV_LOCKED_DEV) $(TEST_HARNESS) summary
