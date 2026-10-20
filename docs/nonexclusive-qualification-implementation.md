# Non-exclusive fleet GPU qualification

User requirement: minimal GPU qualification must not wait for an idle GPU.
Normal experiment reservations remain unchanged.

Implementation: a fleet inventory policy selects `nonexclusive` capability or
`exclusive` scheduling qualification. New operations retain the selection.
Existing native process containment and resident container construction own the
bounded CUDA probe. The fixed probe independently checks its device UUID and
2×2 numerical result. No occupancy override, claim, or scheduler bypass for
ordinary workloads is added.

Affected consumers: fleet self-tests, runtime/workload upgrade checks, native
host receipts and protected inventory loading. CPU/storage scheduled checks
remain required. Non-exclusive failure remains a failure, never a skipped pass.
Unknown host execution after a lost receipt requires investigation rather than
automatically repeating an uncontained process.

Evidence:

- Four capability tests passed, including actual container command construction,
  wrong UUID rejection, nonzero process exit and absent declared GPU.
- 39 selected configuration, capability and self-test tests passed.
- Physical contained probe passed on Sleipnir using current resident profile and
  image `3a83508251516973c6357f9763121e7b56c69c923f6a9fad8fa194a3111fa3a5`,
  GPU `GPU-11672ae4-f151-dd5a-53bb-bfe29f17e597`, with no exclusive claim.
  Receipt:
  `/nas/home/can134/.local/share/rphys/mlflow-readable/releases/2bb5e1389/sleipnir-capability-owner-validation.json`.
- Changed-file Ruff passed.
- Seven final capability, host-boundary and upgrade-policy tests passed.
  Upgrade coverage retains CPU/storage checks and rejects a failed capability
  probe. Host coverage rejects a changed profile and an uncertain replay.
- The new probe module passed Pyright. The upgrade uses the current admitted
  profile identity, not the authored descriptor's unresolved fingerprints.

Remaining: package and deploy the supporting
Loom release, enable the fleet policy, and qualify the installed path. Preserve
the ongoing readable-metrics scientific canary during rollout.
