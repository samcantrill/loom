# Phase 1 Execution Plan: Shared Operation And Evidence Contracts

## Metadata

- Status: refined phase execution plan - ready for implementation
- Feature focus: Artifact Payload Materialization
- PR title: `Artifact Payload Materialization - Phase 1: Shared Operation And Evidence Contracts`
- Branch: `codex/shared-operation-evidence-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/shared-operation-evidence-contracts`
- Phase execution plan path: `docs/roadmap/stage-16/phases/shared-operation-evidence-contracts.md`
- Full plan: `docs/roadmap/stage-16/implementation-plan.md`
- Source phase: `Phase 1: Shared Operation And Evidence Contracts`
- Stack predecessor: none; this is the root Stage 16 phase
- Base branch: local `develop` at `d4cd066674dac5b48576bfdbb054cded095ab346`
- Target branch: `develop`
- Merge eligibility: eligible only after implementation, targeted validation, `make validate-pr`, `make test-summary`, automated PR review, and PR target verification against `develop`; this planning commit alone is not merge-ready product work
- Workflow path: expanded path
- Successor dependency notes: Phase 2 depends on the public `loom.operations` records. If Phase 1 is not merged before Phase 2 starts, Phase 2 should branch from and target `codex/shared-operation-evidence-contracts`.
- Plan quality gate: passed in the implementation plan on 2026-05-15 with no blocking findings after review, bounded refinement, and confirmation review
- Plan quality gate loop budget: consumed and passed; do not rerun unless the implementation plan changes
- Draft pass: complete in this artifact
- Refine pass: complete in this artifact
- Setup limitations: the worktree and branch were provided by the manager; no product code was changed during planning
- Blockers: none

## Objective

Create the narrow public operation/evidence vocabulary that Stage 16 can reuse for payload materialization, backend capability summaries, run exchange projections, diagnostics, and later retry or cleanup evidence without creating a generic lifecycle subsystem.

## Full-Plan Context

Stage 16 starts with shared value objects because later phases need one status, diagnostic, adapter, and evidence vocabulary. Phase 2 will add local copy materialization records under `loom.pipeline.stores`, Phase 3 will add fake backend payload operations, Phase 4 will integrate explicit materialization into bundles and preflight, and Phase 5 will harden user-facing no-backend docs and handles. This phase must not implement materialization execution, payload handler protocols, bundle behavior, preflight probes, CLI flags, retry policy, cleanup policy, or real backend adapters.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: all earlier Stage 16 phases are absent, and the manager-provided branch was created from local `develop` commit `d4cd066674dac5b48576bfdbb054cded095ab346`
- Retarget/rebase plan after predecessor merge: not applicable for this root phase
- Branch cleanup constraints: keep `codex/shared-operation-evidence-contracts` until no successor phase branch targets or depends on it

## Source Phase Summary

