# Phase 5 Execution Plan: CLI, Docs, Hardening, And Final Validation

## Metadata

- Status: final phase execution plan
- Feature focus: Portable Run Exchange
- PR title: `Portable Run Exchange - Phase 5: CLI Docs And Hardening`
- Branch: `codex/run-bundle-cli-docs-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-cli-docs-hardening`
- Phase execution plan path: `docs/roadmap/stage-12/phases/run-bundle-cli-docs-hardening.md`
- Full plan: `docs/roadmap/stage-12/implementation-plan.md`
- Source phase: Phase 5, CLI, Docs, Hardening, And Final Validation
- Stack predecessor: none; Phase 4 merged to `develop`
- Base branch: `develop` via `origin/develop` at `ddc078dfcb7a07c9c914ec32c07a45f79d7cf07e`
- Target branch: `develop`
- Merge eligibility: merge-eligible after PR validation, automated review, CI, and target-branch verification
- Workflow path: expanded path
- Successor dependency notes: none; Phase 5 is the final Stage 12 implementation phase.
- Plan quality gate: passed on 2026-05-14 in the implementation plan
- Plan quality gate loop budget: review used, refinement used, confirmation used
- Draft pass: completed by managing Codex
- Refine pass: included in this scope-complete expanded-path plan; no separate refinement pass needed unless CLI behavior forces a public-surface decision
- Setup limitations: none; branch/worktree created from updated `origin/develop`
- Blockers: none

## Objective

Expose local bundle export, inspect, and import through thin `loom runs`
commands, update user-facing docs, harden CLI diagnostics, and complete final
Stage 12 validation without adding provider, network, plugin, or queue-owned
archive behavior.

## Full-Plan Context

Phases 1 through 4 landed portable exchange records, local bundle export,
safe inspect/import, offline-evidence alignment, resume-readiness reporting,
and queue-consumable transfer evidence. Phase 5 is the user-facing closure:
the CLI must call those public Python APIs without duplicating archive or store
logic, and docs must explain the conservative v12 behavior and deferrals.

## Stack Context

- Root or stacked phase: root phase after Phase 4 merge
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 4 PR #149 is merged and post-merge metadata is pushed to `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: branch can be deleted after merge because no later Stage 12 phase depends on it

## Source Phase Summary

- Goal: add `loom runs export`, `loom runs inspect`, and `loom runs import`
  wrappers plus docs and final validation evidence.
- Required scope: text/JSON result envelopes, CLI diagnostics for bundle
  failures, documentation for defaults/provenance/readiness/deferrals, and
  final package/import-boundary sweep.
- Required checkpoints: CLI imports public `loom.runs` APIs lazily; no bundle
  business logic is duplicated in CLI; no external provider or network behavior
  is introduced.
- Acceptance criteria: commands work in text and JSON modes, docs describe
  v12 behavior accurately, and `make validate-pr` plus `make test-summary`
  pass or record blockers.

## Current Source And Harness Findings

- `src/loom/cli/runs.py` already owns `loom runs index/list/diff`, lazy
  `loom.runs` imports, JSON envelope formatting, warning conversion, and
  catalog error mapping.
- `src/loom/runs` already exports `export_run_bundle`, `inspect_run_bundle`,
  `import_run_bundle`, `RunBundleExportOptions`, and `RunBundleImportPolicy`.
- Local export can use `SQLitePerRunAuthorityStore(run_uri)` as the authority
  store for a local completed run URI; import targets a local run collection.
- Existing integration tests build completed local runs and exercise bundle
  export/inspect/import APIs; CLI tests already cover text and JSON behavior
  for `loom runs` commands.
- Import-boundary constraints remain: top-level CLI may import command modules,
  but `loom.cli.runs` should import `loom.runs` and authority/store helpers
  lazily inside builders.

## In-Scope Work

- Register `loom runs export RUN_URI DESTINATION` with payload-selection flags,
  checksum verification, and text/JSON output.
