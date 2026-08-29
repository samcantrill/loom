# Phase 9D Execution Plan: Embedded Supervisor And Restart Closure

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 9D
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9d-embedded-supervisor-restart-closure`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path: create after Phase 9C2 is remotely merged
- Base revision: current `origin/develop` after the Phase 9C2 merge
- PR target: `develop`
- PR title: `feat(scheduling): close embedded managed restart`
- Dependency: Phase 9C2 remotely merged. Blocked Phases 9–9C remain read-only
  evidence; Phase 9C2's private supervisor is the only process owner.
- Workflow path: expanded because the embedded run-store-to-resident projection
  and restart capacity interact. One executor and one independent review.
- Blocker corrections: 0/3

## Objective And Context

Move the embedded/local production managed path onto Phase 9C2's separate
supervisor and resident workspace. The parent stages an exact assignment bundle;
the child receives no run store or Python services; restarting the local agent
application reconciles at zero availability without another launch or lost
result. This phase removes the final callable/thread process owner.

Phase 9D also completes the already-approved local protected configuration hard
cut. No existing local daemon CLI invocation or managed root is compatible.

## Scope

In scope:

- Intentionally lazy-export `ResidentWorkerLaunchProfile` from `loom.queue` and
  require one exact value in `LocalDaemonConfig`, with no default or inference.
- Require the seven fixed resident-profile flags on both `queue daemon-init` and
  `queue daemon-serve`; construct exact `ResidentProfileDescriptor` plus paths;
  bump the local-daemon CLI envelope v3 to v4.
- Fresh local initialization creates a one-member Phase 9C2 supervisor profile
  set; ordinary local start requires the separate service and exact profile.
- Generalize/rename the current remote request/workspace into the one private
  resident assignment bundle/workspace used by remote and embedded execution.
- Project the already-prepared embedded `StageWorkerRequest` into the bundle,
  copy and verify bounded no-follow input bytes, construct only assignment-local
  child paths, retain/digest-check outputs, map the child result/failure back to
  the original journal-owned run URI, and use ordinary authority finalization.
- Move/split embedded managed composition under `loom.queue`; remove optional
  managed executor/artifact-store/plugin/validator/process-launcher hooks,
  `_ManagedWorkerHandle`, and `SQLiteAgentJournal._process_handles`. Pipeline
  execution never imports queue.
- Route embedded launch/query/stop/result through the Phase 9C2 client and finish
  same-session local restart at zero availability with exact journal/workspace/
  supervisor/result/output/outbox replay, unknown claim retention, provider
  release, and one fresh observation before polling.
- Update all production/tests/examples for the explicit hard cut and add local
  service/restart operational guidance.

Out of scope:

- Remote supervisor behavior already merged in Phase 9C2 except shared private
  renames required by the common workspace; no compatibility aliases remain.
- SLURM guarded recovery and session replacement/final validation remain Phase
  9E/9F. No supervisor HA, migration, PID adoption, or automatic takeover.

## Fixed Contracts

### Explicit local profile and CLI

`LocalDaemonConfig.resident_worker_launch_profile` is required and its descriptor
is exactly `ResidentProfileDescriptor.to_dict()`. Both daemon commands require:

```text
--resident-project-root PATH
--resident-python-executable PATH
--resident-profile-id ID
--resident-profile-revision REVISION
--resident-project-fingerprint FINGERPRINT
--resident-environment-fingerprint FINGERPRINT
--resident-executor-fingerprint FINGERPRINT
```

There is no profile file, environment/cwd/executable inference, default, alias,
or migration. Init and serve must receive identical values; the supervisor root
fingerprint rejects mismatch before daemon availability.

### Shared resident bundle and result projection

The exact bundle content remains the blocked Phase 9A plan's `Fixed shared
resident-assignment bundle decision` and Phase 9C2's current remote schema. It
contains assignment/work/attempt/offer/claim IDs, selected profile descriptor,
path-free prepared stage data, exact input manifests, output names, claims, and
provider descriptors. It never contains coordinator run URI, run-store root,
arbitrary host paths, Python callables, or credentials.

```text
parent reads prepared StageWorkerRequest and source ArtifactRefs
  -> copies verified regular bytes into assignment workspace
  -> persists bundle and journal launch intent
  -> Phase 9C2 supervisor launches fixed resident worker
  -> child writes assignment-local result/outputs
  -> parent verifies retained digests and restores original run identity
  -> existing journal/coordinator/authority terminal and release path
