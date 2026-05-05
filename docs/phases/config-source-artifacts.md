# Phase 15 Execution Plan: Raw Snapshot Opt-In And Source Artifact Hardening

## Metadata

- Status: draft phase execution plan
- Feature focus: Configuration
- PR title: `Configuration - Phase 15: Raw Snapshot Opt-In And Source Artifact Hardening`
- Branch: `codex/config-source-artifacts`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-source-artifacts`
- Phase execution plan path: `docs/phases/config-source-artifacts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 15 - Raw Snapshot Opt-In And Source Artifact Hardening
- Stack predecessor: none; Phases 1-14 are merged.
- Base branch: `develop`
- Base commit: `043bea8a4bed7d30cee36851be81232c3f40facb`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, pre-submit blocker gate, PR preparation/submission, and passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: this phase hardens source artifact contracts, raw source snapshot policy, duplicate source handling, and future rebuild/security behavior.
- Successor dependency notes: Phase 16 may document final v1 source artifact behavior and broaden end-to-end coverage. Later run-store/security work may persist caller-returned raw snapshots, but this phase must not write run directories.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: pending for expanded path.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Sandboxed `gh auth setup-git` and `git fetch origin` were blocked by read-only writes to `~/.gitconfig` and `.git/FETCH_HEAD`; approved reruns succeeded. Local `develop` and `origin/develop` matched the assigned base commit. Initial sandboxed `git worktree add` could not create nested branch refs; approved `git worktree add` created the branch and worktree.
- Blockers: none known for the draft plan.

## Objective

Define explicit, security-first raw source snapshot behavior for config composition by adding a caller-owned opt-in that returns deduped raw local/file source payloads without writing them, while hardening default source artifact and manifest limitation metadata so metadata-only artifacts clearly state their rebuild limits.

## Full-Plan Context

Phases 1-14 established strict config loading, include/override composition, artifact-safe provenance, manifest/source metadata records, default resolver-output exclusion, and authored-composition fingerprints. Phase 15 is the raw snapshot and source artifact hardening layer after those defaults exist.

