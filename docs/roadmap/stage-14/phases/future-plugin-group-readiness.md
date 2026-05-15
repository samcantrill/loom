# Phase 4 Execution Plan: Future Group Readiness And Contract Hooks

## Metadata

- Status: PR open
- Feature focus: Plugin Discovery
- PR title:
  `Plugin Discovery - Phase 4: Future Group Readiness And Contract Hooks`
- Branch: `codex/future-plugin-group-readiness`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/future-plugin-group-readiness`
- Phase execution plan path:
  `docs/roadmap/stage-14/phases/future-plugin-group-readiness.md`
- Full plan: `docs/roadmap/stage-14/implementation-plan.md`
- Source phase: Phase 4, `future-plugin-group-readiness`
- PR: [#159](https://github.com/samcantrill/loom/pull/159)
- Stack predecessor: none
- Base branch: `develop` at `887ca684b623735fc88b8e85073b84c6d1a1ec8a`
- Target branch: `develop`
- Merge eligibility: root phase PR targets `develop`; merge only after
  implementation, required validation, automated review, CI, scope
  verification, and target-branch verification pass.
- Workflow path: expanded path, because this phase protects public future group
  contracts and Stage 15/19 compatibility.
- Plan quality gate: passed in the implementation plan on 2026-05-15.
- Expanded-path draft/refine status: completed in this planning pass.
- Blockers: none.

## Objective

Complete Stage 14 future-group readiness by making every non-recipe/non-codec
group explicitly listing/check-only in code contracts, CLI/preflight tests, and
documentation. The phase must especially protect
`loom.artifact_store_backends` from accidental backend construction,
credential probing, URI validation, registry mutation, or run-readiness claims.

## Current Source Recheck

Rechecked on 2026-05-15 in this worktree:

- `DataSource` exists under `loom.io.sources`, but no source plugin registry
  or loader contract exists in `src/loom`.
- `ExecutorDescriptorRegistry` exists for runtime capabilities, but no
  executor implementation plugin registry/loader is defined.
- `RunExporter` and `RunImporter` protocols exist under `loom.runs.models`,
  but no run-exporter plugin registry/adapter loader exists.
- `SweepProposalProvider` exists under `loom.pipeline.sweep.providers`, but no
  sweep-provider plugin registry/adapter loader exists.
- `EventSink` and `EventSinkRegistry` are docs-only in `docs/features/plugins.md`;
  no source-level event sink registry exists.
- `ArtifactStoreFactory` exists as local-root runner/stage-worker plumbing, but
  Stage 15 still owns backend descriptors, config handoff, capability records,
  URI validation, credentials, operation semantics, and any backend registry.

Conclusion: only `loom.recipes` and `loom.codecs` are registry-ready in Stage
14. All future groups stay metadata/listing/check-only.

## Scope

- Add or refine plugin readiness metadata for all known groups, without
  changing the Phase 3 CLI JSON schema shape unnecessarily.
- Add tests proving future groups list deterministically with `listing-only`
  readiness and do not import targets by default.
- Add tests proving `plugins check` and selected plugin preflight fail closed
  or skip load for future groups, especially artifact-store backends.
- Extend contract/package tests so no future-group loader is exported by
  `loom.plugins` or `loom.plugins.entrypoints`.
- Update docs/readiness notes with current source recheck evidence, future
  revisit triggers, and artifact-store backend boundary guidance.

## Out Of Scope

- Source, executor, run-exporter, sweep-provider, artifact-store-backend, or
  event-sink registration loaders.
- Artifact-store backend descriptor/factory, registry, config schema,
  capability model, URI validation, credential probing, materialization,
  cache/staging behavior, operation-result schema, runner integration, or
  run-readiness claims.
- Concrete external service integrations, optional SDK dependencies, network
  probes, or marketplace/install behavior.
- Third-party CLI command injection.

## Acceptance Criteria

- Future groups are listed with `listing-only` readiness in CLI/plugin
  summaries.
- `loom plugins check` returns nonzero for unsupported future-group load/check
  requests and does not import advertised targets.
- Selected plugin preflight for future groups reports metadata and skips load
  with listing-only details.
- Artifact-store backend tests prove Stage 14 does not construct stores,
  validate URI schemes, probe credentials, or claim run readiness.
- Docs identify each future group, current contract status, Stage 14 behavior,
  and revisit trigger.

## Validation

Targeted development command:

```sh
uv run pytest tests/unit/loom/plugins tests/unit/loom/cli tests/unit/loom/diagnostics tests/contracts tests/package
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Design Impact

