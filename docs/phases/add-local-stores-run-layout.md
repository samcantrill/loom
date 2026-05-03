# Phase 7 Execution Plan: Local Stores And Run Layout

## Metadata

- Status: draft phase execution plan
- Branch: `codex/add-local-stores-run-layout`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout`
- Phase execution plan path: `docs/phases/add-local-stores-run-layout.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 7 - Local Stores And Run Layout`
- Stack predecessor: none
- Base branch: `develop` at `e9407f427314f88aec0324946f125529d4cd93ce`
- Target branch: `develop`
- Merge eligibility: root phase PR; reviewable and merge-eligible only while targeting `develop`.
- Successor dependency notes: no successor branch is recorded yet. Keep this phase branch until the PR is merged and any future successor has been rebased or retargeted away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- Refine pass: pending
- Setup limitations: manager verified the control checkout was clean and synced to `origin/develop` at `e9407f427314f88aec0324946f125529d4cd93ce` before assignment. The draft pass created the worktree from local `develop`; an initial sandboxed `git worktree add` could not create the branch ref and was rerun with approved filesystem access. No remote synchronization or validation commands were run in this draft pass.
- Blockers: none

## Objective

Implement durable local artifact and run state without planning or executing stages. This phase creates the store protocols, local filesystem store implementations, atomic write helpers, artifact indexes, and the inspectable v0 run directory layout that later planning and execution phases will consume.

The phase should make run state plain-file inspectable and stable enough for future same-run-directory resume tests, while keeping stage fingerprint calculation, resume decisions, runner lifecycle, CLI behavior, remote stores, and cross-run cache reuse out of scope.

## Full-Plan Context

Phases 1 through 6 are merged into `develop`. They provide import-safe package boundaries, primitives, serialization, generic local I/O and codecs, trusted config composition and recipe expansion, object instantiation helpers, static pipeline specs, graph validation, stage context, stage protocol, and in-memory status records.

Phase 7 is the persistence boundary between those pure/static layers and later runtime behavior:

- Phase 7 persists local run/artifact state, but does not compute plans or run stages.
- Phase 8 will compute plans, selectors, stage fingerprints, and conservative resume decisions using the store state created here.
- Phase 9 will execute stages, validate outputs, drive lifecycle transitions, and use the run/artifact stores to persist real runs.
- Phase 10 will harden error reporting, interrupted-run behavior, docs, and extension contract tests after the local runtime exists.

Future-phase work that must remain out of scope includes actual stage execution, runner lifecycle helpers, resume planning, downstream invalidation, stage fingerprint calculation, selector behavior, output validation by a runner, CLI commands, remote stores, global run catalogs, cross-run cache reuse, subprocess/SLURM execution, lock managers unless tests expose a concrete need, and domain-specific artifact helpers.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phases 1 through 6 are merged into latest `develop`; the manager explicitly directed Phase 7 to start from `develop`, not from any old Phase 5 or Phase 6 branch.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is needed. If `develop` moves before PR preparation, the PR preparer should rebase or replay this branch onto updated `develop`, rerun validation, and record the stack maintenance.
- Branch cleanup constraints: this root branch can be deleted after merge only if no successor branch depends on it.

## Source Phase Summary

- Goal: implement durable local artifact/run state, atomic writes, and the inspectable local run directory layout without planning or executing stages.
- Required scope:
  - Add artifact and run store protocols.
  - Add local artifact and run stores.
  - Add atomic write helpers for JSON, text, bytes, replacement, directory creation, and unique temporary filenames.
  - Add run/artifact indexes using logical artifact keys of the form `stage.output`.
  - Add persistence helpers for run metadata, root status, plan, config snapshots, provenance documents, stage status, inputs, outputs, fingerprints, failures, logs, and artifact indexes.
  - Define the required local run layout under `run.json`, `status.json`, `plan.json`, `artifacts.json`, `config/`, `provenance/`, `stages/<stage>/`, and `artifacts/<stage>/`.
- Required checkpoints:
  - `ArtifactStore` exposes `save`, `load`, `register`, `exists`, and `validate`/checksum validation behavior.
  - `LocalArtifactStore` uses `CodecRegistry`, writes through temp paths and atomic moves where possible, computes stored-byte checksums, and returns typed `ArtifactRef`s.
  - `register` accepts already-written local files or file URIs, records checksums when requested, supports optional `codec_key`, and does not attempt generic serialization.
  - `RunStore` exposes run/stage directory resolution and read/write helpers for all Phase 7 state files.
  - Missing optional files return `None` where appropriate; missing required or corrupt state raises clear store errors.
- Acceptance criteria:
  - Artifacts save/load through JSON, text, and bytes codecs.
  - Already-written local files can be registered as artifacts with optional `codec_key`.
  - `ArtifactStore.load` fails clearly for codec-less artifacts unless an explicit codec is supplied.
  - Checksums are written and validated.
  - Run directory state is written atomically where possible.
  - Run status, plan, stage status, inputs, outputs, fingerprints, failures, artifact indexes, config snapshots, and provenance paths are read and written through the run store.
  - Local run directories contain the required v0 files and remain inspectable as plain JSON/YAML/text where applicable.
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 7; `docs/structure.md` sections "Stores and State", "Provenance and Resume", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 9, 10, and 11; `docs/features/run-store.md`, `docs/features/artifacts.md`, `docs/features/io.md`, `docs/features/serialization.md`, `docs/features/state.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/reliability.md`, and `docs/features/testing.md`.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/__init__.py` is currently an import-safe skeleton with no product behavior.
- `src/loom/artifacts.py` already provides frozen `ArtifactRef` values with `artifact_id`, `uri`, `artifact_type`, optional `codec_key`, schema version, checksum, fingerprint, producer stage, timestamp, metadata, and `to_dict`/`from_dict` helpers.
- `src/loom/io/codecs` already provides `Codec`, `CodecRegistry`, `create_default_codec_registry`, and JSON/text/bytes codecs with keys `json.v1`, `text.v1`, and `bytes.v1`.
- `src/loom/io/uris.py` already provides local path and `file://` conversion helpers; Phase 7 should reuse them for local refs instead of adding duplicate URI parsing.
- `src/loom/fingerprints.py` already provides digest validation, `hash_bytes`, and digest comparison helpers suitable for local file checksums.
- `src/loom/pipeline/status.py` already provides `RunStatusRecord` and `StageStatusRecord` serialization shapes. The run store should persist and read those records rather than inventing a parallel status model.
- `src/loom/pipeline/specs.py` validates stage/output names and already rejects output `path`; Phase 7 should allocate physical artifact paths in `LocalArtifactStore`, not in specs.
- `StageContext` currently has paths and plain-data config/provenance only. Store-backed context helper fields are not part of this phase.
- Package import-boundary tests assert cheap root imports and that `loom.io` does not import config or pipeline. Store behavior belongs under `loom.pipeline.stores` and must not be exported from root `loom`.
- Test suites currently include package, unit, contract, and integration tests. There is no e2e suite directory yet.

