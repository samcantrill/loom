## Phase

- Phase: `Phase 4 - Config Composition`
- Branch: `codex/add-config-composition`
- Target: `develop`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-config-composition`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Expanded phase plan: `docs/phases/add-config-composition.md`

## Summary

Implements trusted Phase 4 YAML config composition for `loom`. The PR adds hard
config dependencies, composes a base config plus overlays and dot-path
overrides, resolves ordinary interpolation through a local wrapper, validates
the top-level `loom`-owned fields, rejects `_recipe_` blocks until Phase 5,
redacts secret-like keys recursively, records config provenance, and returns a
deterministic `ComposedConfig` fingerprint.

## Acceptance Criteria

- [x] Base config and overlays compose in order.
- [x] Mapping, scalar, list, and explicit null merge semantics match the plan.
- [x] Overrides parse supported scalar and structured values and apply through
  path-aware dot paths.
- [x] Interpolation resolves through `loom.config.interpolation` and unresolved
  or resolver-style values fail with config-specific errors.
- [x] Required top-level fields are validated without validating the future
  pipeline schema.
- [x] `_recipe_` keys fail clearly as unsupported until Phase 5.
- [x] Secret-like keys are redacted recursively without mutating resolved data.
- [x] Config provenance and fingerprints change when source inputs change.
- [x] Config composition writes no files.

## Implementation Notes

Added `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6` as hard runtime
dependencies and updated `uv.lock`.

Config behavior is split across `loom.config` modules for API, loading, merge,
overrides, interpolation, validation, redaction, provenance, errors, and
composition orchestration. Public `compose_config` returns plain resolved data,
redacted data, config provenance, an empty Phase 4 recipe manifest, and a stable
fingerprint.

Scope was kept to Phase 4. The change does not add recipe expansion,
`_target_` construction, pipeline parsing, stores, runner behavior, persistence
writes, or top-level `loom` config exports. `_include_`, `_copy_`, `_replace_`,
and `_target_` remain ordinary project-owned data in this phase.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md with package, unit, contract, and integration suites passing; e2e not present
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed with 0 errors, default pytest passed with 175 tests, and uv build produced sdist and wheel artifacts
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 0.68s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 0.60s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.30s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 0.38s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | not present | 0.00s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Package collected 13 tests, unit collected 153 tests, contract collected 4
tests, and integration collected 5 tests.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` in commit
  `429f2ee`.
- PR review before this PR: unused.

## Risks / Follow-Ups

- Hard config dependencies are now default runtime dependencies as accepted by
  the v0 implementation plan; revisit after v0 if downstream users need a
  primitives-only install.
- Recipe expansion and `_target_` construction remain Phase 5 work.
- Pipeline schema parsing, run-store persistence, runner behavior, and config
  snapshot writes remain future-phase work.
- Dot-path overrides remain mapping-key only, and resolver-style interpolation
  remains unsupported until provenance and fingerprint policy are defined.

## PR Creation Status

PR was not opened during preparation because GitHub authentication is
unavailable in this environment.

```text
command: gh auth status
result:
github.com
  X Failed to log in to github.com account samcantrill (/home/samcantrill/.config/gh/hosts.yml)
  - Active account: true
  - The token in /home/samcantrill/.config/gh/hosts.yml is invalid.
  - To re-authenticate, run: gh auth login -h github.com
  - To forget about this account, run: gh auth logout -h github.com -u samcantrill
```

After authentication is refreshed, use:

```sh
gh pr create --base develop --head codex/add-config-composition --title "Phase 4: Config Composition" --body-file docs/phases/add-config-composition-pr-body.md
gh pr view <PR> --json baseRefName,headRefName,state,url
```
