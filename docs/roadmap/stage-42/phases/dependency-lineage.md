# Phase 5 Execution Plan: Dependency Lineage

## Metadata

- Status: in_progress; stage 42 / P5.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p5-dependency-lineage`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 5: Dependency Lineage
- Worktree/coordination: manifest context; base after P4
  `9534e7699fc49b588c5c81c3bbdd608f869c8b34`.
- Dependencies: P4 exact output identity and earlier native/query contracts.
- Named refinement uncertainty: none. Blockers: none. P4 #353 remotely merged,
  completion metadata published/synchronized and exact phase branch retired.

## Objective And Supported Merge State

Answer “which results depend on this exact output?” and “what inputs produced
this result?” using recorded generic relationships. Persist the evidence when
an attempt is prepared, before a later retry changes producer heads. Return
connecting paths, reuse origins and evidence/depth/scope limits. This phase is
independently useful with metadata-only output selection.

Own `FR-42-A01/A02/A03`, `EX-42-A01/A02`, `VAL-42-A01/A02`, `DQ-42-A01`, and
the historical-consumption part of `VAL-42-A03`. No graph database, automatic
execution, domain stage ordering or retrospective provenance guessing.

## Source Evidence And Current Harness

- `src/loom/pipeline/stores/authority.py`: `PreparedAttemptRequest` includes
  bound inputs/upstream commits but these are not complete per-input origins.
- `src/loom/pipeline/stores/read_models.py`: attempt identities, commit facts,
  action-result bindings and lifecycle snapshots; extend `StageAttempt` with the
  retained start witness. Both authority implementations' `confirm_execution_started`
  and direct RUNNING allocation paths own its capture; terminalizers preserve it.
- `src/loom/pipeline/orchestration.py`, `planning/readiness.py`,
  `execution/stage_attempts.py`: planning/preparation/worker input handoff.
- `src/loom/queue/_action_result_resolution.py`, `_action_results.py` and
  `src/loom/pipeline/planning/_action_identity.py`: exact reused facts/action evidence. Reuse where
  semantics match; action identity is not a general lineage index.
- Both authority stores/repositories, protocol/client/service serializers,
  local run/provenance readers; `src/loom/runs/bundles.py`, `imports.py`, `models.py`
  and `src/loom/authority/offline_import.py` for bundle export/import boundaries.
- Existing readiness, authority preparation, action-result binding, stage-attempt
  and immutable-artifact fixtures. Stage attempts are identified by run + stage
  + attempt ID; a display ID such as `stage-1` is not globally unique.

## Fixed Contracts And Invariant Ownership

The [detailed output-access contract](../planning/output-access.md#detailed-implementation-contract)
owns `AttemptInputBinding`, optional legacy fields and four relation meanings.
`consumed_input` means bound to an attempt with an authority-confirmed start, not
proof that application code opened the file. Prepared/cancelled-before-start input remains
`bound_input`. `None` means unknown legacy binding evidence; an empty tuple means
known no inputs. Never modify `ArtifactRef.metadata` to carry query identities.

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| Retained input equals handed-off input | Preparation transaction, assignment/readiness guards and worker handoff | Producer retry/reuse or pending input could relink consumer to current head | Assert exact ref/producer commit across prep, grant, start, output commit |
| Declared/bound/started relations differ durably | Authority attempt start witness; graph reads it | Terminalization overwrites current state; deferred audit can be absent after crash | Before/after-start cancel/failure then restart in both owners; no audit prerequisite; legacy unknown |
| Reuse and external boundaries remain honest | Per-input origin capture and binding reader | Equal bytes/tags or local materialized path could imply false producer | Cross-run reuse, unrelated same checksum, external untracked input |
| Graph limits do not mean no dependency | Bounded traversal/page assembler | Fan-in/out, cycles or evidence gaps could hide a path | Dedup stable identities, intermediate traversal, truncation/coverage and cursor tests |

Public/durable meanings are fixed. Private graph adjacency representation and
read batching are discretionary. Do not add a persisted graph projection until
current query workloads demonstrate a need; existing prepared/commit records own
truth. New lineage fields do not enter action fingerprints or change scheduling.

## Implementation Slices

1. Add optional per-input binding read/write shapes, nullable monotonic start
   witness fields, and additive migrations for retained attempt evidence in both
   authority backends and serializers. `start_confirmed=None` means unknown
   legacy evidence; new managed attempts initialize false, not null. The owner
   records true and UTC acknowledgement time in the actual start transition
   transaction; direct RUNNING allocation captures its acknowledged start too.
   Replay preserves the first time, terminalization never clears it, and a late
   terminal no-op confirmation cannot create it. No best-effort lifecycle observer
   is required for this invariant. Keep existing fences and lifecycle states.
   Preserve old request replay serialization when new data is absent. Validate
   exact native producer selectors at the authority boundary. External refs get
   an explicit external origin rather than guessed run/commit fields.
2. Capture every effective input port while readiness/preparation resolves it,
   including formerly pending inputs and cross-run action-result bindings.
   Persist original artifact ref, original producer locator where known, and
   the scoped consuming attempt before grant. Keep existing head/revision/fence
   validation; an input changing during preparation must follow current replan
   behavior, not overwrite the old attempt's binding.
3. Carry the same evidence through native/container/Slurm common handoff paths.
   Materializing an input may change its worker-local path, not its source
   identity. Read the retained start witness before projecting consumed edges;
   legacy unknown yields explicit incomplete-consumption coverage. Join
   output commit → producing attempt → retained input bindings for upstream reads.
4. Extend supported bundle/export/import and provenance read projections so
   new input and start evidence survives round-trip, preserving source identity under existing
   import mapping. Old bundles remain legacy-unknown. Inspect the actual bundle
   owner during execution; if preserving source identity needs a new import
   contract, stop for bounded refinement rather than inventing remapped origins.
5. Implement scoped stable traversal on exact commit/attempt nodes, reusing P4
   locators. Visit intermediate nodes before output-type filtering; retain fan-in
   and fan-out edges, original/matched reuse associations and unknown boundaries.
   Enforce depth/result/visited budgets, stateless bounded continuation and the
   distinction between complete no-match and traversal limit.
6. Add `trace_lineage`, `lineage-query-v1`, `loom runs lineage`, MCP
   `loom_trace_lineage`, and docs with generic multi-run fixture. Both read roles
   share authorization; hidden/inaccessible producer boundaries cannot leak data.

## Test And Validation Plan

Add `tests/contracts/test_attempt_input_lineage_contract.py`,
`tests/integration/queue/test_lineage_queries.py`. Extend
`tests/unit/loom/pipeline/planning/test_readiness.py`,
`tests/unit/loom/pipeline/execution/test_stage_attempts.py`, authority protocol
and store contracts, and `tests/integration/authority/test_action_result_binding.py`.
Required bundle checks: `tests/contracts/test_run_bundle_export_contract.py`,
`tests/contracts/test_run_bundle_import_contract.py`,
`tests/integration/pipeline/test_run_bundle_export_inspect.py`,
`tests/integration/pipeline/test_run_bundle_import.py`.

Required cases: pending-to-bound input, reuse without local producer attempt,
successor producer commit, retry consumer attempts, failure/cancel before and
after start followed by terminalization/restart in both authority modes with
audit observations absent, repeated start confirmation retaining its first time,
late confirmation after unstarted terminalization, migrated/bundled unknown start
evidence, direct RUNNING allocation, history output upstream, fan-in/out, traversal through nonmatching
intermediates, unknown old/external data, exact source authorization, scope/depth/
visited/cursor limits, schema migration, replay and export/import.

Development selection:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/contracts/test_attempt_input_lineage_contract.py tests/integration/queue/test_lineage_queries.py tests/unit/loom/pipeline/planning/test_readiness.py tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/integration/authority/test_action_result_binding.py
```

