# Phase 15 Execution Plan: Raw Snapshot Opt-In And Source Artifact Hardening

## Metadata

- Status: final phase execution plan
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
- Workflow path rationale: this phase adds a security-sensitive public opt-in and hardens source artifact limitations while preserving default artifact-safe behavior.
- Successor dependency notes: Phase 16 may document final v1 source artifact behavior and broaden end-to-end coverage. Later run-store/security work may persist caller-returned raw snapshots, but this phase must not write run directories.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in draft commit `3d746e2` (`plan: add phase execution plan`).
- Refine pass: completed by `loom_phase_planner` in this artifact.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Sandboxed `gh auth setup-git` and `git fetch origin` were blocked by read-only writes to `~/.gitconfig` and `.git/FETCH_HEAD`; approved reruns succeeded during setup. Local `develop` and `origin/develop` matched the assigned base commit. Initial sandboxed `git worktree add` could not create nested branch refs; approved `git worktree add` created the branch and worktree.
- Blockers: none.

## Objective

Define explicit, security-first raw source snapshot behavior for config composition by adding a Python API caller-owned opt-in that returns deduped raw local/file source payloads without writing them, while hardening default source artifact and manifest limitation metadata so metadata-only artifacts clearly state their rebuild limits.

## Full-Plan Context

Phases 1-14 established strict config loading, include/override composition, artifact-safe provenance, manifest/source metadata records, default resolver-output exclusion, and authored-composition fingerprints. Phase 15 is the raw snapshot and source artifact hardening layer after those defaults exist.

This phase preserves accepted v1 decisions: `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only; and no plugin, remote, or global include resolvers are added.

Future Phase 16 docs/e2e hardening, run-store persistence, CLI behavior, remote/plugin source support, secret-aware security policies, and exact runtime-value replay remain out of scope.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-14 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the v1 plan records Phase 14 as merged, and local/remote `develop` resolved to the assigned base commit during setup.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 15 PR is merged and no successor branch depends on `codex/config-source-artifacts`.

## Source Phase Summary

- Goal: define explicit raw snapshot behavior and harden source artifact limitations after default source metadata/hash records are already populated.
- Required scope: backward-compatible extension of Phase 13 source artifact records; manifest references to raw snapshot availability or explicit deferral; duplicate-source handling; explicit raw source snapshot opt-in, or clear deferral to run-store security policy.
- Required checkpoints: keep default source records metadata/hash-only; add manifest/provenance facts for raw snapshot availability and metadata-only rebuild limits; dedupe duplicate local/file raw payloads when opt-in is enabled; avoid run-store or filesystem writes.
- Acceptance criteria: default source metadata/hash records from Phase 13 remain backward-compatible; raw snapshot opt-in can reconstruct missing authored source files for supported local/file sources; duplicate raw payloads are deduped when raw snapshots are enabled.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/api.py` owns public `compose_config(...)`, `inspect_config_composition(...)`, `compose_config_with_catalog(...)`, `ComposedConfig`, and `ConfigCompositionInspection`. `src/loom/config/compose.py` owns staged orchestration, source artifact population, manifest/provenance metadata, artifact safety facts, and current `raw_source_bytes_included: False` metadata. `src/loom/config/artifacts.py` owns `SourceArtifactRecord`, `CompositionManifest`, `ConfigFingerprintRecord`, and strict `from_dict(...)` field validation. `src/loom/config/load.py` already reads raw bytes once to hash and decode base/overlay local files. `src/loom/config/includes.py` reads include sources and records include site metadata. `src/loom/config/fingerprints.py` records `raw_source_bytes_included: False` in the default fingerprint policy.
- Existing tests or harness behavior: package/API and boundary coverage lives in `tests/package/test_config_api.py` and `tests/package/test_import_boundaries.py`; contract coverage lives in `tests/contracts/test_config_artifact_contract.py` and `tests/contracts/test_config_composition_inspection_contract.py`; unit artifact/fingerprint/compose coverage lives in `tests/unit/loom/config/test_config_artifacts.py`, `test_config_fingerprints.py`, and `test_compose.py`; integration coverage for source records, provenance, and fingerprints lives in `tests/integration/config/test_compose_provenance.py` and `test_compose_fingerprints.py`.
- Import-boundary or dependency constraints: production work stays in `loom.config` plus existing shared hashing/serialization helpers. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project code, or add runtime dependencies.

