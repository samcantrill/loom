# Phase 17 Execution Plan: Offline Evidence Writer

## Metadata

- Status: draft phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 17: Offline Evidence Writer`
- Branch: `codex/authority-offline-evidence`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-offline-evidence`
- Phase execution plan path: `docs/phases/authority-offline-evidence.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 17 - Offline Evidence Writer
- Stack predecessor: none; Phase 16 merged in PR #134 and is recorded in the plan
- Base branch: `develop` at `3b437a7`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 18 must reuse the manifest models and fixture evidence from this phase, but Phase 17 must not import evidence into authority truth.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed before phase work; no blocking findings remain.
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: completed by managing agent on 2026-05-12 after confirming execution facade, local-store, CLI, and materialization checksum boundaries
- Setup limitations: none; GitHub auth and current `develop` were available when the worktree was created.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Implement an explicit offline-first execution path that writes a versioned,
machine-readable evidence manifest for local runs without representing that
evidence as authority truth.

## Full-Plan Context

Phases 1-16 made online mutation service-backed, strict, and scheduler-ready.
Phase 17 adds the trusted local evidence shape that Phase 18 will import. The
phase must keep online authority failure behavior fail-closed and must leave
authority import, collision policy, and repository transaction behavior entirely
to Phase 18.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 16 is merged into `develop`
- Why this base branch is correct: all earlier v10 phases are recorded as merged and `develop` includes the Phase 16 merge metadata commit `3b437a7`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: no successor branch should depend on this branch unless Phase 18 starts before Phase 17 merges

## Source Phase Summary

- Goal: write explicit v10 offline-first evidence manifests for local execution.
- Required scope: offline-first mode selection, manifest schema, execution/config/provenance/plan/stage/output/artifact/log/resource facts, local event/audit log capture, diagnostics, and source labeling as non-authoritative evidence.
- Required checkpoints: online mode must not fall back to offline evidence, incomplete local evidence must be detected and labeled, and Phase 18 must have stable fixture manifests to reuse.
- Acceptance criteria: explicit offline runs produce versioned manifests; manifest data covers execution identity, stage order, terminal states, outputs, and artifact facts; diagnostics never label evidence as authority truth.

## Current Source And Harness Findings

- `AuthorityResolutionMode.OFFLINE_FIRST` and CLI parsing helpers already exist, but `loom run` does not expose resolution-mode options yet.
- `PipelineRunner` currently rejects raw `LocalRunStore` and requires an authority-backed serial store before any execution.
- `AuthorityBackedSerialRunStore` delegates local artifact/materialization writes to `LocalRunStore`; an offline run-store adapter can follow that path without importing server-private repository code.
- `LocalRunStore` already persists run status, plan, runtime metadata, config manifests, provenance documents, stage statuses, stage inputs, stage fingerprints, stage outputs, stage failures, logs, artifact indexes, and event logs.
- `ExecutionPlan`, status records, event records, `ResourceRequest`, and `ArtifactRef` already provide plain-data serialization suitable for a manifest contract.
- Phase 16 resource admission returns no decision when no coordination store is present; offline evidence can record requested resources without introducing a service resource lease.
- `loom.pipeline.execution.__init__` uses a lazy export facade; any new offline execution helpers exported there must update the exact package API test.
- `loom.pipeline.stores.materialization_read_models` already contains local-file URI/checksum helpers; Phase 17 should reuse the same URI/chksum conventions or small standard-library equivalents without importing CLI or authority server code.
- CLI result payloads are additive dataclasses, so offline evidence paths can be surfaced without changing successful run semantics for online mode.

## In-Scope Work

- Add offline evidence manifest value models in `src/loom/pipeline/offline_evidence.py` with strict schema version, kind, source label, diagnostics, run facts, plan facts, runtime/config/provenance facts, stage evidence, artifact facts, log references, resource requests, and audit events.
- Add a writer that reads a completed local run directory through public local-store methods and writes `offline-evidence/manifest.json` atomically.
- Add an explicit offline run-store adapter/factory, exported through the execution facade, so `PipelineRunner` can run local serial execution only when offline-first mode was selected.
- Preserve the existing `LocalRunStore` rejection for accidental direct runner use.
- Wire `loom run --offline-first` and `--authority-mode offline_first` to the offline adapter, and ensure default online mutation still resolves through authority.
- Add non-authoritative diagnostics/source metadata to offline run metadata and CLI JSON/text summaries.
- Add reusable complete and intentionally incomplete fixture manifest coverage for Phase 18.

## Out-of-Scope Work

- Offline import API, CLI import command, equivalence checker, authority repository import transaction, or collision policy.
- Best-effort import of legacy run directories or deferred-finalization envelopes.
- Treating offline evidence as authoritative service state.
- Online fallback to offline evidence after authority resolution or mutation failure.
- Remote artifact upload, object-store copying, or cryptographic attestation.
- New scheduler queues, resource fairness, or service-backed resource behavior.
- SLURM live/deferred-finalization behavior changes.

## Assumptions

- The first v10 evidence manifest can store local file artifact size and checksum when the artifact URI resolves to a readable local file; non-local or missing payloads are represented with diagnostics and metadata only.
- Offline evidence is written at the end of runner execution and after failure paths that produce a run directory, so the manifest can summarize both succeeded and failed terminal runs.
- Resume of an existing offline run may rewrite the same manifest after the resumed terminal state.
- Offline resource coordination evidence means recording requested stage resources and any local resource-admission metadata that exists, not acquiring authority leases.
- CLI options may remain hidden help options for this phase, matching the existing hidden resolver-mode option style.

## Scope Contract

Offline execution is explicit. `PipelineRunner` may accept an offline adapter that marks itself as non-authoritative evidence, but raw `LocalRunStore` remains rejected. The evidence manifest is plain JSON with a fixed schema version and `kind`, carries `state_source.authoritative: false`, validates known fields strictly, and records diagnostics instead of silently omitting missing required facts. Online authority-backed runs do not write offline manifests unless the caller explicitly selected offline-first mode. The neutral manifest module must not import `loom.cli`, `loom.authority._repository`, FastAPI, or server route modules.

## Design Impact

- Maintainability: manifest collection reads from existing local-store methods instead of parsing ad hoc file paths except for payload checksums and log existence.
- Extensibility: manifest versioning and diagnostics leave room for Phase 18 validation, later stronger checksums, and richer artifact stores.
- Domain neutrality: evidence records generic runs, stages, resources, artifacts, and logs without research-domain semantics.
- Source-tree boundaries: manifest models stay outside server-private repository modules; CLI only selects mode and reports evidence paths.

## Future Compatibility

Phase 18 should be able to import only this manifest contract, compare `kind`,
schema version, source label, run identity, stage order, terminal state, output
refs, artifact facts, and event order, and then reject ambiguous evidence before
mutating authority state.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Allow `PipelineRunner(LocalRunStore(...))` when authority is missing | That would weaken the v10 fail-closed online authority policy. |
| Reconstruct evidence by scanning arbitrary run directories only in Phase 18 | Phase 18 needs a stable v10-created evidence shape, not reverse-engineered local state. |
| Store only a human-readable summary | Import requires machine-validated identity, stage, output, artifact, and provenance facts. |
| Write evidence for every online authority run | The plan requires offline evidence to be explicit and non-authoritative, not an online fallback. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Initial payload verification is local-file oriented | Phase 17 does not move remote artifacts or define object-store contracts. | Remote artifact stores become importable evidence sources. |
| Offline resource evidence is descriptive, not enforcing service capacity | Offline mode has no authority resource service by definition. | A future local scheduler/offline lease design is scoped. |
| CLI offline mode may remain hidden help text | Resolver mode options already use hidden CLI affordances during v10 rollout. | User-facing docs/UX phase promotes offline workflows. |

## Reviewability

- Expected PR size and shape: one manifest/model module, one offline adapter/writer integration slice, additive CLI reporting, focused tests, and fixture manifests.
- Files and areas to inspect: `src/loom/pipeline/offline_evidence.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/pipeline/execution/__init__.py`, `src/loom/cli/authority.py`, `src/loom/cli/run.py`, package/unit/contract/integration/e2e tests, and any fixture directories.
- Scope-control checks: no authority repository import path, no Phase 18 import command, no online fallback, no legacy/deferred-finalization conversion, and no new scheduler behavior.

## Implementation Steps

1. Add strict offline evidence manifest models and read/write helpers in `src/loom/pipeline/offline_evidence.py` with local artifact checksum/size diagnostics.
2. Add `OfflineEvidenceRunStore`/`create_offline_evidence_run_store` that delegates to `LocalRunStore`, marks source as offline evidence, exposes manifest path/read helpers, and remains separate from raw `LocalRunStore`.
3. Teach `PipelineRunner` to skip authority capability admission only for the offline adapter and to write the offline manifest after terminal run state.
4. Wire CLI authority mode parsing for `loom run`, create the offline adapter only for explicit offline-first selection, and surface evidence manifest path/source in results.
5. Add unit and contract coverage for manifest validation, incomplete evidence diagnostics, event ordering, artifact facts, and no server-private imports.
6. Add integration/e2e coverage for a small offline-first local run and negative coverage proving online authority failures do not write offline evidence.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_execution_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: offline evidence exports remain phase-scoped; manifest code does not import CLI, FastAPI, authority repository, or server-private modules.

### Unit Suite

- Status: required
- Expected paths: new `tests/unit/loom/pipeline/test_offline_evidence.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/cli/test_run.py`
- Required assertions or deferral reason: strict manifest serialization, schema/kind validation, local payload checksum and missing-payload diagnostics, event ordering, incomplete evidence diagnostics, offline adapter admission behavior, and CLI offline-mode selection.

### Contract Suite

- Status: required
- Expected paths: new `tests/contracts/test_offline_evidence_contract.py`
- Required assertions or deferral reason: golden complete manifest shape, golden incomplete manifest diagnostics, compatibility rejection for wrong kind/schema, and Phase 18 fixture readability.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_execution.py`, new or existing CLI run integration tests
- Required assertions or deferral reason: offline-first local execution writes manifest with run/stage/output/artifact/event/resource facts; online authority-backed execution does not write offline evidence; failed offline runs still write diagnostic evidence.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_runs_e2e.py` or a focused e2e file
- Required assertions or deferral reason: deterministic `loom run --offline-first` smoke writes an evidence manifest and labels the result non-authoritative.

### Opt-In Suites

- Status: deferred
- Markers affected: external scheduler, large-artifact checksum, remote artifact store, and hosted service import tests.
- Required assertions or deferral reason: Phase 17 uses deterministic local filesystem coverage only; remote payload and import behavior are future work.

## Risks

- Accidentally allowing implicit offline fallback would violate the core v10 authority policy.
- Overly loose manifest validation would make Phase 18 import unsafe.
- Manifest writer path scanning could duplicate local-store validation if it bypasses store methods too broadly.
- Artifact checksum collection must avoid failing an otherwise valid run solely because a non-local payload cannot be inspected.

## Validation Commands

Targeted development commands:

```sh
uv run ruff check src/loom/pipeline/offline_evidence.py src/loom/pipeline/execution src/loom/cli tests/unit/loom/pipeline tests/unit/loom/cli tests/contracts/test_offline_evidence_contract.py tests/integration/pipeline tests/e2e/test_cli_runs_e2e.py tests/package/test_pipeline_execution_api.py tests/package/test_import_boundaries.py
uv run pyright src/loom/pipeline/offline_evidence.py src/loom/pipeline/execution src/loom/cli tests/unit/loom/pipeline tests/unit/loom/cli tests/contracts/test_offline_evidence_contract.py tests/integration/pipeline tests/e2e/test_cli_runs_e2e.py tests/package/test_pipeline_execution_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline tests/unit/loom/cli/test_run.py tests/contracts/test_offline_evidence_contract.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_cli_runs.py tests/e2e/test_cli_runs_e2e.py tests/package/test_pipeline_execution_api.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: manifest models/helpers first; offline adapter/factory second; runner terminal manifest write third; CLI wiring/reporting fourth; fixtures and full-suite coverage last.
- Tests to run with each slice: model unit/contract tests after manifest work; runner unit/integration tests after adapter/runner work; CLI unit/e2e tests after CLI wiring.
- Decisions the executor must not revisit: offline mode is explicit only; raw `LocalRunStore` remains rejected by `PipelineRunner`; no import transaction or authority repository mutation is in scope; manifest source is non-authoritative; manifest models live in the neutral pipeline layer, while runner/CLI wiring lives in execution/CLI.
- Conditions that require stopping for the manager: source review proves local status/plan/event data cannot identify a complete terminal run, or CLI offline selection conflicts with an already public option.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Final phase execution plan: refined by managing agent on 2026-05-12; confirmed the neutral manifest module boundary, lazy execution facade updates, explicit offline adapter/factory, and additive CLI reporting path.
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