- Register `loom runs inspect BUNDLE` with optional checksum verification and
  text/JSON output.
- Register `loom runs import BUNDLE TARGET_COLLECTION` with strict default
  policy and text/JSON output.
- Add formatting helpers for bundle export, inspect, and import summaries,
  including diagnostics and historical-only readiness blockers.
- Map `CatalogError`/validation failures to `CliError` with stable
  machine-readable CLI error codes.
- Add contract, integration, and e2e coverage for text and JSON command flows.
- Update docs for conservative metadata-only export, inspect without
  extraction, payload/log flags, target-local identity, source provenance,
  offline-evidence alignment, unsupported providers, and live-resume deferral.

## Out-of-Scope Work

- External provider integrations, plugin discovery, or automatic exporter
  dispatch.
- Network, cluster, SSH, object-store, or remote workspace transfer behavior.
- Queue-owned bundle schemas or queue parsing of archive contents.
- New top-level `loom bundle` command family.
- New import policies beyond the existing strict/historical-only defaults.

## Assumptions

- `loom runs export` should accept a local `RUN_URI` and destination archive
  path; the run URI is sufficient to open the local SQLite authority store for
  v12.
- `loom runs inspect` reports diagnostics and returns success if the public API
  returns a structured inspection result, even when that result status is
  `failed`; malformed/unreadable bundles remain CLI errors through the public
  API exception path.
- `loom runs import` returns success only when the public import result status
  is `succeeded`; failed import result envelopes become run-state CLI errors
  with JSON diagnostics.

## Scope Contract

The CLI is an outer wrapper over public `loom.runs` APIs. It may construct
option/policy records and local authority-store adapters, but it must not parse
tar members, copy bundle payloads, mutate run stores directly, interpret
provider-specific transfer data, or widen the importer/exporter protocols.
JSON envelopes use new stable schema versions under `loom.cli.runs.*.v1`.

## Design Impact

- Maintainability: CLI behavior stays thin and testable, with archive safety
  and import mutation retained in `loom.runs`.
- Extensibility: later provider-loaded CLI commands can reuse public result
  records and JSON envelopes without changing the local bundle surface.
- Domain neutrality: command text describes runs, bundles, diagnostics, and
  readiness, not domain-specific artifacts.
- Source-tree boundaries: `loom.cli` owns parsing/formatting; `loom.runs` owns
  exchange behavior; queue remains untouched.

## Future Compatibility

Future provider aliases, plugin discovery, transfer handlers, and live
migration work can extend the public APIs and add options without making local
bundle archives the provider protocol.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement archive parsing in CLI | It duplicates safety logic and violates the stage boundary. |
| Add a top-level `loom bundle` family | The plan selected the existing `loom runs` group. |
| Add provider names or auto-dispatch flags now | v12 only has built-in local bundle and offline-evidence adapters. |
| Treat imported history as resumable in text output | Live migrated resume is explicitly deferred. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Export CLI opens only local SQLite authority stores by run URI | v12 has no provider or authority-dispatch CLI design. | A later stage adds provider/plugin-backed export dispatch. |
| Import CLI exposes only strict historical-local behavior | Existing policies intentionally have one supported value each. | Merge/fork/overwrite or live-resume import policies are designed. |

## Reviewability

- Expected PR size and shape: CLI parser/handler updates, formatting helpers,
  focused tests, docs updates, and final phase metadata.
- Files and areas to inspect: `src/loom/cli/runs.py`,
  `src/loom/cli/formatting.py`, `tests/unit/loom/cli`,
  `tests/contracts/test_cli_runs_contract.py`,
  `tests/integration/pipeline/test_cli_runs.py`,
  `tests/e2e/test_cli_runs_e2e.py`, and docs under `docs/features`.
- Scope-control checks: no archive parsing in CLI, no provider integrations,
  no queue changes, no protocol widening, and no nonlocal transfer behavior.

## Implementation Steps