## In-Scope Work

- Add store-specific errors under `loom.pipeline.stores`.
- Add an `ArtifactStore` structural protocol and `LocalArtifactStore` implementation.
- Add a `RunStore` structural protocol and `LocalRunStore` implementation.
- Add atomic filesystem helpers for deterministic JSON, UTF-8 text, bytes, file replacement, idempotent directory creation, and unique temp paths in the target directory.
- Add checksum helpers for regular local files saved or registered through the local artifact store.
- Add artifact index helpers that serialize and deserialize logical `stage.output` keys to `ArtifactRef` values.
- Add run directory path helpers for root files, config files, provenance files, stage files, log files, and stage artifact directories.
- Add read/write helpers for `run.json`, root `status.json`, `plan.json`, root `artifacts.json`, config snapshots, provenance documents, stage status, stage inputs, stage outputs, stage fingerprints, stage failures, and stage provenance.
- Export the Phase 7 store API from `loom.pipeline.stores` without adding root `loom` exports.
- Add focused package, unit, contract, and integration tests for local stores, atomic writes, indexes, manual artifact registration, codec-less artifact behavior, checksums, and required layout.

## Out-of-Scope Work

- No actual stage execution or executor behavior.
- No `PipelineRunner`, lifecycle orchestration, output validation, or stage target instantiation.
- No resume planning, selectors, downstream invalidation, or stage fingerprint calculation.
- No remote stores, remote source registries, content-addressed global stores, run catalogs, or cross-run cache reuse.
- No functional CLI behavior.
- No broad refactors outside the store boundary.
- No lock manager unless Phase 7 tests expose a concrete race that atomic writes cannot handle.
- No stage-bound context helpers such as `context.artifact_store.save(...)`, `context.output_path(...)`, or `context.register_artifact(...)`; those belong with runner/context wiring in Phase 9.

## Assumptions

