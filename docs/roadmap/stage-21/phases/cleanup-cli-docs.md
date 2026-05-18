# Phase 5 Execution Plan: Cleanup CLI And Documentation

## Metadata

- Status: final phase execution plan
- Feature focus: Cleanup And Retention
- PR title: `Cleanup And Retention - Phase 5: CLI Commands And Documentation`
- Branch: `codex/cleanup-cli-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-cli-docs`
- Phase execution plan path: `docs/roadmap/stage-21/phases/cleanup-cli-docs.md`
- PR: pending
- Full plan: `docs/roadmap/stage-21/implementation-plan.md`
- Source phase: Phase 5, `cleanup-cli-docs`
- Stack predecessor: none; predecessor PR https://github.com/samcantrill/loom/pull/194 merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 4 merge; eligible for merge to `develop` after automated review, validation, CI, and PR target checks pass
- Workflow path: expanded path
- Successor dependency notes: final Stage 21 phase; no successor phase is expected.
- Plan quality gate: passed in the implementation plan on 2026-05-18
- Plan quality gate loop budget: consumed by recorded review/refinement/confirmation; no blockers remain
- Draft pass: completed locally in this artifact
- Refine pass: completed locally in this artifact because Phase 5 adds destructive CLI entry points and final user-facing docs
- Setup limitations: none
- Blockers: none

## Objective

Expose the Stage 21 cleanup behavior through thin CLI commands and public documentation while keeping cleanup policy, safety, deletion, result facts, event projection, and collection orchestration inside the cleanup APIs implemented by earlier phases.

## Full-Plan Context

Phases 1 through 4 added cleanup records, bounded selectors, retention hints, authority-backed dry-run planning, explicit local deletion, audit event projection, collection GC, and read-only cleanup preflight checks. This final phase adds `loom clean` and `loom gc` command surfaces, text/JSON formatting, confirmation behavior, feature documentation, and final validation evidence. Whole-run deletion, provider deletion, automatic retention enforcement, arbitrary query parsing, and cleanup-specific event sink loading remain out of scope.

## Stack Context

- Root or stacked phase: root phase after predecessor merge
- Current predecessor branch or PR: none; Phase 4 PR #194 merged to `develop`
- Why this base branch is correct: Phase 5 depends on Phase 4 collection cleanup helpers and cleanup preflight ids now present on `develop`.
- Retarget/rebase plan after predecessor merge: not needed at plan creation.
- Branch cleanup constraints: no successor branches are expected to depend on this branch.

## Source Phase Summary

- Goal: expose cleanup and candidate-level GC through CLI commands and update docs, examples, and final validation evidence.
- Required scope: `loom clean RUN_URI`, `loom gc <collection>`, selector flag parsing, confirmation or `--yes` for mutation, text/JSON output, docs, and CLI/e2e tests.
- Required checkpoints: CLI delegates policy to public cleanup APIs, collection paths are discovery inputs only, mutation requires explicit confirmation or `--yes`, and whole-run/provider deletion remains deferred.
- Acceptance criteria: CLI dry-run/delete and collection GC match public cleanup APIs; JSON output uses public plain-data cleanup records; docs describe safety, deferrals, and examples; final repository validation passes or any unavailable checks are justified.

## Current Source And Harness Findings

- CLI commands register via `src/loom/cli/main.py` and one module-level `register_subparser(...)` function per command group.
- Existing CLI modules use `OutputFormat`, `format_json_envelope(...)`, and `CliError`/`ExitCode` for stable output and error mapping.
- Public cleanup APIs already provide per-run `plan_cleanup(...)`, `execute_cleanup(...)`, `CollectionCleanupTarget`, `plan_collection_gc(...)`, and `execute_collection_gc(...)`.
- Existing selectors use `CleanupSelector`; CLI parsing should map bounded flags to that record instead of adding a new query language.
- Existing run catalog APIs can discover local run summaries, but collection paths must not become managed roots or deletion authority.
- Unit CLI tests usually monkeypatch command builder functions; integration/e2e tests can use temporary authority repositories and synthetic local runs.

## In-Scope Work

