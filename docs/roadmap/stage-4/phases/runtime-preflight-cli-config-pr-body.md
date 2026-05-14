## Summary

Adds the Phase 6 runtime input and preflight mapping layer. Config can now
provide top-level `runtime` and `runtime_profiles` sections, CLI commands can
build sparse explicit runtime option sources, and preflight reports normalized
runtime/profile/stage, executor, and resource capability diagnostics through
stable check IDs.

This keeps the runtime API as the source of truth: CLI/config adapters delegate
to `RunOptions`, runtime profile merge semantics, and Phase 5 executor
capability diagnostics. The run workflow remains local-only and runtime options
are still not threaded into runner requests, stores, plugins, adapter schemas,
or persisted `runtime.json`.

## Acceptance Criteria

- [x] CLI and config map into normalized `RunOptions`.
- [x] Tags and notes work through CLI and config/API pathways.
- [x] Preflight reports runtime/profile/stage/executor/resource diagnostics
  with stable check IDs.
- [x] Runtime checks are grouped under `runtime`, executor checks under
  `executor`, and resource capability checks under `resources`.
- [x] Group normalization, default group selection, and serialized JSON remain
  stable and contract-tested.
- [x] Unknown profiles and unknown selected executors fail.
- [x] Ignored resources and unclaimed adapter namespaces warn.
- [x] `--strict` escalates warnings consistently with v3 behavior.

## Implementation Notes

- Added `src/loom/pipeline/runtime/config.py` with
  `RuntimeConfigSections`, `parse_runtime_config_sections()`, and
  `merge_config_run_options()` for optional top-level `runtime` and
  `runtime_profiles` config sections.
- Extended CLI option adapters and `plan`, `preflight`, and `run` parsers for
  runtime profile, executor, run URI, dry-run, selector/resume, repeated tag,
  and repeated note inputs. CLI sources are sparse so absent flags do not
  override config/profile fields.
- Added `PreflightGroup.RUNTIME` and `PreflightGroup.RESOURCES`, plus stable
  IDs for `runtime.options`, `runtime.profile`, `runtime.stage_options`,
  `executor.resolve`, `executor.capabilities`, and `resources.capabilities`.
- Mapped Phase 5 `CapabilityDiagnostic` records into preflight checks without
  moving descriptor logic into diagnostics. Unknown executors fail
  `executor.resolve`; unresolved executor capability/resource checks skip
  instead of duplicating the same failure.
- Preserved existing local executor availability probing through
  `executor.local`, existing preflight JSON envelope shape, and existing
  strict-mode warning escalation.
- Tightened run/artifact path checks so explicit runtime `run_uri` values are
  used without forcing config composition, while config-derived run URIs remain
  available after runtime normalization has already run.

New tests implemented:

- Runtime config unit tests for section extraction, profile merge, sparse
  explicit options, stage validation, and invalid section shapes.
- CLI unit tests for sparse runtime sources, tag/note parsing, preflight
  request wiring, and run preflight groups.
- Diagnostics unit/contract tests for new groups, stable check IDs, capability
  mapping, warning/skip/fail behavior, and JSON stability.
- Config-extra integration and e2e coverage for CLI preflight resource
  warnings and `--strict` warning exits.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Final run after blocker resolution passed Ruff, Pyright, default no-extra tests, config-extra tests, and build on 2026-05-07. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` on 2026-05-07 with overall status `passed`. |
| GitHub checks | Passed | Required `checks` workflow passed for the reviewed PR head on 2026-05-07. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.14s |
| unit | passed | 550 | 0 | 0 | 1 | 0 | 5.29s |
| contract | passed | 53 | 0 | 0 | 2 | 0 | 1.82s |
| integration | passed | 15 | 0 | 0 | 7 | 7 | 1.84s |
| e2e | passed | 16 | 0 | 0 | 0 | 0 | 5.62s |
| config-extra | passed | 397 | 0 | 0 | 0 | 684 | 14.89s |
| Overall | passed | 1081 | 0 | 0 | 11 | 691 | 34.60s |

## Risks / Follow-Ups

- Phase 7 still owns threading normalized `RunOptions` into `RunRequest`,
  runner handoff, and persisted runtime metadata.
- Built-in preflight still uses the default descriptor registry only; plugin
  discovery and third-party descriptor loading remain future work.
- Nested runtime/profile/adapter settings remain config/Python API only unless
  a later roadmap adds specific CLI flags for them.