## In-Scope Work

- Add the explicit Python API opt-in keyword `include_raw_source_snapshots: bool = False` to `compose_config(...)`, `inspect_config_composition(...)`, and `compose_config_with_catalog(...)`.
- Keep `include_raw_source_snapshots` keyword-only: after `recipe_catalog` on `compose_config(...)` and `inspect_config_composition(...)`, and after `overrides` on `compose_config_with_catalog(...)`.
- Add an internal orchestration keyword of the same name to `src/loom/config/compose.py` so public wrappers do not invent a second option name.
- Add a public, plain-data raw snapshot helper shape in `src/loom/config/artifacts.py` and export it from `loom.config` only if the implementation needs callers/tests to inspect the typed helper directly.
- Keep default source artifacts metadata/hash-only and backward-compatible: existing required fields and strict unknown-field behavior remain valid; raw content is never added as a field on `SourceArtifactRecord` or `CompositionManifest`.
- Add source-artifact, manifest, provenance, and inspection metadata that says whether raw snapshots are disabled, available, or unavailable for each source reference. This metadata may include payload IDs and reasons, but not raw content.
- When opt-in is enabled, return enough caller-owned plain data on `ComposedConfig` and `ConfigCompositionInspection` to reconstruct supported local/file authored sources already loaded for base, overlay, and include records.
- Dedupe duplicate raw payloads by content digest plus size and have each source reference point at the shared payload ID.
- Keep unsupported recipe source artifacts metadata-only with an explicit unavailable reason.
- Preserve the default artifact-safe fingerprint payload and digest behavior: raw snapshot payload content, payload IDs, and raw availability metadata must not change the default `artifact_safe_authored_composition_v1` fingerprint.

## Out-of-Scope Work

- Default raw source-byte persistence or default raw bytes in `source_artifacts`, manifests, provenance metadata, fingerprint records, or run artifacts.
- Any run directory writes, run-store layout, store API, or persistence implementation.
- Remote sources, plugin sources, global search paths, custom include resolvers, or network behavior.
- CLI commands, CLI output, or public command-line flags.
- Pipeline resume integration or making `loom.pipeline` depend on config artifacts.
- Secret-aware raw snapshot classification, encryption, HMAC/keyed fingerprints, or resolved runtime-value persistence.
- `_copy_` support or broader composition semantics.

## Assumptions

- A config-level caller-owned opt-in is viable because `loom.config` already reads supported local/file sources to compute digests and parse UTF-8 YAML. Deferring all payloads to run-store policy is rejected for this phase because the acceptance criteria require opt-in reconstruction and dedupe when feasible without persistence.
- Raw source payloads are trusted authored YAML bytes decoded as UTF-8 text. If byte-perfect non-UTF-8 or binary capture appears necessary, stop and defer that part to run-store/security policy rather than widening v1 config semantics.
- Recipe source artifacts remain metadata-only because recipe callables and expanded outputs do not have safe raw source ownership in v1.
- Metadata-only rebuild limitations are part of the public artifact contract and should be visible even when raw snapshots are disabled.
- Public API signature changes are acceptable only as additive, defaulted, keyword-only parameters that preserve existing caller behavior.

## Scope Contract

Phase 15 keeps implementation in scope and chooses a config-level caller-owned raw snapshot opt-in, not full deferral to run-store policy.

Public API contract:

- `compose_config(config_path, overlays=(), overrides=(), recipe_catalog=None, *, include_raw_source_snapshots: bool = False) -> ComposedConfig`
- `inspect_config_composition(config_path, overlays=(), overrides=(), recipe_catalog=None, *, include_raw_source_snapshots: bool = False) -> ConfigCompositionInspection`
- `compose_config_with_catalog(config_path, *, recipe_catalog: RecipeCatalog, overlays=(), overrides=(), include_raw_source_snapshots: bool = False) -> ComposedConfig`
- Passing a non-bool `include_raw_source_snapshots` must fail with `ConfigValidationError`.
- Existing positional call compatibility must hold; the new option must not allow accidental positional use.

Raw snapshot helper shape:

- Add a plain-data helper named `RawSourceSnapshotBundle` or an equivalent clearly named artifact helper. It must contain `schema_version`, `enabled`, `payloads`, `references`, and `metadata`.
- Each payload record must contain `payload_id`, `content`, `content_digest`, `size_bytes`, `encoding`, and optional plain metadata. `encoding` is exactly `utf-8` for v1.
- Each source reference must contain a source artifact reference (`kind`, `order`, `path`, `content_digest`, `size_bytes`), `availability`, `payload_id`, and `reason`.
- `availability` values are exactly `disabled`, `available`, or `unavailable`.
- Disabled references use reason `not_requested` and no `payload_id`.
- Available local/file base, overlay, and include references point to a deduped payload ID.
- Unsupported recipe references use reason `unsupported_source_kind`.
- Unavailable local/file references, if encountered because capture was not possible without a second incompatible schema path, must use a specific reason such as `raw_capture_unavailable` and no payload.
- `payload_id` must be stable from content digest plus size, for example `sha256:<digest>:<size_bytes>`. Different source paths with identical content may share the same payload.

Default behavior:

- Raw source bytes are disabled by default.
- `SourceArtifactRecord` remains metadata/hash-only and backward-compatible; no raw content field is added.
- `CompositionManifest`, provenance metadata, inspection stages, and source artifact metadata may report raw snapshot disabled/unavailable facts, but must not contain raw payload content.
- The default artifact-safe fingerprint payload and digest remain unchanged in semantic scope and exclude raw bytes, raw payload IDs, and raw snapshot availability metadata.
- `loom.config` performs no persistence and writes no run-store files.

Opt-in behavior:

- Supported source kinds are local/file base, overlay, and include sources that `loom.config` directly reads as UTF-8 YAML.
- Opt-in raw payloads are returned on `ComposedConfig` and `ConfigCompositionInspection` only, not embedded in manifest/source/fingerprint persistence contracts.
- Duplicate payloads dedupe by content digest plus size. All source references must remain present even when payload content is shared.
- Raw snapshot records are caller-owned return data. A caller may persist them later under a separate policy, but this phase does not implement storage, deletion, encryption, or run-store decisions.

Loader/include capture contract:

- Keep existing `load_config(...)` behavior and return shape compatible for tests and callers.
- If raw capture needs a new internal helper, make `load_config(...)` a wrapper over it instead of changing all callers.
- Avoid broad duplicate reads: base, overlay, and include raw text should be captured from the same read/decode operation already needed for parsing when `include_raw_source_snapshots=True`.
- Include expansion may gain a narrow capture option and return internal raw snapshot candidates alongside include records; do not add raw text to public include site records.
- The source artifact builder should consume internal capture candidates and source/include records; it should not reopen all source files after composition.

Stop if implementation appears to require default raw bytes, run-store writes, remote/plugin source semantics, pipeline imports, resolved runtime values, secret classification/encryption, incompatible source artifact schema breaks, or changing the default artifact-safe fingerprint policy.

## Design Impact

- Maintainability: centralizes raw snapshot policy near existing source artifact population while keeping raw content out of manifest, source record, provenance, and fingerprint persistence contracts.
- Extensibility: explicit availability reasons and deduped payload references leave a path for future run-store security policy without changing default source-record contracts.
- Domain neutrality: records describe generic authored config sources and payload availability, not project-specific experiment semantics.
- Source-tree boundaries: production changes stay in `loom.config`; pipeline, stores, CLI, plugin, network, and project packages remain independent.

## Future Compatibility

- Future run-store code can persist caller-returned raw snapshot payloads under its own security policy without `loom.config` choosing paths or writing files.
- Future CLI/docs can report whether a manifest is metadata-only or raw-snapshot-capable from manifest metadata alone.
- Future remote/plugin source work can add source-kind-specific availability reasons without weakening v1 local/file defaults.
- Future secret-aware policies can define encryption/redaction gates for raw snapshots while this phase preserves default raw-byte exclusion.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Persist raw snapshots by default | Violates the accepted security-first default and may leak authored secrets. |
| Defer all raw snapshot payloads to run-store policy | Would leave Phase 15 opt-in reconstruction and dedupe acceptance criteria unimplemented even though a persistence-free caller-owned opt-in is feasible. |
| Store raw bytes directly on every `SourceArtifactRecord` | Breaks the metadata/hash-only source record contract and duplicates payloads. |
| Put raw payloads in `CompositionManifest` | Makes a persistence contract carry raw authored config bytes and conflicts with default artifact-safety expectations. |
| Add remote/plugin source capture now | V1 explicitly has no plugin/remote/global source resolvers. |
| Feed raw snapshots into the default fingerprint | Changes Phase 14 default artifact-safe semantics and risks making raw payload opt-in affect default comparison unexpectedly. |
| Treat metadata-only source records as rebuildable | Overclaims capability; metadata/hash records can verify known content but cannot reconstruct missing files. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Raw snapshots are caller-owned return data, not persisted run artifacts | Keeps `loom.config` persistence-free and avoids premature storage/security policy. | Run-store roadmap work defines how to persist, protect, and restore raw config snapshots. |
| Raw reconstruction is limited to supported local/file UTF-8 authored config sources | Matches v1 source support and current loader behavior. | Remote/plugin sources or binary/non-YAML source policies are deliberately designed. |
| Recipe source artifacts remain metadata-only | Recipe callables and generated outputs do not have safe raw source ownership in v1. | A future recipe provenance phase defines stable recipe source capture. |

