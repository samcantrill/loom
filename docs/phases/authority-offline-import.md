# Phase 18 Execution Plan: Offline Import Transaction

## Metadata

- Status: final phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 18: Offline Import Transaction`
- Branch: `codex/authority-offline-import`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-offline-import`
- Phase execution plan path: `docs/phases/authority-offline-import.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 18 - Offline Import Transaction
- Stack predecessor: none; Phase 17 merged in PR #135 and is recorded in the plan
- Base branch: `develop` at `ddd898f`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: none; this is the final v10 implementation phase.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed before phase work; no blocking findings remain.
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: completed by managing agent on 2026-05-12 after confirming repository transaction, protocol-result body, route/client, and provenance surfacing boundaries
- Setup limitations: none; Phase 17 offline evidence writer is merged into `develop`.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Import complete v10 offline evidence manifests into the authority service as
authoritative facts, using strict validation, collision rejection, and a single
repository transaction.

## Full-Plan Context

Phases 1-16 made online mutation service-backed and scheduler-ready. Phase 17
created explicit non-authoritative offline evidence. Phase 18 completes v10 by
accepting only that v10 evidence shape and replaying it into authority truth
without adding legacy repair, deferred-finalization conversion, remote artifact
movement, or overwrite/fork behavior.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 17 is merged into `develop`
- Why this base branch is correct: all earlier v10 phases are recorded as merged and `develop` includes the Phase 17 merge metadata commit `ddd898f`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: no successor branch depends on this final phase branch

## Source Phase Summary

- Goal: atomically import accepted v10 offline evidence manifests into authority truth.
- Required scope: import API and CLI, equivalence checker, manifest/schema/state validation, collision rejection, atomic repository transaction, import provenance, replay-level evidence/audit timeline, and read/status/catalog/diagnostics visibility.
- Required rejection classes: incomplete evidence, incompatible kind/schema, authoritative or unsafe source labels, stale/non-terminal data, conflicting run identity, unsafe or ambiguous artifact/stage/output facts, and transaction rollback.
- Acceptance criteria: accepted imports create authoritative run/stage/attempt/output/artifact facts; rejected imports do not mutate authority state; existing run identities reject before mutation.

## Current Source And Harness Findings

- `loom.pipeline.offline_evidence` now provides strict manifest models, `read_offline_evidence_manifest`, and complete/incomplete diagnostics.
- Authority repository writes are private to `src/loom/authority/_repository.py`; public runtime code must continue through service/client abstractions.
- Existing repository methods each open their own transaction, so Phase 18 needs a repository-owned import method or service helper that performs all inserts inside one `AuthorityRepository.transaction()` block.
- The repository schema already stores runs, stages, attempts, output commits, artifact facts, submitted operations, cleanup/recovery records, and audit events. Import provenance can be represented through run metadata, lifecycle reasons, and audit events without a schema migration unless a blocker proves a dedicated table is required.
- `AuthorityProtocolResult.body` is the right initial response payload for import result facts, avoiding a broad protocol-field expansion for a single operation.
- `AuthoritativeRunSnapshot` can be additively extended with run metadata/provenance read facts because `_run_snapshot()` already has access to `authority_runs.metadata_json`.
- Diagnostics/status/catalog summaries use state-source metadata and read-model fields; imported state should be surfaced through additive `import_provenance` metadata without changing existing status semantics.
- `AuthorityClient`, FastAPI mutation routes, and `AuthorityMutationService` already use neutral protocol envelopes and are the correct service boundary for CLI import. The import route can live under the authority mutation route group because it is a repository mutation, but it must keep a distinct `offline_import` operation name and path.
- `loom authority` owns authority lifecycle subcommands; the import CLI can fit there without creating a broad top-level command.

## In-Scope Work

- Add neutral import result/rejection/equivalence models in a service-owned module such as `src/loom/authority/offline_import.py`.
- Validate manifests before mutation: kind, schema version, non-authoritative source, complete status, no error diagnostics, terminal run status, parseable execution plan, stage order consistency, terminal stage statuses, output/artifact consistency, local payload facts, config/provenance shape, and event ordering.
- Add an authority repository import operation that rejects existing run identities before insertion and writes the accepted run, stage, attempt, output commit, artifact fact, lifecycle reason, and audit-event timeline inside one SQLite transaction.
- Add an import service/API route and `AuthorityClient` helper so callers do not mutate private SQLite state directly.
- Add a CLI surface, tentatively `loom authority import-offline MANIFEST`, with standard authority-selection options and compact JSON/text output.
- Expose import provenance in authoritative read/status/catalog/diagnostics surfaces through state-source/provenance metadata and imported audit facts.
- Add rollback tests by forcing a mid-transaction failure after validation and proving no partial authoritative run can be read.
- Add only small protocol/capability vocabulary needed by the import operation, such as `offline_import`, if the existing enums need a stable operation family or capability label.

## Out-of-Scope Work

- Importing legacy/pre-v10 run directories or deferred-finalization envelopes.
- Repairing incomplete evidence or tolerating unknown facts.
- Remote artifact upload, payload copy, or object-store migration.
- Collision overwrite, run forking, or import replacement workflows.
- Domain-specific semantic equivalence beyond the recorded generic pipeline facts.
- New scheduler/resource allocation behavior.

## Assumptions

- The first import can preserve offline payload/log/config/provenance references as evidence metadata and audit payloads rather than copying files into an authority-owned object store.
- Imported authority status should reflect the terminal offline run and stage statuses, with lifecycle reasons marking `offline_import`.
- Stage attempts can be reconstructed from offline stage status attempt numbers; missing attempt numbers are rejection-worthy for RUN stages and terminal outputs.
- A failed stage without outputs imports as a terminal attempt without an output commit; a succeeded stage with outputs imports artifact facts and an output commit.
- Static skipped/stale/blocked stages may be represented as terminal stage/attempt facts when the offline manifest contains terminal status evidence.
- The repository should expose imported run metadata through snapshots; catalog integration can then consume import provenance through read-model metadata without scanning private database tables.

## Scope Contract

Phase 18 must only import Phase 17 v10-created manifests. It must reject
ambiguous evidence before opening a repository write transaction when practical,
and must leave the repository unchanged on validation or transaction failure.
The CLI and HTTP route must use the authority service/client boundary. No
runtime path may silently import evidence, and no online execution failure may
trigger import.

## Design Impact

- Maintainability: validation and mutation are separated so rejection reasons remain testable without repository setup.
- Extensibility: import result/rejection models and manifest version checks leave room for future schema migrations or remote artifact import workflows.
- Compatibility: imported state uses existing authority facts first; any read-model additions must be additive and schema-version compatible.
- Domain neutrality: import compares generic run, stage, artifact, resource, provenance, and event facts only.

## Future Compatibility

Later migration tools can add explicit legacy/deferred import profiles or remote
payload handling without weakening this v10 import contract. Manifest version
checks should fail closed until a compatibility adapter is intentionally added.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Drive import through repeated public mutation calls | That cannot guarantee a single atomic transaction across the full replay. |
| Import raw run directories without the Phase 17 manifest | The full plan requires v10-created evidence, not inferred local state. |
| Overwrite or fork an existing run URI | The plan requires strict collision rejection. |
| Store imported state only as an audit blob | Status, catalog, diagnostics, and read models need authoritative run/stage/artifact facts. |
| Copy local payloads during import | Remote/local payload movement is explicitly out of scope for this phase. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No legacy/deferred import path | The phase must complete strict v10 import without weakening trust semantics. | Users need migration of older local/deferred evidence. |
| Imported payload evidence remains reference metadata | Payload copying and remote store contracts are out of scope. | Authority-owned artifact storage or remote evidence import is designed. |
| Collision policy is reject-only | Replacement/fork workflows need separate UX and audit semantics. | A product requirement for controlled replacement appears. |

## Reviewability

- Expected PR size and shape: one import validator/service module, repository atomic import method, route/client/CLI wiring, additive read/diagnostic provenance surfacing, focused tests, and PR artifacts.
- Files and areas to inspect: `src/loom/authority/offline_import.py`, `src/loom/authority/_repository.py`, `src/loom/authority/mutation_service.py`, `src/loom/authority/routes/mutations.py`, `src/loom/pipeline/stores/authority_client.py`, `src/loom/cli/authority.py`, read-model/status/catalog diagnostics, and package/unit/contract/integration/e2e tests.
- Scope-control checks: no legacy import, no deferred-finalization conversion, no remote payload copy, no overwrite/fork behavior, no direct SQLite mutation from CLI/client code, and no online fallback import.

## Implementation Steps

1. Add import rejection/result models and a pure validation/equivalence checker for `OfflineEvidenceManifest`.
2. Add a repository-owned atomic import method that writes accepted facts and audit events in one transaction and rejects existing run URIs before insert; use direct SQL inside that transaction rather than composing public repository methods that each commit independently.
3. Add service/API/client plumbing for an offline-evidence import operation using authority protocol envelopes, a distinct import path, and `AuthorityProtocolResult.body` for accepted result facts.
4. Add `loom authority import-offline MANIFEST` with JSON/text result formatting and authority selection.
5. Add imported provenance visibility in status/catalog/diagnostics/read models with additive metadata.
6. Add unit/contract/integration/e2e coverage for accepted import, rejection classes, collision, API/CLI boundary, and rollback.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_execution_api.py` or authority API package tests
- Required assertions or deferral reason: CLI/client code does not import `loom.authority._repository`; import validation stays out of CLI modules; public exports remain intentional.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/authority/test_offline_import.py`, existing authority repository/service/client/CLI tests
- Required assertions or deferral reason: validation accepts complete Phase 17 manifests; rejects wrong kind/schema, incomplete manifests, error diagnostics, non-terminal statuses, stage order mismatches, artifact/output mismatches, collisions, and transaction rollback.

### Contract Suite

- Status: required
- Expected paths: new or existing `tests/contracts/test_offline_import_contract.py`, authority protocol contract tests
- Required assertions or deferral reason: import protocol request/response shape, rejection payload shape, accepted result shape, and manifest compatibility contract.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_mutation_api.py`, new authority import integration tests, CLI config integration if needed
- Required assertions or deferral reason: import a Phase 17 offline manifest into a temp repository-backed service, read back authoritative snapshot/status/catalog facts, and prove collision/rollback leave no partial run.