- Add `loom clean` command support for dry-run preview and explicit deletion of selected cleanup candidates for one run.
- Add `loom gc` command support for candidate-level cleanup across local run collections.
- Add bounded selector flags, including representative `--older-than 7d`, plus status/reason/kind/stage/artifact/tag/retention filters where they map cleanly to `CleanupSelector`.
- Add confirmation/`--yes` behavior for mutating commands, with dry-run as the default.
- Add concise text output and stable JSON envelopes backed by public cleanup record `to_dict()` payloads.
- Update public docs for cleanup safety, retention hints, preflight warnings, collection GC, CLI examples, and explicit deferrals.
- Add package/unit/contract/integration/e2e coverage for parser, formatting, confirmation, JSON output, and synthetic cleanup flows.

## Out-of-Scope Work

- Whole-run directory deletion, run tombstones, or cleanup of arbitrary directories.
- Provider or remote deletion commands, provider SDKs, credential probing, or remote retention enforcement.
- CLI-owned deletion policy, direct filesystem deletion from CLI code, or cleanup-specific event sink loading.
- Arbitrary boolean query parsing or unbounded selectors.
- Treating run collection paths as managed roots or ownership evidence.

## Assumptions

- `argparse` remains the CLI framework.
- `--older-than` can accept compact duration values such as `7d`, `12h`, `30m`, and seconds.
- A first `loom gc` implementation can discover current runs through the existing local catalog/list APIs and require per-run cleanup facts to carry managed-root/ownership evidence.
- Interactive confirmation can read from standard input through a small helper that is unit-testable.

## Scope Contract

CLI modules parse arguments, build cleanup selectors and delete intent records, call cleanup APIs, and format results. They must not reimplement selector matching, path safety, deletion, authority persistence, event projection, or collection cleanup orchestration. `loom clean` defaults to dry-run. Mutating `loom clean` and `loom gc` require `--delete` plus either `--yes` or an affirmative prompt. JSON payloads expose cleanup reports/results through public plain-data records, wrapped in normal CLI result envelopes.

## Design Impact

- Maintainability: keeps CLI code as orchestration and presentation around existing cleanup APIs.
- Extensibility: future selector flags and provider adapters can map to cleanup records without changing CLI output envelopes.
- Domain neutrality: commands and docs use generic runs, candidates, targets, retention modes, and synthetic examples.
- Source-tree boundaries: `loom.cli` imports public cleanup APIs and run discovery helpers; cleanup modules remain free of CLI imports.

## Future Compatibility

- Future remote deletion can add adapter support behind cleanup APIs without adding provider-specific CLI policy.
- Future whole-run deletion can add a separate command or flag family with stronger gates instead of overloading Stage 21 candidate GC.
- Future catalog paging can change discovery internals without changing `loom gc` output payloads.
- Future audit-heavy dry-run workflows can add explicit report recording without making default preview mutating.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add cleanup subcommands under `loom runs` only | The plan calls for direct `loom clean` and `loom gc` entry points, and cleanup is not just catalog inspection. |
| Let CLI delete paths from formatted dry-run rows | Duplicates cleanup policy and bypasses result facts/events. |
| Make `loom gc <collection>` delete whole run directories | Violates Stage 21 candidate-level GC and whole-run deletion deferral. |
| Require a new query language for selectors | The plan requires bounded selector flags and rejects arbitrary parsing. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| First CLI selector parser supports a bounded flag set. | Keeps destructive workflows explainable and reviewable for Stage 21. | Users need compound boolean cleanup policies or saved cleanup policies. |
| `loom gc` discovery remains local-catalog based. | Stage 21 excludes provider deletion and remote collection cleanup. | A future authoritative remote catalog/discovery API lands. |

## Reviewability

- Expected PR size and shape: medium CLI/docs/test addition with no cleanup core rewrites.
- Files and areas to inspect: command registration, selector parsing, confirmation gates, JSON payload shape, docs examples, and synthetic integration/e2e fixtures.
- Scope-control checks: no direct deletion from CLI, no whole-run deletion flags, no provider SDK imports, no event sink loading, and no collection path as managed-root behavior.

## Implementation Steps