```

Workspace state and retained bytes survive application restart. Cleanup follows
durable terminal/output acknowledgements and physical release; it never precedes
replay. The supervisor launch digest binds the exact bundle digest.

### Embedded restart order

```text
matching Phase 9C2 supervisor/profile verified
  -> local agent role lock acquired
  -> availability zero and scheduling/polling suppressed
  -> complete retained journal/workspace set reconstructed
  -> exact supervisor receipts joined
  -> result/output/event/outbox replayed normally
  -> claims released or retained unavailable
  -> fresh complete provider observation published
  -> local scheduling enabled
```

No supervisor receipt or valid retained result means no relaunch and no capacity
reuse. `CONTAINED` follows only Phase 9C2's positive group proof.

## Invariant Ownership

| Invariant | Owner | Material consequence | Coverage |
| --- | --- | --- | --- |
| Local profile is explicit and stable | Config/root fingerprint | Different code after restart | CLI/library init/serve match and mismatch tests |
| Bundle contains only exact inert data/bytes | Queue workspace | Unreconstructable or unsafe child | Codec, no-follow, digest, path/object rejection |
| Embedded path has no callable/thread owner | Queue composition | Restart loses process truth | Static removal and fresh-process tests |
| One launch survives local agent restart | Phase 9C2 supervisor | Duplicate stage effects | Running-worker restart sentinel |
| Result maps to exact original fence/run | Journal/authority importer | Stale output mutation | Result-before-journal and fence mismatch tests |
| Capacity waits for full replay | Local startup/provider | Double allocation | Zero-availability barriers |

## Implementation Slices

1. Complete explicit local library/CLI profile hard cut and one-member supervisor
   initialization/open composition using the merged Phase 9C2 service.
2. Generalize the resident bundle/workspace, implement embedded input/result
   projection, move composition to queue, and remove every old callable owner.
3. Implement local same-session zero-availability restart/replay, update current
   callers/docs, and add real service/agent/worker causal tests.

## Test And Validation Plan

- Unit/CLI: required seven flags, v4 envelope, exact profile/config/root mismatch,
  bundle codec, input/output digest/no-follow checks, result identity mapping.
- Contract: local/remote workspace and supervisor semantics match; no queue import
  from pipeline; no optional managed services or compatibility aliases remain.
- Integration: real Phase 9C2 service plus fresh local agent applications; crash
  around staging/accept/launch/result/journal; exact one-root sentinel; output/
  outbox replay; unknown work retains claims; zero capacity until observation.
- Regression: Phase 2/5 managed lifecycle, GPU environment, cancellation-before-
  start, local daemon CLI/socket production, coordinator/authority restart.
- Gate: focused bundle/managed-local/local-daemon/CLI/import suites, changed-path
  Ruff/Pyright, then `make validate-pr`. Phase 9F owns final summary.

## Risks, Review, And Stops

- Main risks are run-store serialization, a second workspace schema, retained
  thread/process handles, inferred CLI values, result identity rewrite without
  fence checks, workspace cleanup before replay, or early capacity.
- Stop for a genuinely new public/durable choice or if embedded input/output
  cannot use the fixed resident bundle. Do not reopen Phase 9C2 or implement 9E/F.
- Independent review must verify owner removal, exact projection, hard cut, and
  fresh-process local restart.

## Executor Handoff

- Start only after Phase 9C2 remotely merges and base current `origin/develop`.
- Read this plan, Phase 9C2 completion, and blocked Phase 9A's exact shared-bundle
  heading. Implement all slices; do not preserve old callable or CLI behavior.
- Commit source/tests/guidance only; no roadmap/GitHub work and no delegation.

## Workflow State

- Manager preparation: pending Phase 9C2 merge
- Implementation: pending
- Validation/review: pending
- PR/merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | pending |
| Validated revision and evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