Final gate: `make validate-pr`; prepared-attempt/assignment/durable-schema changes
cross execution paths. Use `$loom-targeted-validation`. Verify the generic
handoff in native and controlled container/Slurm adapter tests. Actual container
or Slurm acceptance is required only if backend-specific launch/transport logic
changes; otherwise no physical-fleet claim is needed for this metadata sidecar.
Record any such expanded environment requirement before merge.

## Risks, Stops, And Handoff

Highest-risk phase: correct binding capture without changing action identity,
fencing or replay. Independent phase review focuses there, on transactionally
retained start evidence, and on absent versus empty legacy semantics. Stop on unresolvable source identities, unsupported
bundle remapping or a need to reopen execution lifecycle contracts. Unknown
legacy edges and untracked files opened by application code remain explicit
limitations, not reconstruction work.

Read this entire card and owning binding/traversal sections. Workflow preparation
passed; reuse approved readiness and retained-start witness design. One executor
is justified by the tightly coupled preparation, durable authority, bundle and
graph changes. Its write boundary is P5 source/tests/user docs and this card;
P6 payload transfer is excluded. No planning refinement needed at admission;
the explicit bundle-remapping stop remains binding if source investigation finds
one. Required `make validate-pr`, selected bundle/replay/start/handoff evidence
and native read-role parity remain obligations. Split optional dependency lanes
using the existing harness and record real versus controlled backend evidence.
Implementation, validation, independent review and PR pending. Refiner not
needed yet; blocker corrections 0/3; improvement entries none.

## Completion Record

| Item | Result |
| --- | --- |
| Changed paths, tests, validated tree, review/PR/merge, residual risk and cleanup | Pending implementation |