## Reviewability

- Expected PR size and shape: focused API/artifact hardening under `loom.config`, with additive raw snapshot helper records, opt-in plumbing, dedupe logic, limitation metadata, and targeted package/unit/contract/integration tests. No runner, store, CLI, pipeline, remote/plugin, or docs/e2e broadening.
- Files and areas to inspect: `src/loom/config/api.py` for public keyword-only signatures, defaults, validation, and return fields; `src/loom/config/compose.py` for opt-in propagation, source artifact population, manifest/provenance metadata, dedupe, and stage payloads; `src/loom/config/artifacts.py` for raw snapshot helper contracts; `src/loom/config/load.py` only for narrow raw capture helper work; `src/loom/config/includes.py` only for include raw capture plumbing; `src/loom/config/fingerprints.py` to confirm default fingerprint exclusion remains unchanged.
- Scope-control checks: default calls contain no raw bytes; opt-in calls return raw payloads only on the caller-facing snapshot bundle; duplicate raw payloads dedupe; metadata-only limitations are explicit; default fingerprint remains artifact-safe; no run-store writes; no pipeline imports; no CLI behavior; no `_copy_`; no remote/plugin/global resolvers.

## Implementation Steps

1. Add package/API tests that lock the keyword-only `include_raw_source_snapshots` signatures, bool validation, default compatibility, and import-boundary expectations.
2. Add the raw snapshot helper contract and focused unit/contract tests for disabled, available, unavailable, and duplicate-reference shapes.
3. Add narrow internal raw capture for base/overlay/include loads while preserving `load_config(...)` compatibility and avoiding post-composition source rereads.
4. Thread the opt-in through public wrappers and internal composition, build deduped raw snapshot bundles, and add disabled/unavailable metadata references without raw content in source records or manifests.
5. Harden provenance, manifest, and inspection metadata so metadata-only artifacts state rebuild limitations and opt-in artifacts point to payload IDs without embedding content.
6. Add integration coverage for public default behavior, opt-in reconstructability, duplicate dedupe, unsupported recipe metadata-only behavior, manifest/provenance references, and fingerprint raw-byte exclusion.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: public signatures expose keyword-only `include_raw_source_snapshots: bool = False`; existing positional usage remains valid; non-bool option values raise `ConfigValidationError`; any exported helper remains optional-dependency-safe; `loom.pipeline` does not import `loom.config`, manifests, source artifact records, or raw snapshot helpers.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_compose.py`, `tests/unit/loom/config/test_config_fingerprints.py`, and focused raw snapshot helper tests if split out.
- Required assertions or deferral reason: default source records have no raw payload content; disabled snapshot bundle has no payloads and uses `not_requested` references; opt-in records include `content`, `content_digest`, `size_bytes`, `encoding`, and source references for supported base/overlay/include sources; duplicate raw payloads dedupe by digest plus size; unsupported recipe sources are marked `unavailable` with `unsupported_source_kind`; metadata-only rebuild limitations are explicit; default artifact-safe fingerprint payload remains raw-byte-free and ignores raw snapshot bundle content/IDs.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: `SourceArtifactRecord`, `CompositionManifest`, and the raw snapshot helper round-trip as plain data; old metadata/hash-only source artifact and manifest payloads still deserialize; strict unknown-field behavior remains deliberate for persistence contracts; manifest/provenance references report raw snapshot disabled/available/unavailable states without raw content; inspection stage shape is stable/additive; default contract asserts no raw bytes in source artifacts, manifest, provenance, or fingerprint records.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, and a focused file such as `tests/integration/config/test_compose_source_snapshots.py`.
- Required assertions or deferral reason: public `compose_config(...)` and `inspect_config_composition(...)` default to metadata-only artifacts; opt-in returns reconstructable local/file base, overlay, and include content; duplicate same-content sources share one payload while preserving per-source references; recipe artifacts stay metadata-only with explicit unavailable reason; metadata-only artifacts report insufficient data for missing-source reconstruction; manifest/provenance references expose availability without payload content; resolver outputs and raw bytes remain excluded from default fingerprint/manifest security facts unless explicitly returned in the caller-owned snapshot bundle.

### E2E Suite

- Status: deferred.
- Expected paths: none for Phase 15.
- Required assertions or deferral reason: current e2e coverage is runner/pipeline oriented, and this phase must not add run-store, runner, CLI, or pipeline behavior. End-to-end persisted artifact behavior belongs to future run-store/security policy or Phase 16 documentation/e2e hardening, not this raw snapshot contract phase.

### Opt-In Suites

- Status: required for the new raw snapshot opt-in behavior; deferred for unrelated opt-in policies.
- Markers affected: no existing marker is expected unless the implementation adds one for config-extra coverage.
- Required assertions or deferral reason: raw snapshot opt-in behavior must be covered by package/unit/contract/integration tests above. Secret-aware raw snapshot policies, runtime-value persistence, remote/plugin sources, network behavior, CLI inspection, and store persistence are deferred.

## Risks

- Public API signature drift can break existing callers if the new option is not keyword-only and defaulted.
- Raw payloads can leak into default artifacts, manifests, provenance, or fingerprints if disabled and enabled paths are not kept separate.
- Dedupe can accidentally collapse distinct source references unless tests cover identical-content different-path base/overlay/include cases.
- Metadata-only artifacts can overclaim rebuildability unless limitation fields are explicit and tested.
- Carrying raw source text from loaders can duplicate reads or widen lower-level contracts unnecessarily; keep capture internal and opt-in.
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

- Safe implementation slices: first lock public signatures and helper contracts with tests; then add internal raw capture while preserving `load_config(...)`; then thread the opt-in through composition and include expansion; then add deduped bundle/reference metadata; finally add integration coverage for reconstructability, manifest/provenance references, and fingerprint exclusion.
- Tests to run with each slice: package/import-boundary tests after API changes; unit/contract artifact tests after helper-shape changes; compose/load/include unit tests after raw capture plumbing; provenance/fingerprint/source snapshot integration tests after public compose wiring.
- Decisions the executor must not revisit: config-level opt-in remains in scope; the keyword is `include_raw_source_snapshots`; raw snapshots are default disabled; `loom.config` writes nothing; source records and manifests remain metadata/hash-only; default fingerprint policy remains artifact-safe and raw-byte-free; supported opt-in sources are local/file base, overlay, and include only; recipes are metadata-only; duplicate raw payloads dedupe by content digest plus size; no pipeline/store/CLI/plugin/remote behavior; `_copy_` remains unsupported.
- Conditions that require stopping for the manager: satisfying acceptance appears to require default raw bytes, persistence, run-store paths, remote/plugin source semantics, pipeline imports, resolved runtime value persistence, secret classification/encryption policy, incompatible artifact schema breaks, changing the default artifact-safe fingerprint policy, or reopening the already-used v1 plan quality gate.

## Refinement And Review Budget Status

- Phase execution plan draft: used.
- Phase execution plan refine: used for expanded path.
- Phase implementation refinement: unused.
- Pre-submit blocker gate: unused.
- User-authorized blocker-resolution pass: unused.
- PR body draft: unused.
- PR body refine: unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `3d746e2` (`plan: add phase execution plan`).
- Final phase execution plan: refined to final/scope-complete status in this pass; locks config-level raw snapshot opt-in, public keyword/signatures, raw snapshot helper shape, default no-raw behavior, dedupe/reference rules, loader/include capture constraints, suite obligations, executor handoff notes, and stop conditions.
- Implementation summary:
- Implementation validation:
- Refinement summary: expanded-path refine pass completed; no product code changed; no PR opened; full validation intentionally not run.
- PR preparation:
- Stack maintenance:
- Remaining blockers: none.
