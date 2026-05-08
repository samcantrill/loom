# SLURM Live Operations - Phase 2: Command And Manifest Models

## Summary

- Added fakeable SLURM command runner contracts for `sbatch --parsable`,
  `squeue`, `sacct`, and `scancel`, including subprocess and deterministic fake
  runner implementations.
- Added bounded, artifact-safe command result records and parsing for
  `sbatch --parsable` outputs like `123456` and `123456;cluster`.
- Added live SLURM manifest schema version 2 records for submitted jobs, failed
  submissions, scheduler status snapshots, cancellation attempts, and canonical
  `slurm/submissions/<submission_id>/manifest.json` live read/write helpers.
- Added unit, contract, and integration coverage for command parsing, fake
  runner behavior, live manifest round-trips, and dependency-job consistency.

## Scope

- In scope: pure SLURM command/model contracts under
  `loom.pipeline.executors.slurm`.
- Out of scope: `loom run` live submission, `loom status --jobs`,
  `loom cancel --jobs`, and real scheduler calls in default tests.

## Validation

| Command | Result |
| --- | --- |
| `uv run ruff check src/loom/pipeline/executors/slurm tests/unit/loom/pipeline/executors/slurm/test_slurm_commands.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_live_models.py` | passed |
| `uv run pyright src/loom/pipeline/executors/slurm tests/unit/loom/pipeline/executors/slurm/test_slurm_commands.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_live_models.py` | passed |
| `uv run pytest tests/unit/loom/pipeline/executors/slurm/test_slurm_commands.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_live_models.py` | passed, 12 tests |
| `make validate-pr` | passed |
| `make test-summary` | passed |

## Suite Evidence

| Suite | Result |
| --- | --- |
| package | 52 passed, 1 skipped |
| unit | 709 passed, 1 skipped |
| contract | 63 passed, 2 skipped |
| integration | 35 passed, 7 skipped, 9 deselected |
| e2e | 22 passed |
| config-extra | 411 passed, 881 deselected |

## Assumptions And Risks

- Live manifests use schema version 2 while preserving the v6 canonical
  `manifest.json` path.
- The fake runner is intentionally deterministic and cluster-free; real SLURM
  quirks remain Phase 7 opt-in acceptance coverage.
- Scheduler command output persistence is bounded and control-character-safe,
  but later phases still need to keep CLI output and mutation behavior
  conservative.