This phase must preserve accepted v1 decisions: `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only; and no plugin, remote, or global search include resolvers are added.

Future Phase 16 docs/e2e hardening, run-store persistence, CLI behavior, remote/plugin source support, and secret-aware security policies remain out of scope.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-14 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the v1 plan records Phase 14 as merged, and local/remote `develop` resolve to the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 15 PR is merged and no successor branch depends on `codex/config-source-artifacts`.

## Source Phase Summary

- Goal: define explicit raw snapshot behavior and harden source artifact limitations after default source metadata/hash records are already populated.
- Required scope: backward-compatible extension of Phase 13 source artifact records; manifest references to raw snapshot availability or explicit deferral; duplicate-source handling; explicit raw source snapshot opt-in, or clear deferral to run-store security policy.
- Required checkpoints: keep default source records metadata/hash-only; add manifest/provenance facts for raw snapshot availability and metadata-only rebuild limits; dedupe duplicate local/file raw payloads when opt-in is enabled; avoid run-store or filesystem writes.
- Acceptance criteria: default source metadata/hash records from Phase 13 remain backward-compatible; raw snapshot opt-in can reconstruct missing authored source files for supported local/file sources; duplicate raw payloads are deduped when raw snapshots are enabled.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py` owns the public `compose_config(...)`, `inspect_config_composition(...)`, `ComposedConfig`, and `ConfigCompositionInspection` shapes. `src/loom/config/compose.py` owns staged orchestration, `_build_source_artifacts(...)`, `_build_include_source_artifacts(...)`, `_build_recipe_source_artifacts(...)`, manifest metadata, artifact safety facts, and current `raw_source_bytes_included: False` security metadata. `src/loom/config/artifacts.py` owns `SourceArtifactRecord`, `CompositionManifest`, and strict `from_dict(...)` field validation. `src/loom/config/load.py` reads raw bytes to hash and decode base/overlay local files but currently returns only parsed data and `ConfigSource`. Include source facts flow through `src/loom/config/includes.py` records. `src/loom/config/fingerprints.py` consumes source artifact facts and records `raw_source_bytes_included: False` in the default fingerprint policy.
- Existing tests or harness behavior: contract coverage lives in `tests/contracts/test_config_artifact_contract.py` and `tests/contracts/test_config_composition_inspection_contract.py`; unit artifact/fingerprint/compose coverage lives in `tests/unit/loom/config/test_config_artifacts.py`, `test_config_fingerprints.py`, and `test_compose.py`; integration coverage for manifest/source records and fingerprint behavior lives in `tests/integration/config/test_compose_provenance.py` and `test_compose_fingerprints.py`; package/API and boundary coverage lives in `tests/package/test_config_api.py` and `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: production work should remain in `loom.config` plus existing shared hashing/serialization helpers. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project code, or add runtime dependencies.

## In-Scope Work

- Add an explicit config-level caller-owned raw snapshot opt-in on public composition APIs if the refined plan confirms the signature and naming. The draft default is `include_raw_source_snapshots: bool = False` or an equivalent keyword-only option on `compose_config(...)`, `inspect_config_composition(...)`, and catalog variants.
- Keep default source artifacts metadata/hash-only and backward-compatible: existing required fields remain valid, existing manifest source references remain usable, and default records contain no raw source bytes.
- Represent raw snapshot availability and limitation metadata in `SourceArtifactRecord.metadata`, `CompositionManifest.metadata`, provenance metadata, and inspection stage payloads using plain data. Defaults must say raw snapshots are disabled and metadata-only artifacts cannot reconstruct missing source files.
- When raw snapshots are enabled, return enough plain-data payload information to reconstruct supported local/file authored sources already loaded for base, overlay, and include records. Prefer a small structured raw snapshot record or additive metadata over embedding ambiguous ad hoc fields in many places.
- Dedupe duplicate raw payloads by content digest and reference the shared payload from each source artifact/manifest reference. Duplicate same-content base/overlay/include sources should not duplicate raw payload bytes/text in the returned artifact graph.
- Preserve artifact-safe fingerprint defaults. Raw snapshot payloads must not enter the default `artifact_safe_authored_composition_v1` fingerprint unless a separate opt-in policy is explicitly added and covered; this phase should prefer keeping the default fingerprint unchanged.

## Out-of-Scope Work

- Default raw source-byte persistence or default raw bytes in `source_artifacts`.
- Any run directory writes, run-store layout, store API, or persistence implementation.
- Remote sources, plugin sources, global search paths, custom include resolvers, or network behavior.
- CLI commands, CLI output, or public command-line flags.
- Pipeline resume integration or making `loom.pipeline` depend on config artifacts.
- Secret-aware raw snapshot classification, encryption, HMAC/keyed fingerprints, or resolved runtime-value persistence.
- `_copy_` support or broader composition semantics.

## Assumptions

- Raw source snapshot opt-in is viable because `loom.config` already reads supported local/file sources to compute digests; returning caller-owned plain data can remain persistence-free.
- Raw source payloads are trusted authored config bytes decoded as UTF-8 text for v1 YAML sources. If byte-perfect reconstruction needs binary payloads, stop and defer to run-store security policy rather than adding binary persistence semantics in `loom.config`.
- Recipe source artifacts remain metadata-only. Recipe expansion output may be referenced by digest/path facts, but raw callable/module source capture is out of scope.
- Metadata-only rebuild limitations are part of the public artifact contract and should be visible even when raw snapshots are disabled.
- Public API signature changes are allowed only if package tests document them and defaults preserve current caller behavior.

## Scope Contract

Phase 15 chooses config-level caller-owned raw snapshot opt-in, not run-store-owned deferral, provided the refined plan and implementation keep the default artifact graph raw-byte-free and persistence-free. The opt-in must be explicit, default to disabled, and return raw payload data to the Python caller only; `loom.config` must never write raw snapshots to disk or choose a storage location.

Default behavior:

- `compose_config(...)` and `inspect_config_composition(...)` continue to return source metadata/hash records and artifact-safe fingerprints without raw source bytes.
- Manifest/provenance/security metadata must explicitly record that raw snapshots are disabled, raw payloads are unavailable, and metadata-only artifacts can compare known source hashes but cannot reconstruct missing source files.
- Existing serialized `SourceArtifactRecord` and `CompositionManifest` payloads remain backward-compatible. Additive fields must be optional or contained in existing plain-data metadata unless a new versioned helper contract is deliberately added.

Opt-in behavior:

- Supported source kinds are local/file base, overlay, and include sources that `loom.config` directly reads as UTF-8 YAML. Unsupported recipe, remote, plugin, or future resolver sources must be marked unavailable with an explicit reason.
- The returned raw snapshot payload must include source content, content digest, size, encoding, and enough reference metadata to map each source artifact back to a deduped payload.
- Duplicate payloads must dedupe by content digest and size at minimum. If two different paths have identical content, source artifact references may point to one raw payload record.
- Raw snapshot records are caller-owned artifacts. The caller may persist them later, but this phase does not implement storage, deletion, encryption, or run-store policy.

Stop if implementation appears to require default raw bytes, run-store writes, remote/plugin source semantics, pipeline imports, resolved runtime values, secret classification, or an incompatible source artifact schema break.

## Design Impact

- Maintainability: centralize raw snapshot policy near existing source artifact population so metadata-only and opt-in behavior cannot drift.
- Extensibility: explicit availability/limitation metadata and deduped payload references leave a path for future run-store security policy without changing default source records.
- Domain neutrality: records describe generic authored config sources and payload availability, not project-specific experiment semantics.
- Source-tree boundaries: production changes stay in `loom.config`; pipeline, stores, CLI, plugin, network, and project packages remain independent.

## Future Compatibility

- Future run-store code can persist caller-returned raw snapshot payloads under its own security policy without `loom.config` writing files.
- Future CLI/docs can report whether a manifest is metadata-only or raw-snapshot-capable from manifest metadata alone.
- Future remote/plugin source work can add source-kind-specific availability reasons without weakening v1 local/file defaults.
- Future secret-aware policies can define encryption/redaction gates for raw snapshots while this phase preserves default raw-byte exclusion.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Persist raw snapshots by default | Violates the accepted security-first default and may leak authored secrets. |
| Defer all raw snapshot payloads to run-store policy | Would satisfy safety but leave Phase 15 acceptance for opt-in reconstruction and dedupe unimplemented even though a persistence-free caller-owned opt-in appears feasible. |
| Store raw bytes directly on every `SourceArtifactRecord` | Duplicates payloads and bloats source records; duplicate-source handling requires shared payload references. |
| Add remote/plugin source capture now | V1 explicitly has no plugin/remote/global source resolvers. |
| Feed raw snapshots into the default fingerprint | Changes Phase 14 default artifact-safe semantics and risks making raw payload opt-in affect default comparison unexpectedly. |
| Treat metadata-only source records as rebuildable | Would overclaim; metadata/hash records can verify known content but cannot reconstruct missing files. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Raw snapshots are caller-owned return data, not persisted run artifacts | Keeps `loom.config` persistence-free and avoids premature storage/security policy. | Run-store roadmap work defines how to persist, protect, and restore raw config snapshots. |
| Raw reconstruction is limited to supported local/file UTF-8 authored config sources | Matches v1 source support and current loader behavior. | Remote/plugin sources or binary/non-YAML source policies are deliberately designed. |
| Recipe source artifacts remain metadata-only | Recipe callables do not have safe raw source ownership in v1. | A future recipe provenance phase defines stable recipe source capture. |

## Reviewability

- Expected PR size and shape: focused artifact/API hardening under `loom.config`, with additive raw snapshot opt-in records, dedupe logic, limitation metadata, and targeted package/unit/contract/integration tests. No runner, store, CLI, pipeline, remote/plugin, or docs/e2e broadening unless tests need small comments.
- Files and areas to inspect: `src/loom/config/api.py` for public opt-in signatures and defaults; `src/loom/config/compose.py` for source artifact population, manifest/provenance metadata, dedupe, and stage payloads; `src/loom/config/artifacts.py` for any additive raw snapshot contract helper; `src/loom/config/load.py` only if raw bytes/text need to be carried from initial loads; `src/loom/config/includes.py` only if include records need raw payload plumbing; `src/loom/config/fingerprints.py` to confirm default fingerprint raw-byte exclusion remains unchanged. Test areas: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`, `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_compose.py`, `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`, `tests/integration/config/test_compose_provenance.py`, and a focused raw snapshot integration test file if useful.
- Scope-control checks: default calls contain no raw bytes; opt-in calls return raw payloads only to the caller; duplicate raw payloads dedupe; metadata-only limitations are explicit; default fingerprint remains artifact-safe; no run-store writes; no pipeline imports; no CLI behavior; no `_copy_`; no remote/plugin/global resolvers.