1. Add CLI schema constants, parsers, option builders, and lazy API builders for
   export/inspect/import.
2. Add text formatting helpers and JSON envelope payload handling for the three
   new commands.
3. Add unit/contract/integration/e2e tests for text, JSON, diagnostics, and a
   local happy-path export/inspect/import workflow.
4. Update docs for the Stage 12 run exchange behavior and deferrals.
5. Run targeted checks, then full `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`,
  `tests/package/test_runs_api.py`
- Required assertions or deferral reason: final sweep confirms CLI/runs
  imports stay lightweight and public APIs remain stable.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/cli/test_runs.py`,
  `tests/unit/loom/cli/test_formatting.py`
- Required assertions or deferral reason: option construction, handler wiring,
  text formatting, JSON envelopes, and CLI error mapping.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_runs_contract.py`
- Required assertions or deferral reason: stable JSON schemas for export,
  inspect, and import result envelopes plus diagnostic/readiness payload shape.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_cli_runs.py`
- Required assertions or deferral reason: CLI export/inspect/import flows over
  local completed-run bundles and strict import failures where practical.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_runs_e2e.py`
- Required assertions or deferral reason: limited local happy path through
  `main(argv)` for export, inspect, and import.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no network, cluster, plugin, or
  external provider behavior is in scope.

## Risks

- CLI could accidentally duplicate archive or store mutation behavior.
- Export could expose only local SQLite authority behavior more permanently
  than intended if docs do not mark provider dispatch as deferred.
- JSON schemas may need later extension for providers, so v12 should keep
  payloads close to public result dictionaries.
- Import failures returned as structured results must still produce appropriate
  CLI exit codes.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/cli/test_runs.py tests/unit/loom/cli/test_formatting.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py tests/package/test_runs_api.py
uv run ruff check src/loom/cli/runs.py src/loom/cli/formatting.py tests/unit/loom/cli/test_runs.py tests/unit/loom/cli/test_formatting.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py
uv run --extra config pyright src/loom/cli/runs.py src/loom/cli/formatting.py tests/unit/loom/cli/test_runs.py tests/unit/loom/cli/test_formatting.py tests/contracts/test_cli_runs_contract.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Keep all `loom.runs` and authority-store imports inside builders/handlers, not
  at module import time.
- Prefer public result `to_dict()` payloads for JSON envelopes.
- Text output should summarize status, counts, diagnostics, target/source
  identity, and readiness blockers without dumping full manifests.
- Conditions that require stopping for the manager: need for a top-level command
  family, provider dispatch, remote transfer behavior, or protocol widening.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in the Phase 5 worktree.
- Final phase execution plan: completed; expanded path selected because this is
  a public CLI surface and final-stage documentation/hardening phase.
- Implementation summary: added `loom runs export`, `loom runs inspect`, and
  `loom runs import` with text/JSON envelopes, public API delegation, local
  SQLite authority export wiring, strict historical import behavior, CLI
  diagnostics, contract/integration/e2e coverage, and docs for v12 bundle
  behavior and deferrals.
- Implementation validation: targeted Ruff passed; targeted Pyright passed;
  targeted pytest passed with 65 tests; `make validate-pr` passed with Ruff,
  Pyright, default pytest, config-extra pytest, and build success; `make
  test-summary` passed with package 77 passed, unit 1055 passed, contract 180
  passed, integration 149 passed, e2e 42 passed, and config-extra 438 passed.
- Refinement summary: no separate implementation refinement pass used; targeted
  fixes were completed during the implementation pass before full validation.
- Blocker-resolution summary: 0/3 blocker-resolution passes used.
- PR preparation: PR opened as https://github.com/samcantrill/loom/pull/150
  targeting `develop` from `codex/run-bundle-cli-docs-hardening`; verified
  with `gh pr view 150 --json baseRefName,headRefName,state,url`.
- Stack maintenance: none required; Phase 5 is a root phase targeting
  `develop`.
- Remaining blockers: none.