- Goal: add bounded shared operation/evidence value objects and projection helpers that later Stage 16 phases can consume.
- Required scope: new import-light `loom.operations` module, strict plain-data records, redacted details, unsupported/not-implemented summaries, behavior-neutral compatibility projections, package import-boundary tests, unit tests, and contract tests.
- Required checkpoints: final public names recorded before implementation, no root `loom.__init__` export, no subsystem protocol ownership, no optional SDK or plugin discovery imports, and no user-visible behavior changes from compatibility adoption.
- Acceptance criteria: records round trip strictly, reject unknown fields, preserve redacted plain data, cover unsupported and checksum-style evidence examples, and prove `loom.operations` does not import higher-level subsystems.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/artifacts.py`, `src/loom/pipeline/stores/artifact_backends.py`, `src/loom/runs/models.py`, `src/loom/runs/transfer.py`, and `src/loom/diagnostics/models.py` already define overlapping adapter, status, diagnostic, support, and transfer verification records.
- Existing tests or harness behavior: package import-boundary tests live in `tests/package/test_import_boundaries.py`; public API tests live in `tests/package/test_public_api.py`; transfer evidence contracts live in `tests/contracts/test_transfer_evidence_contract.py`; backend diagnostic and artifact backend contracts already cover unsupported and unknown operation behavior.
- Import-boundary or dependency constraints: `loom.operations` may import only foundational stdlib and lower-level plain-data helpers such as `loom.serialization`; it must not import `loom.runs`, `loom.diagnostics`, `loom.pipeline`, `loom.cli`, `loom.plugins`, `loom.authority`, optional config dependencies, provider SDKs, or backend clients.

## In-Scope Work

- Add a single public module at `src/loom/operations.py`.
- Define the final public operation/evidence record names listed in the scope contract.
- Add strict `to_dict`/`from_dict` behavior, unknown-field rejection, non-empty string validation, enum coercion, immutable internal plain-data storage, and thawed serialized outputs.
- Add unsupported and not-implemented result/support constructors using the shared diagnostics and evidence records.
- Add redaction-safe details handling that accepts only plain data and never serializes backend clients, credentials, raw exceptions, tokens, or provider objects.
- Add behavior-neutral projection helpers at existing consumer edges only where import direction stays clean and serialized public behavior does not change.
- Add package, unit, and contract tests for the new public module, projection behavior, strict serialization, redaction, unsupported/not-implemented results, and import boundaries.

## Out-of-Scope Work

- Artifact payload materialization execution, local copy semantics, checksum file reads, or staging behavior.
- Backend payload handler methods, fake backend publish/materialize/upload/download/verify execution, or real provider SDKs.
- Bundle export/import materialization behavior, run catalog changes, preflight materialization probes, or CLI flags.
- Authority import, offline import, retry/timeout policy, cleanup, retention, garbage collection, and broad module reshuffling.
- Root `loom.__init__` exports for the new operation names.

## Assumptions

- Existing run exchange and artifact backend records may keep their public wrapper names in Phase 1 when replacing them would broaden the diff or change serialized shapes.
- Operation names remain consumer-owned non-empty strings rather than a universal enum; store capability operation enums stay in store-owned modules.
- Lowercase serialized enum values should match the style already used by run exchange and artifact backend records.
- Projection helpers are compatibility bridges, not ownership transfers for run exchange, diagnostics, or store protocols.

## Scope Contract

`loom.operations` is a public, import-light value-object module. The final public names for Phase 1 are:

| Public name | Kind | Contract |
| --- | --- | --- |
| `OperationValidationError` | error | Raised for invalid operation/evidence records and strict `from_dict` failures. |
| `OperationStatus` | enum | Serialized values: `succeeded`, `failed`, `blocked`, `unsupported`, `not_implemented`, `unknown`. Describes an operation result, not a planner action or lifecycle status. |
| `OperationSupport` | enum | Serialized values: `supported`, `unsupported`, `unknown`, `not_implemented`. Describes capability/support summaries before or instead of execution. |
| `OperationDiagnosticSeverity` | enum | Serialized values: `info`, `warning`, `error`. |
| `OperationEvidenceStatus` | enum | Serialized values: `proven`, `unproven`, `failed`, `unsupported`, `not_implemented`. Describes evidence/check outcomes. |
| `OperationAdapterIdentity` | record | Fields: `name`, `kind`, `version`. Mirrors existing adapter identity shape without importing `loom.runs`. |
| `OperationDiagnostic` | record | Fields: `code`, `message`, `severity`, `details`. Details must be plain data and redaction-safe. |
| `OperationEvidenceCheck` | record | Fields: `name`, `status`, `message`, `details`. Used for checksum, capability, preflight-readiness, and transfer-style checks. |
| `OperationEvidenceRecord` | record | Fields: `status`, `checks`, `adapter`, `details`; `adapter` may be `None` for local or subsystem-neutral evidence. |
| `OperationSupportRecord` | record | Fields: `operation`, `support`, `message`, `diagnostics`, `details`. This is the unsupported/not-implemented capability summary shape. |
| `OperationResult` | record | Fields: `operation`, `status`, `adapter`, `diagnostics`, `evidence`, `details`; includes class constructors for unsupported and not-implemented results. |

Public behavior boundaries:

- `operation` fields are non-empty strings owned by the calling subsystem. Do not add a global operation enum in Phase 1.
- All mappings must be plain structured data using existing serialization helpers. `to_dict()` returns mutable copies; constructors/from_dict freeze internal mappings.
- `from_dict()` rejects unknown fields, missing required fields, invalid enum values, non-plain details, and non-record entries in nested sequences.
- Redacted detail helpers may summarize exception class names and safe messages, but must not include raw exception objects, backend clients, credentials, tokens, unredacted URIs with secrets, or provider-specific SDK instances.
- Compatibility projections may convert existing run exchange, transfer evidence, artifact backend diagnostics, or backend operation results into these records. They must not make `loom.operations` import those modules and must not change existing serialized run/store/diagnostic public shapes in Phase 1.

## Design Impact

- Maintainability: the shared module removes duplicated status/diagnostic/evidence shapes while keeping subsystem protocols in their current owners.
- Extensibility: later materialization, fake backend, bundle/preflight, retry, and cleanup work can reuse the same result and evidence vocabulary without committing to provider-specific fields.
- Domain neutrality: operation and evidence examples must use generic adapters, checks, and payload operations, not domain-specific datasets, metrics, models, or cloud services.
- Source-tree boundaries: `loom.operations` sits with foundational public value objects and must remain lower than runs, diagnostics, pipeline stores, CLI, plugins, and authority modules.

## Future Compatibility

- Phase 2 can embed `OperationResult`, `OperationEvidenceRecord`, and `OperationSupportRecord` in store-owned materialization request/result records.
- Phase 3 can map fake backend payload operation outcomes to the same result/evidence shapes without adding provider SDKs.
- Phase 4 can project operation evidence into bundle and preflight records while preserving metadata-only defaults.
- Stage 19 retry policy can read `OperationStatus`, diagnostics, and evidence without Phase 1 encoding retry semantics.
- Stage 20 cleanup can consume derived evidence without treating materialized/staging facts as authoritative artifact truth.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add operation records directly to `loom.artifacts` | `loom.artifacts` must remain metadata-only and must not own payload operation behavior. |
| Put shared records under `loom.pipeline.stores` | Runs and diagnostics need to consume operation evidence without making stores the shared vocabulary owner. |
| Reuse run exchange records as the public shared contract | Existing names are run-transfer-specific and would pull `loom.runs` concepts into stores and diagnostics. |
| Add a global operation enum | Operation vocabularies are subsystem-owned; a global enum would either overfit Stage 16 or become a generic lifecycle framework. |
| Export the new records from `loom.__init__` in Phase 1 | The implementation plan explicitly keeps the root import cheap and avoids root exports for this new public path in Stage 16. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| New public `loom.operations` path starts before all Stage 16 consumers exist | Needed to prevent each phase from inventing incompatible status, diagnostic, and evidence records | The module imports subsystem code, exposes protocols, or grows beyond value objects/projections. |
| Existing wrapper records may remain alongside projections | Replacing all run/store diagnostics in one PR would broaden Phase 1 and risk behavior changes | Later phases show duplicated wrappers with identical serialized shapes and clean migration paths. |
| No schema version field on the shared records in Phase 1 | Existing nearby public value objects mostly rely on strict field contracts; adding versioning now would imply persisted-document ownership | Bundle or long-lived persisted operation evidence needs migration semantics. |

## Reviewability

- Expected PR size and shape: one new public module plus focused unit, contract, and package tests; optional small projection changes in existing run/store helper modules only.
- Files and areas to inspect: `src/loom/operations.py`, package import-boundary tests, operation evidence contract tests, any touched projection helper modules, and `__all__` exports for the new module.
- Scope-control checks: no root exports, no materialization execution, no backend payload methods, no bundle/preflight/CLI behavior, no optional dependencies, no network behavior, and no imports from higher-level Loom subsystems inside `loom.operations`.

## Implementation Steps

1. Add the import-light `loom.operations` value-object module with the final public names and strict serialization behavior from the scope contract.
2. Add unit and contract coverage for successful round trips, unknown-field rejection, invalid nested entries, redacted plain-data details, unsupported results, not-implemented results, checksum-style evidence, and adapter identity.
3. Add package API and import-boundary coverage proving `import loom.operations` is stable, typed, and does not import runs, diagnostics, pipeline, CLI, plugins, authority, optional config dependencies, or provider SDKs.
4. Add bounded projection helpers or behavior-neutral adoption in existing run-transfer or artifact-backend diagnostic/result paths only where serialized public behavior remains unchanged.
5. Run targeted tests, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_operations_api.py`, `tests/package/test_import_boundaries.py`, and any necessary public import assertions in existing package tests
- Required assertions or deferral reason: `loom.operations` imports cleanly, exposes the final public names through its own `__all__`, does not require optional dependencies, and does not import forbidden higher-level modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/test_operations.py` plus focused existing unit tests only if projection helpers touch run or store helper modules
- Required assertions or deferral reason: records validate inputs, freeze/thaw plain mappings, round trip, reject unknown fields, produce unsupported/not-implemented results, and preserve redacted details.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_operation_evidence_contract.py`; update `tests/contracts/test_transfer_evidence_contract.py`, `tests/contracts/test_artifact_store_backend_contract.py`, or `tests/contracts/test_backend_diagnostics_contract.py` only if compatibility projections are adopted there
- Required assertions or deferral reason: public serialized shapes are strict and provider-neutral; projections preserve existing public behavior while exposing operation/evidence records.