- Store modules can use only the standard library plus existing project dependencies already introduced by earlier phases. No new runtime dependency is expected for Phase 7.
- Local run IDs, stage names, output names, and relative artifact paths must be path-safe even when earlier spec validation has already run; stores should protect filesystem boundaries independently.
- Local refs should be stored as `file://` URIs for future remote-store compatibility.
- `ArtifactStore.save()` owns serialization through codecs; `ArtifactStore.register()` owns metadata/checksum registration for content written by project code.
- `ArtifactStore.load()` requires either `ref.codec_key` or an explicit codec key. Existence and checksum validation still apply to codec-less artifacts.
- `LocalArtifactStore` should write regular files under the run's `artifacts/<stage>/` directory by default. External local registration, if supported in Phase 7, must be explicit and tested; otherwise it should fail clearly.
- Directory artifacts may be registered and checked for existence, but tree checksums and generic directory loading remain deferred.
- `RunStore` persists documents it is given. It does not compose configs, redact secrets, capture provenance, compute fingerprints, or decide stage/run lifecycle transitions.
- YAML config snapshots can be persisted as supplied text or plain-data snapshots converted with existing config/YAML support; the refine pass should choose the smallest API that avoids making stores own config composition.
- Atomic writes are best-effort for local filesystems: write temp file in the same directory, flush, fsync where practical, replace, and fsync the parent directory where practical.

## Decision-Complete Contract

This draft locks the Phase 7 behavioral contract and module ownership. The refine pass should make exact method signatures, record wrapper names, and path-normalization helpers decision-complete before implementation begins.

Public behavior:

- `loom.pipeline.stores` is the public package for store protocols, local implementations, store errors, atomic helpers as needed, and index helpers.
- Store APIs must accept and return existing value objects where they exist, especially `ArtifactRef`, `RunStatusRecord`, and `StageStatusRecord`.
- Persisted machine state must be deterministic, plain JSON with trailing newlines where practical. Config snapshots and logs remain plain YAML/text files where applicable.
- Missing optional documents should be distinguishable from corrupt documents. Corrupt JSON or invalid serialized records should raise a store-specific corrupt-state error with the path.
- Artifact logical keys use `stage.output`. Duplicate logical keys are rejected when constructing or updating an index.
- `LocalArtifactStore.save()` must allocate safe paths under `artifacts/<stage>/`, encode with a registered codec, write atomically, compute a `sha256` checksum for regular files, and return an `ArtifactRef`.
- `LocalArtifactStore.register()` must normalize a local path or file URI, verify allowed location policy, compute or validate checksums for regular files when possible, preserve optional `codec_key`, and return an `ArtifactRef` without rewriting content.
- `LocalArtifactStore.load()` must validate expected artifact type, resolve codec from the ref or explicit argument, verify local existence and checksum when present, and decode bytes through the selected codec.
- `LocalRunStore` must centralize all local run layout paths so later phases do not format paths independently.

Required local run layout:

```text
run.json
status.json
plan.json
artifacts.json
config/raw.yaml
config/overlays.yaml
config/cli_overrides.yaml
config/resolved.yaml
config/resolved.redacted.yaml
config/recipe_manifest.json
provenance/environment.json
provenance/git.json
provenance/command.json
provenance/dependencies.json
stages/<stage>/status.json
stages/<stage>/inputs.json
stages/<stage>/outputs.json
stages/<stage>/fingerprint.json
stages/<stage>/failure.json
stages/<stage>/provenance.json
stages/<stage>/logs/stdout.log
stages/<stage>/logs/stderr.log
artifacts/<stage>/
```

Error behavior:

- Unsafe run IDs, stage names, output names, artifact paths, or temp paths must fail before filesystem writes.
- Unsupported remote URIs must fail clearly in local stores.
- Missing codec keys on generic load must fail as artifact/store errors that name the artifact and state how to supply a codec.
- Checksum mismatch must fail validation and should include the artifact URI and expected/actual digest.
- Atomic helper failures should clean up the temp path where possible and raise a store-specific atomic-write error.

## Design Impact

- Maintainability: centralizing local persistence in store modules keeps runner, planner, CLI, and value objects from duplicating path and serialization policy.
- Extensibility: structural protocols plus local implementations leave room for remote artifact stores, run catalogs, and alternate persistence backends after v0 without changing artifact refs or status records.
- Domain neutrality: stores persist generic artifacts, statuses, configs, provenance, and plain metadata only; no domain-specific artifact types, schemas, datasets, models, or reports enter `loom`.
- Source-tree boundaries: serialization remains separate from filesystem I/O; I/O remains the codec/source layer; stores own persistent state; planning and execution remain deferred.

