# Authority Example Coverage

This document tracks user-facing coverage for the implemented v10 authority
workflow. Runnable support demos remain in-repo for regression coverage, but
they do not count as primary catalog coverage.

## Covered User-Facing Behaviors

| Behavior | Coverage | Examples |
| --- | --- | --- |
| Authority lifecycle | `loom authority start`, `status`, `doctor`, `restart`, and `stop` use an explicit state directory and workspace registry. | `operations.authority-lifecycle` |
| Co-located CLI variants | Compatible CLI workflows teach explicit `--authority-backend co_located_service --authority-profile co_located` variants instead of creating a separate co-located example. | `execution.runtime-profile`, `execution.subprocess`, `execution.offline-first-import`, `execution.slurm.dry-run-basics`, `execution.slurm.afterok-diamond`, `operations.local-diagnostics`, `operations.failing-run`, `operations.offline-import-rejections` |
| Offline-first before/after import | `loom run --offline-first` writes non-authoritative evidence, pre-import `loom status` shows the non-authoritative state, `loom authority import-offline` promotes the run, and post-import `loom status` reports authoritative imported provenance. | `execution.offline-first-import` |
| Offline import rejection | Incomplete and conflicting imports fail with stable machine-readable rejection codes. | `operations.offline-import-rejections` |
| Resource coordination | Authority-backed resource limits and resource leases are exercised through the supported public Python API. | `operations.resource-leases` |

## Not Currently User-Facing

- `operations.authority-backend-diagnostics` remains an `internal_demo` until
  backend diagnostics can be taught through a pure user-facing supervisor path
  rather than a local service-authority fixture.