### Integration Suite

- Status: deferred
- Expected paths: none required for this phase
- Required assertions or deferral reason: Phase 1 adds value objects and behavior-neutral projections only. No execution, bundle, backend, preflight, or CLI integration behavior changes are in scope.

### E2E Suite

- Status: deferred
- Expected paths: none required for this phase
- Required assertions or deferral reason: no user workflow or CLI behavior changes are in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: the module must be dependency-light and no-network; optional dependency or provider SDK suites do not apply.

## Risks

- Public API overreach: too many fields, helpers, or exports could turn `loom.operations` into a lifecycle framework instead of a vocabulary module.
- Import cycles: projections must not make lower-level modules import runs, diagnostics, stores, CLI, plugins, or authority modules.
- Hidden behavior changes: replacing existing run/store public records too aggressively could alter serialized output or user-visible diagnostics.
- Redaction regressions: raw exceptions, credentials, or backend clients could leak if details are accepted without plain-data validation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/test_operations.py tests/contracts/test_operation_evidence_contract.py tests/package/test_operations_api.py tests/package/test_import_boundaries.py
uv run pytest tests/contracts/test_transfer_evidence_contract.py tests/contracts/test_artifact_store_backend_contract.py tests/contracts/test_backend_diagnostics_contract.py
git diff --check
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: add the new module first, add tests for the final public records, then add only narrowly bounded projections where they are behavior-neutral.
- Tests to run with each slice: run the new unit/contract/package tests after module work; rerun affected transfer/backend contract tests after projection changes.
- Decisions the executor must not revisit: final public record names, single `src/loom/operations.py` module shape, no root export, operation names as strings, no subsystem imports in `loom.operations`, and no materialization execution in Phase 1.
- Conditions that require stopping for the manager: a global operation enum appears necessary; materialization execution or backend protocols are needed to validate the records; projections would change existing serialized public behavior; `loom.operations` needs to import runs, diagnostics, pipeline, CLI, plugins, authority, optional dependencies, or provider SDKs; targeted tests require broad unrelated refactors.