## Future Compatibility

- Remote stores should be able to implement the same protocols later while preserving `ArtifactRef` URI semantics.
- Same-run-directory resume in Phase 8 should consume the run store's status, plan, fingerprint, output, and artifact-index helpers rather than scanning ad hoc paths.
- Local execution in Phase 9 should use store path helpers for contexts, logs, config/provenance persistence, stage outputs, failures, and artifact directories.
- CLI/status/artifact inspection in later phases should be possible by reading plain JSON/YAML/text files without importing user project code.
- Optional lock files and run catalogs remain possible because the layout reserves stable root files and avoids global mutable state.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement runner lifecycle in Phase 7 | Stage execution and lifecycle orchestration belong to Phase 9; Phase 7 should be reviewable as persistence only. |
| Implement resume planning in the run store | Resume policy belongs to Phase 8 planning and must consider fingerprints, selectors, status, and artifact validation together. |
| Add a lock manager immediately | The v0 plan accepts atomic writes first; locks are revisited only if tests expose a concrete race. |
| Let stages or specs choose physical output paths | Output path templates are deferred; Phase 7 should allocate safe local artifact paths in `LocalArtifactStore`. |
| Store only opaque blobs or binary state | The v0 run layout must remain human-inspectable as plain JSON/YAML/text. |
| Add remote store support now | Remote stores are explicitly deferred and would widen review scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No lock manager in v0 Phase 7 | Atomic writes and conservative later resume validation keep the first local store implementation small. | Atomic-write, interrupted-run, or concurrent-run tests expose a concrete race or partial-state ambiguity. |
| No tree checksum for directory artifacts | Regular-file checksums satisfy the required v0 save/register/load path; directory checksum policy needs a separate design. | Directory artifacts become part of resume correctness or downstream users need integrity verification for directory outputs. |
| No cross-run artifact catalog or content-addressed cache | The v0 plan requires same-run-directory resume only and local inspectability first. | Phase 8/9 local resume is stable and a later plan adds global discovery or cache reuse. |

## Reviewability

- Expected PR size and shape: one bounded store-layer PR with new modules under `src/loom/pipeline/stores/`, export updates in `src/loom/pipeline/stores/__init__.py`, and focused tests under package/unit/contract/integration suites.
- Files and areas to inspect:
  - `src/loom/pipeline/stores/errors.py`
  - `src/loom/pipeline/stores/atomic.py`
  - `src/loom/pipeline/stores/artifact_store.py`
  - `src/loom/pipeline/stores/local_artifacts.py`
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/stores/indexes.py`
  - `src/loom/pipeline/stores/__init__.py`
  - package import-boundary tests
  - unit tests for stores, atomic helpers, and indexes
  - contract tests for store protocols
  - integration tests for local layout and codec-backed artifact operations
- Scope-control checks:
  - no `PipelineRunner`, planner, selector, executor, or CLI behavior
  - no top-level `loom.__init__` exports
  - no remote store implementation
  - no new heavyweight runtime dependency
  - no stage execution or target construction

## Implementation Steps

1. Add store error types and public exports under `loom.pipeline.stores`.
2. Add atomic filesystem helpers with targeted tests for JSON/text/bytes writes, replacement, cleanup on failure, directory creation, and temp name uniqueness.
3. Add artifact index helpers that serialize/deserialize logical `stage.output` keys and `ArtifactRef` values.
4. Add `ArtifactStore` protocol and `LocalArtifactStore` path allocation, save, register, load, existence, checksum, and validation behavior.
5. Add `RunStore` protocol and `LocalRunStore` root/stage/config/provenance/log/artifact path helpers.
6. Add `LocalRunStore` read/write helpers for run metadata, statuses, plan, stage files, failures, artifact index, config snapshots, and provenance documents.
7. Add package and contract tests for public store exports and structural protocol compatibility.
8. Add integration tests that create a synthetic run directory, save/load/register artifacts, write/read state files, and assert the required layout without planning or executing stages.
9. Run targeted package, unit, contract, and integration checks during implementation, then leave final `make validate-pr` and `make test-summary` for PR preparation as required.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py` and existing import-boundary tests if public exports change.
- Required assertions or deferral reason: `loom.pipeline.stores` exports the Phase 7 protocols, local stores, errors, and index helpers; root `loom` still does not import or export stores; importing `loom.io` still does not import `loom.pipeline`.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_atomic.py`, `tests/unit/loom/pipeline/stores/test_indexes.py`, `tests/unit/loom/pipeline/stores/test_local_artifacts.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, and `tests/unit/loom/pipeline/stores/test_store_errors.py`.
- Required assertions or deferral reason: atomic writes are deterministic and clean up temp files; unsafe paths are rejected; checksums are computed and validated; codec-backed JSON/text/bytes saves round-trip; codec-less loads fail clearly without explicit codec; manual registration preserves content and metadata; run store read/write helpers handle optional, required, and corrupt files correctly.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` or split store contract files if clearer.
- Required assertions or deferral reason: downstream-style store implementations satisfy `ArtifactStore` and `RunStore` structurally without inheritance; `LocalArtifactStore` and `LocalRunStore` satisfy their protocols; contract tests avoid domain-specific artifacts.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py` or `tests/integration/test_local_stores.py`.
- Required assertions or deferral reason: local run directory creation produces required directories and path helpers; artifact store and run store work together under one temp run directory; root and stage status, plan, inputs, outputs, fingerprints, failures, config snapshots, provenance files, logs, and artifact indexes can be written and read through store APIs; no planner or stage execution is involved.