## Implementation Steps

1. Define the minimal raw snapshot option and plain-data contract, including disabled/default metadata, enabled payload references, unsupported-source reasons, and dedupe identity.
2. Carry supported local/file raw source text from load/include paths into the source artifact builder only when the opt-in is enabled, preserving metadata/hash-only defaults.
3. Add deduped raw payload records and manifest/provenance/inspection references that map each source artifact to payload availability or a limitation reason.
4. Harden default limitation metadata so metadata-only artifacts clearly state raw snapshots are unavailable and missing source reconstruction is impossible without opt-in payloads.
5. Add focused unit and contract coverage for record shape, disabled defaults, opt-in payload references, unsupported source reasons, and duplicate payload dedupe.
6. Add public compose/inspection integration coverage proving opt-in reconstruction for supported local/file sources and unchanged default artifact-safe behavior.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: public config signatures/export behavior intentionally include the opt-in option or helper contract; defaults remain source-compatible for existing callers; `loom.config` remains optional-dependency-safe; `loom.pipeline` does not import `loom.config`, manifests, source artifact records, or raw snapshot helpers.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_compose.py`, and focused raw snapshot helper tests if a helper module is introduced.
- Required assertions or deferral reason: default source records have no raw payloads; opt-in records include content/digest/size/encoding and source references for supported base/overlay/include sources; duplicate raw payloads dedupe; unsupported recipe sources are marked unavailable; metadata-only rebuild limitations are explicit; default artifact-safe fingerprint payload remains raw-byte-free.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: `SourceArtifactRecord`, `CompositionManifest`, and any new raw snapshot helper round-trip as plain data; old metadata/hash-only payloads still deserialize; unknown-field behavior remains deliberate; manifest references raw snapshot availability or disabled/unsupported reasons; inspection stage shape remains stable/additive; default contract asserts no raw bytes.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, and a focused file such as `tests/integration/config/test_compose_source_snapshots.py`.
- Required assertions or deferral reason: public `compose_config(...)` and `inspect_config_composition(...)` default to metadata-only artifacts; opt-in returns reconstructable local/file base, overlay, and include content; duplicate same-content sources share one payload; metadata-only artifacts report insufficient data for missing-source reconstruction; resolver outputs and raw bytes remain excluded from default fingerprint/manifest security facts unless explicitly opted in.

### E2E Suite

- Status: deferred.
- Expected paths: none for Phase 15.
- Required assertions or deferral reason: current e2e coverage is runner/pipeline oriented, and this phase must not add run-store, runner, CLI, or pipeline behavior. End-to-end persisted artifact behavior belongs to future run-store/security policy or Phase 16 documentation hardening, not this raw snapshot contract phase.

### Opt-In Suites

- Status: required for the new raw snapshot opt-in behavior; deferred for unrelated opt-in policies.
- Markers affected: no existing marker is expected unless the implementation adds one for config-extra coverage.
- Required assertions or deferral reason: raw snapshot opt-in behavior must be covered by package/unit/contract/integration tests above. Secret-aware raw snapshot policies, runtime-value persistence, remote/plugin sources, network behavior, CLI inspection, and store persistence are deferred.

## Risks

- Public API signature drift can break package tests or existing callers if the opt-in is not additive and defaulted.
- Raw payloads can leak into default artifacts or fingerprints if the source builder does not separate disabled and enabled paths.
- Dedupe can accidentally collapse distinct sources without preserving per-source references; tests need identical-content different-path cases.
- Metadata-only artifacts can overclaim rebuildability unless limitation fields are explicit and tested.
- Carrying raw source text from loaders can duplicate file reads or widen lower-level contracts unnecessarily. Prefer a narrow internal capture path and keep recipe sources metadata-only.
- Adding raw snapshot helpers to package exports can pull optional config dependencies or pipeline/store imports too early; package and import-boundary tests must cover this.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_fingerprints.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_source_snapshots.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with contract/unit tests for disabled/default metadata and opt-in record shape; then add the public opt-in keyword and internal plumbing; then add raw payload capture for base/overlay/include sources; then add dedupe and manifest/provenance references; finally add integration tests for reconstructability and default fingerprint exclusion.
- Tests to run with each slice: package/import-boundary tests after API changes; unit/contract artifact tests after record-shape changes; compose unit tests after source builder plumbing; integration provenance/fingerprint/raw snapshot tests after public compose wiring.
- Decisions the executor must not revisit: raw snapshots are explicit opt-in and default disabled; `loom.config` writes nothing; default source records remain metadata/hash-only and backward-compatible; default fingerprint policy remains artifact-safe and raw-byte-free; supported opt-in sources are local/file base, overlay, and include only; recipes are metadata-only; duplicate raw payloads dedupe; no pipeline/store/CLI/plugin/remote behavior; `_copy_` remains unsupported.
- Conditions that require stopping for the manager: satisfying acceptance appears to require default raw bytes, persistence, run-store paths, remote/plugin source semantics, pipeline imports, resolved runtime value persistence, secret classification/encryption policy, incompatible artifact schema breaks, or reopening the already-used v1 plan quality gate.
- Expanded-path refinement notes: pending. The refine pass should confirm the exact public option name/signature, raw snapshot helper shape, dedupe reference structure, and whether loader/include raw capture can remain small without duplicate file reads.

## Refinement And Review Budget Status

- Phase execution plan draft: used.
- Phase execution plan refine: pending for expanded path.
- Phase implementation refinement: unused.
- Pre-submit blocker gate: unused.
- User-authorized blocker-resolution pass: unused.
- PR body draft: unused.
- PR body refine: unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan:
- Implementation summary:
- Implementation validation:
- Refinement summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