## Refinement And Review Budget Status

- Planning draft pass: used
- Planning refine pass: used
- Phase implementation refinement: unused; one expanded-path pass remains available to the manager after implementation if targeted validation fails, coverage is missing, or review finds a bounded blocker
- PR review: unused; one automated review pass remains available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: refined and ready for implementation
- Implementation summary: `src/loom/operations.py` added with strict shared operation/evidence dataclasses and enums, redacted plain-data helpers, unsupported/not-implemented constructors, and strict `to_dict`/`from_dict` validation. Added phase-scoped unit, contract, and package tests in `tests/unit/loom/test_operations.py`, `tests/contracts/test_operation_evidence_contract.py`, `tests/package/test_operations_api.py`, and `tests/package/test_import_boundaries.py`.
- Implementation validation: `uv run pytest tests/unit/loom/test_operations.py tests/contracts/test_operation_evidence_contract.py tests/package/test_operations_api.py tests/package/test_import_boundaries.py` -> `64 passed`; `uv run pytest tests/contracts/test_transfer_evidence_contract.py tests/contracts/test_artifact_store_backend_contract.py tests/contracts/test_backend_diagnostics_contract.py` -> `8 passed`; `uv run ruff check src/loom/operations.py tests/unit/loom/test_operations.py tests/contracts/test_operation_evidence_contract.py tests/package/test_operations_api.py tests/package/test_import_boundaries.py` -> passed; `uv run pyright src/loom/operations.py tests/unit/loom/test_operations.py tests/contracts/test_operation_evidence_contract.py tests/package/test_operations_api.py` -> `0 errors`; `git diff --check` -> passed.
- Refinement summary: skipped; targeted validation, full PR validation, and coverage obligations passed without a bounded implementation blocker.
- Blocker-resolution summary: none
- PR preparation: `make validate-pr` passed; `make test-summary` passed with package `97 passed, 1 skipped`, unit `1171 passed, 7 skipped, 1 deselected`, contract `232 passed, 2 skipped`, integration `156 passed, 8 skipped, 13 deselected`, e2e `43 passed, 2 deselected`, and config-extra `440 passed, 1708 deselected`.
- Stack maintenance: root phase targeting `develop`; Phase 2 may stack on this branch if Phase 1 is not merged
- Remaining blockers: none