### E2E Suite

- Status: deferred
- Expected paths: none for this phase.
- Required assertions or deferral reason: Phase 7 has no runner, CLI, or end-to-end pipeline execution surface. E2E coverage starts when Phase 9 wires local execution and public runtime entry points.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected.
- Required assertions or deferral reason: no remote, network, SLURM, subprocess, slow, or optional-dependency behavior is in scope for Phase 7.

## Risks

- Store protocols can become too broad if they absorb planning or runner lifecycle decisions. Keep them to persistence and path helpers.
- Atomic writes differ subtly by filesystem. Tests should assert observable local behavior and cleanup rather than platform-specific internals.
- Allowing external local registration too freely can break reproducibility. The default should be conservative and explicit.
- Persisted JSON wrapper shapes can drift from existing `ArtifactRef`, `RunStatusRecord`, and `StageStatusRecord` serialization. Tests should round-trip through existing value objects.
- Config snapshot helpers could accidentally make stores own config composition or redaction. Stores should only persist supplied content.
- Adding exports from `loom.pipeline` or root `loom` could break import-boundary expectations. Exports should stay in `loom.pipeline.stores`.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - errors, exports, and protocols first
  - atomic helpers and tests
  - artifact index helpers and tests
  - local artifact store and tests
  - local run store and tests
  - integration coverage for combined layout
- Tests to run with each slice: run the nearest unit test file for the edited module, then `make test-package`, `make test-contract`, and `make test-integration` after public exports and integration helpers are in place.
- Decisions the executor must not revisit:
  - no stage execution, planning, selectors, resume, CLI, remote stores, or lock manager by default
  - physical local artifact paths are owned by `LocalArtifactStore`
  - run layout path formatting is centralized in `LocalRunStore`
  - logical artifact keys are `stage.output`
  - codec-less artifacts cannot be generically loaded without an explicit codec
- Conditions that require stopping for the manager:
  - exact store protocol cannot cover the Phase 7 acceptance criteria without changing earlier public value objects
  - atomic-write tests prove a lock manager is required to satisfy the phase
  - existing Phase 6 status/spec contracts conflict with required persisted layout
  - final targeted suites expose failures that would require implementing Phase 8 or Phase 9 behavior

## Handoff Notes For `phase-execution-plan-refine`

- Finalize exact method signatures for `ArtifactStore`, `LocalArtifactStore`, `RunStore`, `LocalRunStore`, and artifact index helpers.
- Decide the minimal config snapshot API for YAML/text persistence without making stores compose or redact configs.
- Decide whether external local artifact registration is supported in Phase 7 and, if so, the explicit flag and tests.
- Decide the precise error class hierarchy under `loom.pipeline.stores.errors`.
- Decide JSON wrapper shapes for `run.json`, `plan.json`, `artifacts.json`, stage input/output/fingerprint/failure/provenance documents, and whether to add small dataclasses or keep wrapper helpers internal.
- Confirm package export expectations before implementation changes `tests/package/test_pipeline_api.py` or adds a new package API test.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; recorded in the `plan: add phase execution plan` commit for this artifact.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: none required at draft time; root phase targets `develop`.
- Remaining blockers: none.