1. Add cleanup CLI helpers for selector parsing, confirmation, output formatting, and dry-run/delete orchestration for one run.
2. Register `loom clean` and `loom gc` commands in `src/loom/cli/main.py`.
3. Add collection discovery and `loom gc` orchestration over public collection cleanup APIs without treating collection paths as authority.
4. Add unit, contract, integration, and e2e coverage for dry-run, delete, selector parsing, confirmation, JSON, and collection flows.
5. Update feature docs and roadmap artifacts with final CLI behavior and validation evidence.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py` and CLI package/import checks where applicable
- Required assertions or deferral reason: new CLI modules remain importable without loading provider SDKs or cleanup implementation internals unnecessarily.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/cli/test_clean.py`, `tests/unit/loom/cli/test_gc.py`, `tests/unit/loom/cli/test_main.py`
- Required assertions or deferral reason: parser registration, selector parsing, confirmation gates, output formatting, JSON envelopes, and error mapping.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts` with cleanup CLI JSON/plain-data output paths
- Required assertions or deferral reason: JSON output remains plain-data and references public cleanup report/result shapes.

### Integration Suite

- Status: required
- Expected paths: cleanup CLI integration tests under `tests/integration`
- Required assertions or deferral reason: CLI handlers operate over temporary authority-backed runs, append result facts on deletion, and do not treat collection paths as managed roots.

### E2E Suite

- Status: required
- Expected paths: cleanup-specific e2e tests under `tests/e2e`
- Required assertions or deferral reason: user-visible dry-run/delete flows and collection GC flows work through `loom.cli.main.main`.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: provider-specific cleanup, remote deletion, and live services remain outside Stage 21.

## Risks

- Confirmation prompts can be hard to test unless stdin handling is isolated.
- CLI output may expose too much nested record detail in text mode if formatting is not summarized.
- Collection discovery may be tempted to infer managed roots from paths instead of recorded cleanup facts.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/cli -k 'clean or gc'
uv run pytest tests/contracts -k cleanup
uv run pytest tests/integration -k cleanup
uv run pytest tests/e2e -k cleanup
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: selector/output helpers, `loom clean`, `loom gc`, tests, docs.
- Tests to run with each slice: CLI unit tests after parser/formatting, cleanup integration/e2e tests after command orchestration, contracts after JSON shape changes.
- Decisions the executor must not revisit: dry-run default, explicit delete intent, CLI as thin wrapper, candidate-level GC only, no provider deletion, no whole-run deletion flags.
- Conditions that require stopping for the manager: CLI needs to delete paths directly, collection paths must become managed roots, or arbitrary query parsing is required.

## Refinement And Review Budget Status

- Phase implementation refinement: used locally to preserve CLI import-light
  behavior and fix focused Pyright summary typing before final validation
- PR review: completed by manager review; no blocking findings
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally
- Final phase execution plan: completed locally
- Implementation summary: added `loom clean` and `loom gc` command modules,
  shared bounded selector/confirmation helpers, parser registration, text/JSON
  output, explicit `CleanupDeleteIntent` construction, authority-backed
  dry-run/delete orchestration, feature docs, and cleanup CLI coverage across
  package, unit, contract, integration, and e2e suites.
- Implementation validation: targeted cleanup validation passed outside the
  sandbox after the sandbox blocked service-authority sockets:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/cli tests/contracts
  -k cleanup tests/integration -k cleanup tests/e2e -k cleanup
  tests/package/test_import_boundaries.py::test_cli_help_remains_import_light
  tests/package/test_import_boundaries.py::test_import_cli_remains_import_safe`
  reported 17 passed / 17 skipped / 590 deselected for cleanup-selected suites
  after the initial sandbox-only service-authority `PermissionError`.
- Final validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with
  Ruff, Pyright, default harness, config-extra harness, and build.
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
  `build/test-summary.md` with package 108 passed / 1 skipped, unit 1394
  passed / 7 skipped / 1 deselected, contract 274 passed / 2 skipped,
  integration 170 passed / 8 skipped / 13 deselected, e2e 46 passed /
  2 deselected, and config-extra 449 passed / 3 skipped / 2001 deselected.
- Refinement summary: kept cleanup API imports lazy so `loom --help` and direct
  cleanup CLI imports do not load `loom.pipeline`; added an explicit
  import-boundary test and fixed summary integer typing for Pyright.
- Blocker-resolution summary: 0/3 used; no implementation, validation, or
  mergeability blockers remain before PR opening.
- PR preparation: PR body drafted in
  `docs/roadmap/stage-21/phases/cleanup-cli-docs-pr-body.md`; PR creation
  pending.
- Stack maintenance: not needed; root phase from `develop` after Phase 4 merge.
- Remaining blockers: none.
