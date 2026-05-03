## Phase

- Phase: Phase 7 - Local Stores And Run Layout
- Branch: `codex/add-local-stores-run-layout`
- Target branch: `develop`
- Stack predecessor: none
- Merge eligibility: root phase PR; reviewable and merge-eligible only while targeting `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Phase execution plan: `docs/phases/add-local-stores-run-layout.md`
- Draft pass: complete
- Refine pass: complete

## Summary

Adds the Phase 7 local persistence boundary for runs and artifacts without
planning or executing stages. The PR introduces store protocols, filesystem
implementations, atomic write helpers, artifact index helpers, and the v0 local
run directory layout consumed by later planning and execution phases.

## Acceptance Criteria

- [x] `ArtifactStore` and `RunStore` protocols are exported from `loom.pipeline.stores`.
- [x] `LocalArtifactStore` saves and loads JSON, text, and bytes artifacts through `CodecRegistry`.
- [x] Already-written local files can be registered as artifacts with optional `codec_key`.
- [x] Codec-less artifact loads fail clearly unless an explicit codec is supplied.
- [x] Saved and registered regular files record and validate `sha256` checksums.
- [x] Atomic helpers cover JSON, text, bytes, replacement, directory creation, and unique temp paths.
- [x] Artifact indexes serialize logical `stage.output` keys to typed `ArtifactRef` values.
- [x] `LocalRunStore` reads and writes run metadata, status, plan, artifact index, config snapshots, recipe manifest, provenance documents, stage inputs, outputs, fingerprints, failures, provenance, status, and logs.
- [x] Local run directories expose the required v0 plain-file layout under `run.json`, `status.json`, `plan.json`, `artifacts.json`, `config/`, `provenance/`, `stages/<stage>/`, and `artifacts/<stage>/`.

## Implementation Notes

The public API remains scoped to `loom.pipeline.stores`; root `loom` and
`loom.pipeline` exports are unchanged. Store modules reuse existing
`ArtifactRef`, status records, codecs, URI helpers, deterministic JSON
serialization, fingerprint digest helpers, plain-data validation, and timestamp
helpers instead of adding new wrapper dataclasses or dependencies.

`LocalArtifactStore.save()` allocates local files under a stage artifact
directory, serializes through the selected codec, writes atomically, computes a
stored-byte checksum, and returns a typed `ArtifactRef`. `register()` stays
local-only, requires explicit `allow_external=True` for external local files,
and does not attempt serialization.

`LocalRunStore` owns run layout path helpers and persists caller-supplied
documents. It does not compose configs, compute fingerprints, decide resume
behavior, run stages, instantiate targets, provide CLI behavior, or introduce
remote store support.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/samcantrill/work/loom-worktrees/add-local-stores-run-layout/src uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py
result: passed, 38 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-package
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-unit
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-contract
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-integration
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed in the PR body refine pass; Ruff passed, Pyright passed, default pytest passed with 302 passed, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed in the PR body refine pass; wrote build/test-summary.md.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.92s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.98s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.36s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.56s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite output totals from `build/test-summary.md`:

- package: 19 passed
- unit: 257 passed
- contract: 15 passed
- integration: 11 passed
- e2e: no test files are present for this suite yet

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Budget Status

- Phase implementation refinement: used
- PR review before this PR: unused

## Risks / Follow-Ups

- No lock manager is included; v0 relies on atomic local writes. Revisit if later interrupted-run tests expose a concrete race.
- Resume planning, selector behavior, stage fingerprint calculation, runner lifecycle, output validation, CLI behavior, remote stores, and cross-run cache reuse remain deferred to later phases.
- Directory artifacts can be registered and checked for existence, but generic directory loading and tree checksums remain out of scope.
- Config snapshots and logs are persisted as caller-supplied text; stores do not compose, parse, or redact configs.

## PR Creation Status

PR body refine verified the draft against the phase execution plan, actual
diff, acceptance criteria, scope boundaries, risks, and refreshed suite
evidence. No Phase 8 planning/resume/selector behavior, Phase 9 runner/executor
behavior, or Phase 10 hardening/documentation behavior is included early.

PR creation is pending the refine/open pass GitHub authentication, branch push,
and explicit base/head command:

```sh
gh pr create --base develop --head codex/add-local-stores-run-layout --body-file docs/phases/add-local-stores-run-layout-pr-body.md --title "Phase 7: Local Stores And Run Layout"
```

After creation, verify with:

```sh
gh pr view <PR> --json baseRefName,headRefName,state,url
```

The PR must have `baseRefName` set to `develop` and `headRefName` set to
`codex/add-local-stores-run-layout`.

## Stack Maintenance

- Current base branch: `develop`
- Retarget/rebase needed after predecessor merge: none; there is no predecessor
- Successor branches depending on this phase: none recorded
- Branch cleanup constraints: branch may be deleted after merge only if no successor branch depends on it