### E2E Suite

- Status: required if stable
- Expected paths: `tests/e2e/test_authority_supervisor_cli.py` or a focused CLI import smoke
- Required assertions or deferral reason: create an offline-first local evidence manifest, import it through CLI authority options into a temp service/repository, then read authoritative status.

### Opt-In Suites

- Status: deferred
- Markers affected: large artifacts, remote artifact stores, external hosted authority.
- Required assertions or deferral reason: Phase 18 uses deterministic local filesystem evidence and in-process or local temp service coverage only.

## Risks

- A too-permissive equivalence checker could import ambiguous or corrupted evidence as authority truth.
- A multi-call replay outside one repository transaction would violate atomicity.
- Provenance surfacing must not imply imported facts were live online execution.
- Adding route/client protocol surface can accidentally expose private repository concepts if not kept neutral.

## Validation Commands

Targeted development commands:

```sh
uv run ruff check src/loom/authority src/loom/cli/authority.py src/loom/pipeline/stores tests/unit/loom/authority tests/contracts tests/integration/authority tests/e2e/test_authority_supervisor_cli.py tests/package
uv run pyright src/loom/authority src/loom/cli/authority.py src/loom/pipeline/stores tests/unit/loom/authority tests/contracts tests/integration/authority tests/e2e/test_authority_supervisor_cli.py tests/package
uv run pytest tests/unit/loom/authority tests/contracts/test_offline_import_contract.py tests/integration/authority tests/e2e/test_authority_supervisor_cli.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: validator/result models first; repository atomic import second; service/route/client third; CLI/read-model visibility fourth; rejection/rollback/e2e tests last.
- Decisions not to revisit: v10 manifests only, complete evidence only, reject-only collisions, single repository transaction, service/client boundary for CLI, no payload copy, no deferred-finalization conversion, import result facts in protocol `body` unless implementation exposes a hard blocker.
- Conditions that require stopping for the manager: existing repository schema cannot express imported terminal run/stage/output facts without a migration, or service-route plumbing cannot support an atomic repository import without exposing private repository state.

## Refinement And Review Budget Status

- Phase implementation refinement: used locally during validation
- PR review: used by manager review on 2026-05-12
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Final phase execution plan: refined by managing agent on 2026-05-12; confirmed protocol `body` result payload, additive snapshot metadata/provenance surfacing, distinct import route/client operation, and direct SQL inside one repository transaction for atomicity.
- Implementation summary: added the strict `loom.authority.offline_import` validator/result surface, including manifest/schema/source/terminal-state/output/event checks and structured rejection diagnostics; added a repository-owned atomic import transaction that rejects collisions, writes imported run/stage/attempt/output/artifact facts, stores `authority_import` provenance metadata, and records replay-scoped audit events; wired the mutation service, FastAPI mutation routes, authority client, and `loom authority import-offline` CLI command; and surfaced imported provenance through authoritative snapshots, diagnostics inspection, and status text formatting.
- Implementation validation: focused Ruff/Pyright/pytest coverage passed for the import module, repository, client/route/CLI wiring, contract shapes, integration API flow, package boundaries, and import-specific e2e smoke; `make validate-pr` passed with Ruff, Pyright, default harness `1348 passed, 19 skipped, 14 deselected`, config-extra harness `424 passed, 1378 deselected`, and package build; `make test-summary` passed with package `70 passed, 1 skipped`, unit `978 passed, 1 skipped`, contract `157 passed, 2 skipped`, integration `130 passed, 8 skipped, 10 deselected`, e2e `40 passed, 2 deselected`, and config-extra `424 passed, 1378 deselected`.
- Refinement summary: one bounded local refinement pass tightened offline event validation to parse full `PipelineEventRecord` payloads, preserved original replay scope in imported audit events, threaded explicit `imported_by` through the client/CLI path, and repaired exact public-export test snapshots after the new route constant expanded `loom.pipeline.stores.__all__`.
- PR review: used by manager review on 2026-05-12; no scope, atomicity, provenance-labeling, protocol-boundary, validation-evidence, or PR-body blockers were found.
- Blocker-resolution summary: not needed; 0/3 blocker-resolution passes used.
- PR preparation: PR body prepared at `docs/phases/authority-offline-import-pr-body.md`; PR #136 opened at https://github.com/samcantrill/loom/pull/136 against `develop` from `codex/authority-offline-import`, target/head were verified with `gh pr view 136 --json baseRefName,headRefName,state,url`, and GitHub `checks` completed successfully before merge.
- Stack maintenance: root phase merged into `develop` at `d3770050a0e1df722909f89be1d6b7e3924bfb2e`; no successor branch depended on `codex/authority-offline-import`.
- Remaining blockers: none.
