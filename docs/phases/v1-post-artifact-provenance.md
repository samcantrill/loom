# Phase 4 Execution Plan: Artifact-Safe Ordering And Provenance

## Metadata

- Status: refined phase execution plan
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 4: Artifact-Safe Ordering And Provenance`
- Branch: `codex/v1-post-artifact-provenance`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-artifact-provenance`
- Phase execution plan path: `docs/phases/v1-post-artifact-provenance.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 4. Artifact-Safe Ordering And Provenance
- Stack predecessor: none; Phases 1-3 have merged into `develop`, including Phase 3 blocker-fix PR #49 and metadata PR #50.
- Base branch: `develop` / `origin/develop` at `0efbcc3` (`docs: record v1-post phase 3 merged (#50)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review and checks because the target is `develop`.
- Workflow path: expanded path
- Successor dependency notes: Phase 5 depends on this phase's artifact-safe provenance and fingerprint contract before changing pipeline/run-store persistence. Phase 6 may add residual-risk coverage only after these defaults are stable.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blocking findings remain.
- Plan quality gate loop budget: initial review used, automated refinement used, confirmation review used.
- Draft pass: completed by `loom_phase_planner` in this commit.
- Refine pass: completed by `loom_phase_planner` in this commit; expanded path was selected because this phase changes schema, provenance, artifact/fingerprint contracts, and execution ordering.
- Setup limitations: none blocking. `gh auth status` required approved network access after sandboxed status reported an invalid token; approved check succeeded, `gh auth setup-git` succeeded, and `git fetch origin` succeeded.
- Blockers: none after the expanded-path refinement pass.

## Objective

Make default config artifacts, provenance, manifests, and fingerprints artifact-safe by construction and by execution order: artifact-safe records must be built before runtime resolver execution, new provenance writes must use schema version 2 without a top-level resolved-runtime digest, and legacy schema-version-1 provenance reads must remain supported.

## Full-Plan Context

V1-post closes contract gaps found after the v1 Phase 16 merge. Phases 1-3 have already cleaned import/docs boundaries and structured config diagnostics. This phase resolves the central artifact-safety gap: default composition records currently allow runtime interpolation to happen before provenance/manifest/fingerprint construction and `ConfigProvenance` still emits `resolved_fingerprint`. Phase 5 owns pipeline/run-store manifest persistence and default resolved-config persistence removal; Phase 6 owns recipe residual-risk coverage. Those future persistence, runner, and residual-risk changes must remain out of this PR.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the manager selected `develop`; Phases 1, 2, and 3 plus metadata PR #50 are merged; local setup fetched origin and the worktree was created from `develop` at `0efbcc3`.
- Retarget/rebase plan after predecessor merge: none needed because there is no predecessor.
- Branch cleanup constraints: this branch may be deleted after merge only if no successor branch has been created from it.

## Source Phase Summary

- Goal: make default config artifacts, provenance, manifests, and fingerprints artifact-safe by construction and by execution order.
- Required scope: build artifact-safe source artifacts, unresolved/redacted config, fingerprint records, provenance metadata, and composition manifest before runtime resolver execution; preserve resolver expressions and resolver paths; write schema-version-2 provenance with `artifact_fingerprint`; keep schema-version-1 legacy read compatibility; keep `ComposedConfig.fingerprint` artifact-safe; add plaintext secret override docs warning.
- Required checkpoints: no new default resolved-runtime digest, no emitted top-level `resolved_fingerprint` on new provenance writes, environment value changes do not affect default fingerprints or provenance-emitted digests, and resolver expressions remain present in artifact-safe records.
- Acceptance criteria: contract and integration tests prove schema-version-2 writes, legacy schema-version-1 reads, artifact-before-resolver ordering, resolver-expression preservation, and env-value independence; docs include a concrete plaintext override warning such as `+auth.token=...` and recommend `oc.env`.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py` owns compose ordering, stage records, provenance/manifest/fingerprint construction, and currently builds source artifacts, fingerprint records, provenance, and manifest after `resolve_interpolation(...)` and `validate_top_level_fields(...)`; it also computes `build_resolved_fingerprint(validated)`. `src/loom/config/provenance.py` owns `ConfigProvenance`, currently with `SCHEMA_VERSION = 1` and a required top-level `resolved_fingerprint`. `src/loom/config/fingerprints.py` already builds the artifact-safe fingerprint record and stores its payload in record metadata. `src/loom/config/artifacts.py` owns strict `CompositionManifest` and `ConfigFingerprintRecord` serialization. `src/loom/config/api.py` owns the public `ComposedConfig.fingerprint` surface.
- Existing tests or harness behavior: package API coverage is in `tests/package/test_config_api.py`; provenance/manifest contracts are in `tests/contracts/test_config_artifact_contract.py`; public provenance/fingerprint integration coverage is in `tests/integration/config/test_compose_provenance.py` and `tests/integration/config/test_compose_fingerprints.py`; resolver behavior is in `tests/integration/config/test_compose_resolvers.py`; docs/example checks live under `tests/integration/docs/`.
- Import-boundary or dependency constraints: keep `loom.config` domain-neutral and persistence-free; do not add `loom.pipeline` imports or run-store writes; do not broaden optional dependencies beyond existing config extras.

## In-Scope Work

- Reorder composition so source artifacts, unresolved/redacted artifact config, artifact-safe fingerprint records, provenance metadata, and the composition manifest are created before runtime resolver execution. Resolver scanning that preserves expression text may still run before artifact construction; resolver execution must not.
- Preserve resolver expressions and resolver paths in artifact-safe records, including provenance metadata, manifest metadata, and fingerprint metadata.
- Change new `ConfigProvenance` writes to `schema_version: 2`, add top-level `artifact_fingerprint`, and omit top-level `resolved_fingerprint`.
- Keep legacy `schema_version: 1` provenance reads for payloads with top-level `resolved_fingerprint`; normalize the legacy value only to `metadata.legacy_resolved_fingerprint`, without re-emitting it from new writes.
- Store artifact-safe fingerprint facts in `metadata.fingerprint` or manifest/fingerprint records instead of a resolved-runtime digest.
- Preserve public `ComposedConfig.fingerprint` as the artifact-safe digest from the default artifact-safe fingerprint record.
- Add docs warning against plaintext secret overrides with an example such as `+auth.token=...`; recommend environment resolvers such as `${oc.env:AUTH_TOKEN}` for secrets.

## Out-of-Scope Work

- Secret-aware opt-in runtime fingerprints.
- Default resolved config persistence.
- Broadening the runtime resolver allow-list beyond the current supported resolver surface.
- Phase 5 pipeline/run-store persistence changes, including `PipelineRunner`, `config/composition_manifest.json`, and default `resolved.yaml` removal.
- Phase 6 recipe residual-risk coverage.
- CLI behavior, `_copy_`, plugin or remote resolvers, sweeps, resolved-runtime replay, and any v2 workflow.

## Assumptions

- Schema-version-2 provenance may add fields needed for artifact safety but should keep existing source, override, recipe-count, and metadata facts where possible.
- Schema-version-1 compatibility is read-only: old payloads deserialize, but normal new `to_dict()` output uses schema version 2 and does not contain top-level `resolved_fingerprint`.
- If a public constructor signature must change, the executor may add compatibility defaults or a clearly named optional legacy field, but must not require callers to provide resolved-runtime fingerprints for new provenance.
- Artifact-safe record construction may use unresolved/redacted data and resolver scan results before runtime resolver execution; runtime validation still returns the in-memory `resolved` config to callers.

## Scope Contract

New public compose results must expose the same high-level surfaces: `resolved`, `unresolved`, `redacted`, `provenance`, `manifest`, `fingerprint_records`, and `fingerprint`. The public `fingerprint` remains the artifact-safe digest. Artifact-safe records are records built from authored composition data, redacted/unresolved config, resolver expression records, source artifacts, recipe manifest payloads, and override facts before runtime resolver execution. Runtime-resolved values remain available only through the in-memory `resolved` result.

New `ConfigProvenance` documents must use this schema-version-2 top-level contract:

- `schema_version: 2`
- top-level `artifact_fingerprint`
- no top-level `resolved_fingerprint`
- artifact-safe fingerprint facts in `metadata.fingerprint` or existing manifest/fingerprint records

The `artifact_fingerprint` value must equal the default artifact-safe `ConfigFingerprintRecord.digest` and `ComposedConfig.fingerprint`. Legacy `schema_version: 1` provenance documents containing top-level `resolved_fingerprint` must still read successfully. The legacy resolved digest may be exposed only as `metadata.legacy_resolved_fingerprint` for compatibility inspection; schema-version-2 writes must not emit it at top level or under a renamed default runtime-fingerprint field. Schema-version-2 readers should remain strict about unknown top-level fields, including rejecting `resolved_fingerprint` if it appears in a schema-version-2 payload.

Default artifacts must not include resolved environment values or any digest derived from the full runtime-resolved config. Resolver expressions, resolver paths, and authored resolver tokens must remain present in provenance metadata, manifest metadata, and fingerprint record metadata where those records already expose resolver facts. Stop if implementation appears to require changing pipeline persistence, expanding resolver support, or adding a public resolved-runtime fingerprint policy.

## Design Impact

- Maintainability: separates artifact construction from runtime interpolation so future persistence can consume safe records without depending on ordering assumptions hidden in `compose.py`.
- Extensibility: introduces a schema-versioned provenance transition path that can later support explicit opt-in runtime fingerprint policies without confusing them with default artifact fingerprints.
- Domain neutrality: keeps provenance/fingerprint facts about authored config structure and resolver expressions, not domain-specific runtime object identity.
- Source-tree boundaries: confines work to `loom.config`, config docs, and config tests; `loom.pipeline` and run-store modules remain untouched.

## Future Compatibility

- Phase 5 can persist composition manifests as plain data without inheriting a resolved-runtime digest from config provenance.
- Future explicit runtime fingerprinting must use a separate opt-in policy label and security warning rather than reusing the artifact-safe config fingerprint.
- Schema-version-2 provenance keeps strict top-level fields so later additivity should happen through schema versions or metadata-scoped extension points.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep emitting `resolved_fingerprint` and document it as legacy | Conflicts with the accepted artifact-safe default and continues to expose a runtime-derived digest by default. |
| Build artifacts after runtime interpolation but redact resolved values | Ordering would still make artifacts depend on runtime execution and risks accidental resolved-value leakage. |
| Treat environment values as part of the default config fingerprint | Makes fingerprints unstable across runtime environments and violates the artifact-safe authored-composition policy. |
| Broaden resolver support while touching ordering | Resolver allow-list changes are a separate security decision and are explicitly out of scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Legacy schema-version-1 provenance compatibility remains in the reader. | Existing provenance artifacts with `resolved_fingerprint` must remain inspectable. | A documented deprecation window allows dropping schema-version-1 compatibility. |
| Runtime-resolved fingerprint policy remains absent. | The phase intentionally removes default runtime digests and defers opt-in secret-aware policy design. | Users need explicit runtime replay or selected resolved-subtree fingerprints with security controls. |

## Reviewability

- Expected PR size and shape: moderate config-only PR with one ordering refactor, provenance schema transition, focused contract/integration tests, and a small docs update.
- Files and areas to inspect: `src/loom/config/compose.py`, `src/loom/config/provenance.py`, `src/loom/config/fingerprints.py` only if metadata placement changes, `src/loom/config/api.py` only if public construction/export compatibility changes, `tests/contracts/test_config_artifact_contract.py`, `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, `tests/integration/config/test_compose_resolvers.py`, `tests/package/test_config_api.py` if exports/signatures change, and `docs/features/config.md`.
- Scope-control checks: no pipeline/run-store files, no CLI, no `_copy_`, no plugin/remote resolver support, no default resolved-config persistence, no new heavyweight dependency, and no future-phase recipe residual-risk work.

## Implementation Steps

1. Introduce the provenance schema-version-2 contract while preserving schema-version-1 read compatibility for top-level `resolved_fingerprint` through `metadata.legacy_resolved_fingerprint`.
2. Reshape compose ordering so artifact-safe source artifacts, unresolved/redacted config, resolver records, fingerprint records, provenance metadata, and manifest are built before runtime resolver execution; keep runtime validation for the returned `resolved` config after that boundary.
3. Wire new provenance writes to use `artifact_fingerprint` from the artifact-safe fingerprint record and remove default resolved-runtime digest construction/emission from config provenance.
4. Ensure provenance/manifest/fingerprint metadata expose artifact-safe fingerprint facts and resolver expression records without resolved resolver outputs.
5. Add the plaintext override warning docs and focused tests for schema transition, ordering, env-value independence, and resolver-expression preservation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py` and, if needed, import-boundary checks in `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: confirm public `loom.config` imports, `ComposedConfig.fingerprint`, and package-level optional import behavior remain stable. If `ConfigProvenance` construction or exports change in a public-observable way, add explicit coverage for compatibility defaults and the schema-version-2 constructor/write path.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_compose.py`, `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_config_fingerprints.py`, and `tests/unit/loom/config/test_config_provenance.py`.
- Required assertions or deferral reason: environment value changes do not affect default `ComposedConfig.fingerprint`, `ConfigProvenance.artifact_fingerprint`, provenance `metadata.fingerprint`, manifest metadata, or default fingerprint record metadata; schema-version-2 `ConfigProvenance.to_dict()` includes top-level `artifact_fingerprint` and omits top-level `resolved_fingerprint`; legacy read compatibility stores old top-level `resolved_fingerprint` only in `metadata.legacy_resolved_fingerprint`; no resolved environment value appears in default provenance/manifest/fingerprint records.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`.
- Required assertions or deferral reason: schema-version-2 provenance writes round-trip with top-level `artifact_fingerprint`; top-level `resolved_fingerprint` is absent from new writes; schema-version-1 payloads containing `resolved_fingerprint` read successfully and expose it only through `metadata.legacy_resolved_fingerprint`; schema-version-2 unknown top-level fields remain rejected, including top-level `resolved_fingerprint`; composition manifests carry artifact-safe fingerprint records and metadata without runtime-resolved digests.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, and targeted resolver coverage in `tests/integration/config/test_compose_resolvers.py` if needed.
- Required assertions or deferral reason: public `compose_config(...)` and `inspect_config_composition(...)` produce artifact-safe records before resolver execution, preserve resolver expressions and paths in provenance/manifest/fingerprint metadata, resolve runtime values only for in-memory `resolved`, and keep artifact/provenance/manifest/fingerprint payloads stable when environment variable values change. Include a sentinel environment-value-change case that proves the emitted artifact fingerprint and all provenance-emitted digests are unchanged while `resolved` changes.

### E2E Suite

- Status: deferred.
- Expected paths: `tests/e2e/test_config_composition_public_api.py` only if compose API behavior needs end-to-end confirmation.
- Required assertions or deferral reason: this phase is config composition/provenance only and explicitly excludes pipeline/run-store persistence, `PipelineRunner`, and default resolved-config persistence removal. If runner behavior or end-to-end workflow wiring appears necessary, stop for the manager instead of expanding e2e scope.

### Opt-In Suites

- Status: required for config-extra and docs/example checks that cover changed wording or examples.
- Markers affected: config optional dependency markers and docs integration markers used by existing config documentation tests.
- Required assertions or deferral reason: docs or example checks should cover the warning not to pass plaintext secrets through overrides, including a concrete `+auth.token=...`-style example, and recommend `oc.env` environment resolvers for secrets. Raw source snapshot opt-in behavior and runtime fingerprint opt-ins are not the target unless existing config-extra suite coupling requires them.

## Risks

- Ordering refactor could accidentally make `resolved` unavailable to callers or change validation timing.
- Schema transition could break callers that construct `ConfigProvenance` directly if compatibility defaults are not handled carefully.
- Metadata could retain a resolved-runtime digest under a new name; tests must search serialized provenance/manifest/fingerprint payloads, not only top-level fields.
- Resolver expressions embedded in recipes or overrides could be lost if only the final unresolved tree is checked.
- Docs could imply plaintext overrides are forbidden; this phase should warn and recommend safer env resolver usage without changing accepted override behavior.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_fingerprints.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_provenance.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_resolvers.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: provenance schema transition first, compose ordering second, metadata/fingerprint cleanup third, docs/tests last.
- Tests to run with each slice: contract and provenance unit tests after provenance changes; focused compose/fingerprint unit tests after ordering/fingerprint changes; integration resolver/provenance/fingerprint tests after compose wiring; package tests after any public signature/export change and again before handoff.
- Decisions the executor must not revisit: no default resolved-runtime fingerprint, no top-level `resolved_fingerprint` on new writes, legacy resolved fingerprints normalize only to `metadata.legacy_resolved_fingerprint`, no expanded resolver allow-list, no runtime fingerprint opt-ins, no `PipelineRunner` default resolved-config persistence removal, no pipeline/run-store persistence changes, and no future-phase recipe or CLI scope.
- Conditions that require stopping for the manager: implementation needs to touch `loom.pipeline`, run-store modules, or `PipelineRunner`; preserve new writes with top-level `resolved_fingerprint`; invent an opt-in runtime fingerprint policy; broaden resolver support; make environment values affect default artifact/provenance digests; or break legacy schema-version-1 provenance reads.
- Expanded-path refinement notes: completed. The final plan pins the schema-version-2 field contract, artifact-before-runtime-resolver-execution acceptance tests, and all suite obligations before executor work begins.

## Refinement And Review Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` in this pass.
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with `plan: add phase execution plan`.
- Final phase execution plan: completed expanded-path refine pass in this commit.
- Implementation summary: implemented artifact-before-runtime-resolver composition ordering, schema-version-2 `ConfigProvenance` writes with top-level `artifact_fingerprint`, legacy schema-version-1 `resolved_fingerprint` read normalization to `metadata.legacy_resolved_fingerprint`, artifact-safe fingerprint metadata in provenance/manifest records, and docs/tests for plaintext secret override warnings and environment-independent artifact digests.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_provenance.py tests/contracts/test_config_artifact_contract.py` passed with 22 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_compose.py` passed with 17 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_resolvers.py` passed with 21 tests after a test-only manifest metadata comparison fix.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_fingerprints.py` passed with 18 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/integration/docs/test_v0_python_examples.py` passed with 15 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/e2e/test_config_composition_public_api.py` passed with 1 test.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check src/loom/config tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_provenance.py tests/contracts/test_config_artifact_contract.py tests/integration/config/test_compose_provenance.py tests/integration/docs/test_v0_python_examples.py tests/e2e/test_config_composition_public_api.py` passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pyright src/loom/config tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_provenance.py tests/contracts/test_config_artifact_contract.py tests/integration/config/test_compose_provenance.py tests/integration/docs/test_v0_python_examples.py tests/e2e/test_config_composition_public_api.py` passed.
  - `make validate-pr` passed: Ruff, Pyright, default harness `439 passed, 11 skipped`, config-extra harness `358 passed, 445 deselected`, and `uv build`.
- Refinement summary: pinned the schema-version-2 `ConfigProvenance` write contract, legacy schema-version-1 read compatibility through `metadata.legacy_resolved_fingerprint`, artifact-before-runtime-resolver-execution boundary, Phase 5 exclusions, and explicit package/unit/contract/integration/e2e/opt-in suite obligations.
- Implementation refinement pass: used the single expanded-path pass to enforce schema-version-2 direct provenance serialization requires a non-empty top-level `artifact_fingerprint`, add integration coverage that env-backed recipe arguments keep recipe manifests, provenance, manifests, and fingerprint records stable across environment value changes, and confirm no Phase 5 pipeline/run-store/default persistence scope was added.
- Implementation refinement validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_provenance.py tests/contracts/test_config_artifact_contract.py` passed with 23 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_provenance.py tests/unit/loom/config/test_compose.py` passed with 34 tests.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run ruff check src/loom/config/provenance.py tests/unit/loom/config/test_config_provenance.py tests/integration/config/test_compose_recipes.py` passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run pyright src/loom/config/provenance.py tests/unit/loom/config/test_config_provenance.py tests/integration/config/test_compose_recipes.py` passed.
- PR scope confirmation: final diff is limited to `loom.config` composition/provenance changes, config feature docs, the phase plan, the PR body artifact, and package/unit/contract/integration/e2e/config-extra tests. No Phase 5 pipeline/run-store API changes, `PipelineRunner` persistence changes, `config/composition_manifest.json` run-store persistence, or default resolved-config persistence changes were found.
- Final PR validation:
  - `make validate-pr` passed: Ruff, Pyright, default harness `439 passed, 11 skipped`, config-extra harness `360 passed, 445 deselected`, and `uv build`.
  - `make test-summary` passed and wrote `build/test-summary.md` with suite evidence: package `38 passed, 1 skipped`; unit `357 passed, 1 skipped`; contract `35 passed, 2 skipped`; integration `9 passed, 5 skipped`; e2e `6 passed`; config-extra `360 passed, 445 deselected`; overall `805 passed, 9 skipped, 445 deselected`.
- PR preparation: PR body artifact written at `docs/phases/v1-post-artifact-provenance-pr-body.md`; expanded-path PR body draft/refine requirements completed in this preparation pass; branch pushed to `origin/codex/v1-post-artifact-provenance`; PR opened at https://github.com/samcantrill/loom/pull/51.
- PR verification: `gh pr view 51 --json baseRefName,headRefName,state,url` returned base `develop`, head `codex/v1-post-artifact-provenance`, state `OPEN`, URL `https://github.com/samcantrill/loom/pull/51`; this is a root PR and is merge-eligible after review and checks.
- Stack maintenance: root PR targets `develop`; no predecessor branch and no stack retargeting required.
- Remaining blockers: none after the expanded-path implementation refinement pass.