- Maintains the Stage 14 public group namespace without freezing premature
  runtime object shapes.
- Keeps plugin diagnostics honest: discovered metadata is not equivalent to
  registered or run-ready behavior.
- Gives Stage 15 artifact-store backend work and Stage 19 event-sink work room
  to define their own descriptors, registries, validation, and lifecycle
  policy.

## Future Compatibility

- Stage 15 can add a store-owned backend descriptor/factory registry without
  refactoring Stage 14 metadata discovery.
- Run exchange and sweep work can add loaders after their owning packages define
  explicit registries or adapter-loading APIs.
- Event sink plugins can reuse the same listing/check path when runtime event
  records and sink registry contracts land.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add import-only checks for every future group | It still imports optional SDKs/project code and can be mistaken for registration readiness. |
| Treat current local-root `ArtifactStoreFactory` as the backend plugin contract | It would freeze a runner-local construction shape before Stage 15 defines config, capabilities, credentials, and operation semantics. |
| Add generic future-group loaders returning raw objects | It bypasses subsystem-owned validation and registry policy. |
| Leave readiness only in prose | Tests should lock the listing-only behavior that users see in CLI/preflight output. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Future groups are public before loaders exist | Stable metadata namespaces are useful for downstream packages now | Owning subsystem lands a registry/adapter loader contract |
| Readiness metadata is diagnostic, not a persisted schema | Stage 14 only needs user-facing list/check evidence | Provenance work needs a versioned plugin-readiness document |
| Run exporter and sweep provider groups remain listing-only despite protocols existing | No source-level plugin registry or adapter-loading contract exists | Run exchange or sweep package defines supplied registries/load adapters |

## Reviewability

- Expected PR shape: small docs/test-focused PR, with minimal production changes
  only if readiness metadata needs a clearer reusable hook.
- Scope-control checks:
  - No new loader functions for future groups.
  - No artifact-store backend construction or credential/URI probing.
  - No `loom.plugins` import of CLI, preflight, run stores, runner lifecycle,
    or optional service dependencies.
  - Tests use fake entry points and monkeypatched imports only.

## Refinement And Review Budget Status

- Phase planning draft: completed.
- Phase planning refinement: completed in this planning pass.
- Phase implementation refinement: not needed; targeted validation and the full
  PR gate passed after the implementation commit.
- PR body draft/refine: completed; PR body is
  `docs/roadmap/stage-14/phases/future-plugin-group-readiness-pr-body.md`.
- PR review: unused until the manager or reviewer consumes the single review
  pass.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: completed in
  `docs/roadmap/stage-14/phases/future-plugin-group-readiness.md`.
- Final phase execution plan: completed and ready for implementation.
- Implementation summary: added public plugin group readiness metadata,
  preserved recipes/codecs as the only registry-ready groups, locked all
  future groups as listing-only in contracts/CLI/preflight tests, and updated
  plugin feature docs with current contract evidence and revisit triggers.
- Validation:
  - Focused suite passed:
    `uv run pytest tests/unit/loom/plugins tests/unit/loom/cli/test_plugins.py
    tests/unit/loom/diagnostics/test_preflight_plugins.py
    tests/contracts/test_plugin_future_groups_contract.py
    tests/contracts/test_plugin_discovery_contract.py
    tests/package/test_plugins_api.py`
    with 53 passed.
  - `uv run ruff check ...` passed for touched source, test, and docs paths.
  - `uv run pyright ...` passed for touched source and tests.
  - `make validate-pr` passed: Ruff, Pyright, default suite
    (1599 passed, 26 skipped, 18 deselected), config-extra suite
    (440 passed, 1636 deselected), and build.
  - `make test-summary` passed: package 87, unit 1131, contract 210,
    integration 156, e2e 43, and config-extra 440 tests passed.
- PR: [#159](https://github.com/samcantrill/loom/pull/159), targeting
  `develop` from `codex/future-plugin-group-readiness`.
- Merge: pending.
