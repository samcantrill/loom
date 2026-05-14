## Summary

Implements the final v11 operator surface for `loom.queue`: queue-owned
preflight diagnostics, status/cancel read models, `loom queue` operational
commands, deterministic tests, and dedicated queue docs. The CLI remains a thin
wrapper over explicit queue config loading, the configured repository, and the
existing Python service/client/controller surfaces.

The docs now explain the ownership split between queue state, authority truth,
and delegated SLURM scheduler evidence, including the v11 limitation that
delegated SLURM still assumes a pre-staged or shared workspace.

## Acceptance Criteria

- [x] Users can follow docs to configure and operate managed local and
  delegated SLURM queues in deterministic or fakeable environments.
- [x] CLI remains a thin operational wrapper over the Python service/client
  surface.
- [x] Preflight and status outputs explain queue, authority, and delegated
  scheduler ownership without overstating delegated launch guarantees.

## Implementation Notes

- Added `loom.queue.preflight` for config/repository, authority-config,
  managed-pool reconciliation readiness, SLURM command availability, and
  delegated workspace-assumption diagnostics.
- Added queue operational status/cancellation read models and queue-specific
  CLI formatting.
- Registered `loom queue preflight`, `start`, `status`, `cancel`, and
  `drain-foreground`.
- Added `docs/features/queue.md` plus cross-links from CLI, execution,
  preflight, runtime resources, and SLURM docs.

New tests cover queue preflight/status helpers, parser registration, CLI
status/cancel/drain behavior, SQLite-backed queue CLI operations, e2e queue CLI
smoke, and import-boundary constraints.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 9 pytest | Passed | 58 passed |
| Config-extra focused queue tests | Passed | 8 passed |
| Targeted Ruff | Passed | Phase 9 touched Python files |
| Targeted Pyright | Passed | 0 errors |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, build |
| `make test-summary` | Passed | Suite summary below |
| GitHub checks | Pending | To run after PR opens |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 77 | 0 | 0 | 1 | 0 |
| unit | passed | 1032 | 0 | 0 | 6 | 1 |
| contract | passed | 167 | 0 | 0 | 2 | 0 |
| integration | passed | 145 | 0 | 0 | 8 | 13 |
| e2e | passed | 41 | 0 | 0 | 0 | 2 |
| config-extra | passed | 438 | 0 | 0 | 0 | 1470 |

## Risks / Follow-Ups

- `loom queue start` is an in-process service/config check in v11, not a
  persistent background supervisor.
- CLI enqueue, retries, fairness, SSH, bundles, daemon transport, and richer
  scheduler policy remain later roadmap work.
