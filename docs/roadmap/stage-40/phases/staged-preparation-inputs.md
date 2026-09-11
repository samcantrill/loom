# Phase 3 Execution Plan: Preparation With Transferred Inputs

## Metadata

- Status: in_progress
- Roadmap stage and phase: 40 / 3
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-40-p3-staged-preparation-inputs
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `ad4ed8a986c7ee9a5e67f01ca00df300f5d2d280`, published Phase 2 completion metadata after squash merge `5918bfd364a8637a0aa6acf87b60a5d71defd39d`.
- PR target: develop
- PR title: Stage 40 Coordinator Client, Agent Preparation, And MCP - Phase 3: Preparation With Transferred Inputs
- Dependencies: Phase 2 PR #300 remotely merged, metadata published, exact stage/control/remote synchronization passed and both exact phase branches retired.
- Workflow path: expanded for archive extraction, transfer/recovery boundaries and retained-state compatibility
- Blockers: none

### Execution startup

The shared start gate created this branch in the retained Stage 40 worktree on
2026-09-11 after verified Phase 2 delivery. Control develop remains clean and is
used only for synchronization. The approved four-phase readiness receipt applies
without product-contract changes; no planning refinement is needed.

The actual predecessor owns receipt values/capture in queue/preparation.py,
state orchestration in queue/_preparation_operations.py, native application wiring
in preparation.py and assignment materialization in _remote_stage_execution.py,
_managed_local.py and agent_session_transport.py. The fixed preparation binding
already travels in the native stage fingerprint. Staged mode can join its committed
archive as one bounded native assignment input, extract before workspace acceptance,
and retain the existing operation/report/publication and root schemas.

One bounded executor is justified by the archive/filesystem boundary and its
independent test surface. It owns receipt/capture/extraction helpers and their
unit tests; the manager owns orchestration, native assignment/readiness wiring,
integration/CLI coverage, user docs and all delivery gates. They share the stage
worktree and phase branch with disjoint file ownership; neither changes branches
while the other is active. Final gates remain make validate-pr and make test-summary.

## Objective And Context

Use the existing preparation operation from a coordinator and worker whose
project storage is not shared. The coordinator captures explicit selected files,
relays an archive to the selected existing worker environment, and publishes the
same checked composition/receipt through Phase 2's lifecycle. Complete FR-40-04
and the staged-path coverage of FR-40-03/05/06/07/08/09/12, under the existing
DQ-40-02/03/04/05/06 boundaries. Shared preparation remains supported.

This is a second input-delivery mode for an already usable operation. Phase 2
owns the common request, result/report, profile selection, finalization,
cancellation, retention and coordinator schema. Phase 4 supplies MCP and skills.

## Current Source And Harness

- Published Phase 2 native preparation control and `src/loom/preparation.py`:
  fixed child, supplied-composition diagnostics and common report/publication.
- `src/loom/queue/_remote_stage_execution.py`: regular-file input relay,
  assignment-owned access, replay/fencing and committed output materialization.
- `src/loom/queue/deployment.py`, `resident_readiness.py`,
  `_agent_process_supervisor.py`: protected source/profile policy, qualified
  installation, retained launch binding and existing software eligibility.
- `src/loom/queue/local_daemon.py`: published preparation linkage/projection,
  native operations, admission/cancellation and role-specific root versions.
- Existing artifact/source/job-binding helpers; extend their actual published
  owners rather than create a general file-delivery registry.
- Published Phase 2 preparation/capture tests and existing
  `tests/integration/queue/test_agent_session_transport.py`,
  `tests/integration/queue/test_agent_service_lifecycle.py`,
  `tests/integration/queue/test_local_daemon_production.py`,
  `tests/unit/loom/queue/test_deployment.py`,
  `tests/package/test_import_boundaries.py`.

The evidence baseline is recorded in the manifest. Exact new file/test paths
come from the merged predecessor; never invent an alternate preparation engine
because private names differ from the planning examples.

## Scope

Implement bounded staged archive capture, committed ArtifactRef delivery through
the native relay, contained extraction/verification, mode-aware qualification,
effective capability/policy exposure and the staged native/CLI journey. Preserve
all common contracts and existing shared operations, including retained work.

No new queue, operation kind, state machine, publication engine, target input
scheme, source deployment, package/environment installation, laptop upload,
dataset distribution, automatic shared-to-staged fallback or MCP implementation.
Captured files serve preparation only; target code/data continue to use existing
compatible installations and explicit supported runtime bindings.

## Fixed Contracts And Private Discretion

### Common API and source-mode handoff

Inherit Phase 2's [Native request and operation result](agent-preparation.md#native-request-and-operation-result),
[Protected deployment selection](agent-preparation.md#protected-deployment-selection),
[One composition, one publication](agent-preparation.md#one-composition-one-publication),
and [Durable state, replay, cancellation and retention](agent-preparation.md#durable-state-replay-cancellation-and-retention).
Those headings remain the authoritative common contracts; this card owns the
additional staged boundary and its validation.

The request changes only `source.mode` to staged. It retains operation_id,
run_name, protected root/profile aliases, project-relative path/includes and
config_path. It uses the same prepare_run/cancel_preparation, operation/read/wait,
Unix/HTTPS client methods and CLI commands. Result schema 1 and the child report
schema remain unchanged. input_receipt has mode staged, the same manifest_digest
meaning, and an existing ArtifactRef as reference instead of the shared reference.
Coordinator identity, full prepared receipt, pinned report and 64 KiB projection
rules apply unchanged; diagnostics/preflight semantics remain native.

Effective advertised source modes are the intersection of implemented support
and enabled protected policy. Advertise staged only after its native path is
implemented and enabled; profiles/root aliases must reflect effective support.
Unsupported or disallowed requests fail through the existing native boundaries
before dependent capture/dispatch. Phase 2's shared-only release continues to
reject staged as unsupported/not_applied before creating preparation work.

Qualification must establish staged input handling in the actual selected
installation. Do not infer staged support solely from a Phase 2 worker's
preparation-input-v1 advertisement. Reuse installed software identity/readiness
and assignment eligibility so a shared-only installation cannot receive a
staged assignment. The concrete qualification mechanics stay with those native
owners; do not redesign ordinary worker capabilities or protocols.

### Captured archive and worker access

Use Phase 2's finite selection and immutable manifest: schema_version 1, sorted
files with unique project-relative POSIX path, size_bytes and sha256, and native
canonical manifest hashing. At most 100 includes and 4,096 captured files are
allowed. Includes are explicit files/directories, not globs or an implicit whole
project upload. Do not include datasets, environments, credentials or unrelated
files by default. The selected config must be a captured regular file.

Staged input receipt.reference is an existing ArtifactRef for a committed
regular-file archive containing that manifest and selected closure. The archive
is published completely before the reference becomes ready or a child dispatches.
Phase 2's initial accepted operation may precede capture completion. Detected
file/list changes remain source_changed; consumed bytes do not imply an atomic
Git revision. Preserve the original accepted profile/configuration snapshot.

Selected and expanded file bytes must fit 64 MiB. The archive plus other
assignment inputs must fit the existing aggregate 64 MiB transfer limit. Excessive
capture/packing size fails with bounded input_limit_exceeded evidence before
dispatch. Apply expansion/destination checks before worker input readiness so
compressed size cannot bypass extraction bounds.

Use the existing committed input artifact/relay path. Extract beneath the
assignment-owned workspace, never over the live installation or another run.
Reject absolute/traversing member paths, symlinks, special files, duplicate
destinations, excessive file counts or expanded size. Verify the manifest and
captured content before exposing readiness. The relay owns bytes, checksum and
transfer replay; extraction owns archive destinations and expanded boundaries.
Each validation stays at its authoritative real boundary.

The private preparation input binding provides the verified directory to the
installed child. It passes no coordinator credential or authority access, and
ordinary path-bearing semantic-data rejection remains enabled. Local workers
use the same receipt/verification semantics; local access may avoid relay copies.
A missing shared mapping never implicitly selects staged mode.

The child composes once, checks once, and commits the existing report. Publication
validates the recorded child/input/profile identity and exact requirements as
before. The target cannot retain B's scratch path or depend implicitly on this
archive. Prepare on B and later execute portable intent on eligible C using
compatible installed code and supported native data/artifact bindings.

### Recovery, retention and compatibility

Use Phase 2's accepted operation and reserved child/target identities. A lost
response or interrupted transfer rejoins that operation and native transfer
replay; it does not reserve a new child or recapture after a ready input receipt.
An interrupted capture before a ready receipt follows Phase 2's operation-owned
temporary cleanup/retry rule. Incomplete extraction is never input-ready.

Cancellation during capture, transfer or child activity uses the same publication
claim and native termination/release rules. Acknowledgement, disconnection or
partial bytes are not cancellation proof. No post-cancellation path publishes a
target without the already-defined claim ordering. Repeated terminal requests
observe the actual result. No target auto-submission is added.

The captured archive/report remains pinned by operation ownership; assignment
scratch follows terminal/release cleanup. Existing authorized artifact tooling
provides complete evidence. No operation delete, automatic expiration or generic
download API is added.

Open Phase 2's coordinator schema-13 state without another root migration.
Preserve accepted/pending/terminal shared operations, snapshots, receipts, stable
identities and read-only replay. Worker roots and journals remain at schema 12.
The common request/result/reference storage accommodates this second mode; no
new durable lifecycle is needed. Recheck actual predecessor source. A required
incompatible format change is a manager stop, not permission to reset roots or
silently revise approved schemas. Existing ordinary/shared assignments retain
their decode and launch contracts.

Private archive packing, extraction helpers and input-access wiring remain
implementation choices. Use existing native primitives where their semantics
match; avoid speculative public formats or registration machinery.

## Implementation Walkthrough

This phase extends the input path of the already working preparation operation.
The following sketches explain the additional work; private helper names and
archive packing choices are illustrative rather than new public contracts.

### Core changes and the unchanged handoff

| Area | Change | Existing behavior reused |
| --- | --- | --- |
| Preparation capture owner from Phase 2 | Pack the finite captured selection and manifest into a committed regular-file archive | Accepted intent, file selection, source-change evidence and manifest hashing |
| `queue/_remote_stage_execution.py` and native artifact helpers | Deliver the committed archive and bind verified extracted input to the child | Relay integrity/replay, assignment ownership, fencing and worker supervision |
| Preparation input extraction | Enforce destinations, expanded size/count and manifest/content identity before input readiness | The same installed preparation child and report |
| Deployment/readiness/eligibility owners | Expose enabled staged support and qualify the actual selected installation | Protected profile snapshots, ordinary software requirements and placement |
| Client/CLI and retained-state consumers | Accept the added mode through the existing request and reopen earlier shared operations | Operation IDs, cancellation, bounded results, report validation and canonical publisher |

The common handoff remains a verified preparation directory on the worker and
the committed report back to the coordinator. Only the route to that directory
changes:

| Property | Shared mode | Staged mode |
| --- | --- | --- |
| Coordinator capture | Complete snapshot on configured shared storage | Complete archive in the existing artifact store |
| `input_receipt.reference` | Finite `loom.shared-preparation-input` reference | Existing committed `ArtifactRef` |
| Worker access | Resolve protected shared mapping and verify the snapshot | Relay archive, extract under assignment workspace and verify |
| After verification | Run the fixed child and return the common report | Run the same child and return the same report |
| Target execution inputs | Compatible installed code and explicit supported bindings | Same requirement; the preparation archive is not implicit target input |

The shared request can therefore become a staged request by changing its mode,
with distinct example IDs for this new operation:

```json
{
  "operation_id": "prepare-staged-042",
  "run_name": "staged-042",
  "source": {
    "mode": "staged",
    "root": "projects",
    "path": "example-project",
    "include": ["configs"]
  },
  "config_path": "configs/experiment.yaml",
  "preparation_profile": "example-cpu"
}
```

The authored project is still visible to the coordinator. This mode transfers
selected preparation inputs from coordinator to worker; it does not upload a
client laptop's checkout. Changing an already accepted operation's mode is
changed intent and conflicts, so this example uses its own operation/run names.

### Capture, relay and extraction

At the coordinator, use the existing operation and capture owner, then expose
the archive reference only after complete publication. This sketch shows the
successful capture path; Phase 2's cancellation/recovery owner still controls
whether the recorded child can proceed:

```python
# Pseudocode on coordinator A, under the accepted operation's ownership.
capture = capture_selected_regular_files(accepted_source)
archive = pack_manifest_and_files(capture)
check_aggregate_assignment_size(archive, other_assignment_inputs)
archive_ref = commit_preparation_archive(archive)
input_receipt = {
    "mode": "staged",
    "manifest_digest": capture.manifest_digest,
    "reference": native_plain_data(archive_ref),
}
persist_ready_input(operation_id, input_receipt)
# Existing orchestration admits/dispatches the same reserved preparation child.
```

`capture_selected_regular_files` represents the Phase 2 selection and consistency
rules, including finite selected bytes. Packing adds archive/aggregate limits;
neither helper introduces a new capture index or durable operation format.
The ready receipt means the coordinator's captured input is complete. Worker
input readiness is later, after transfer and verification.

```python
# Pseudocode in B's native assignment input handling, before the child reads it.
archive_path = relay_materialize(assignment, archive_ref)
verified_directory = extract_and_verify(
    archive_path,
    assignment_workspace,
    expected_manifest_digest=input_receipt["manifest_digest"],
)
bind_preparation_directory(assignment, verified_directory)
# The installed child now follows Phase 2's compose/check/report path.
```

The relay proves delivery integrity and owns transfer replay. `extract_and_verify`
stands for the destination, type, duplicate, expansion and manifest checks at the
filesystem boundary. It must not expose a partially extracted directory as ready.
The private binding grants access to this preparation input only; it does not
weaken ordinary semantic path validation or grant coordinator store credentials.

The bounds apply at different points for concrete reasons: 100 includes and
4,096 files bound selection; 64 MiB selected content bounds capture; 64 MiB
expanded content bounds extraction; the archive plus other assignment inputs
must also fit the existing aggregate 64 MiB relay limit. A selection exactly at
the content ceiling may therefore exceed the transfer ceiling once packed.
Compression does not excuse an oversized expanded archive or an unsafe member.

### Enabling the mode and recovering work

Implemented support and protected policy must both allow staged input. Readiness
also qualifies the actual selected worker installation, so a shared-only Phase 2
installation cannot receive this assignment merely because it advertised
`preparation-input-v1`. The concrete checks remain with existing software identity
and eligibility owners; no automatic environment modification occurs.

After an interrupted transfer, reconcile the same ready archive reference and
reserved child through native relay replay. After a restart, a ready capture
remains authoritative despite author edits. Partial extraction is never readiness,
and cancellation follows the same claim/release ordering as shared preparation.
The report, publication, receipt size and retention contracts continue at their
Phase 2 owners.

The retained-state check is concrete: reopen a coordinator schema-13 root
containing pending and terminal shared operations, use their original references
and IDs, and replay completed preparation read-only. Worker roots/journals stay
on 12. This extension needs no second migration because Phase 2's common input
receipt already distinguishes delivery modes. Validation adds transfer/extraction
and compatibility cases while reusing unchanged common lifecycle evidence.

## Proportionality

The accepted non-shared workflow justifies an archive and its extraction boundary.
Separating that boundary gives a focused PR after a complete shared lifecycle,
without postponing cancellation/recovery or introducing schema-only scaffolding.
Reuse the operation, scheduler, report, publisher, relay and retained-state owners.
The final stage still requires both modes; this is sequencing, not scope removal.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| Only implemented/allowed modes are exposed | Native effective metadata and admission | Staged advertised or requested against shared-only code/policy | Before/after phase capability cases and unsupported refusal |
| Selected installation can consume staged input | Readiness/software requirement and assignment eligibility | A shared-only worker would misinterpret a staged assignment | Real qualified staged worker; incompatible earlier installation refused |
| Captured bytes become verified preparation input | Capture, native relay and extraction at their respective boundaries | Interrupted transfer, digest mismatch or archive escape changes input/readiness | Finite archive, destination/expansion rejection and actual disjoint-root worker |
| One operation owns recovery/cancellation | Existing Phase 2 linkage and lifecycle | Retry during transfer could duplicate a child or bypass cancellation | Same-ID replay, interruption/restart, cancellation and release evidence |
| Preparation input does not pin target execution | Existing runtime/semantic owner | B scratch data would fail on C | Portable target consumption and unsupported scratch intent refusal |
| Earlier shared work survives | Existing schema, request/result and retained reference owners | New input code invalidates retained shared operations or cleanup evidence | Schema-13 reopen, unchanged shared IDs/receipts and pinned archives |

## Implementation Slices

Each step includes focused tests; the phase is one PR with a complete staged
journey at its merge gate.

1. Add archive capture/commit over the existing finite selection and manifest;
   prove limits, source-change handling and complete-reference publication.
2. Connect native relay, contained extraction and selected-installation access;
   prove destination/expansion/checksum boundaries and actual disjoint-root input.
3. Enable policy-filtered staged support through the common client/CLI and
   capability metadata; prove shared-only/unsupported and incompatible-worker
   refusal alongside shared compatibility.
4. Prove staged prepare/submit/execute plus causal transfer/restart/cancellation
   and retained-state cases; document both source modes and their limits.

## Test And Validation Plan

| Suite | Required or deferred | Minimal assertions |
| --- | --- | --- |
| Package | Required | New input helpers do not pull diagnostics/MCP/project code into lower runtime imports |
| Unit | Required | Finite selection/archive, manifest identity, extraction traversal/link/special-file/duplicate rejection, expanded and aggregate byte/count bounds, complete capture before readiness |
| Contract | Required | Same native request/result/report/receipt; truthful enabled modes and qualified installation support; native guard/error/projection meanings retained; no implicit target file delivery or auto-submit |
| Integration | Required | Real local and disjoint-root remote workers use selected Python and verified staged input; coordinator needs no project environment; produce and publish the checked composition and actual portable target output |
| Causal lifecycle | Required | Interrupted capture/transfer/extraction and lost response followed by same-ID restart/replay; ready receipt survives author edits; cancellation during staged delivery obeys claim/release rules; pinned evidence survives cleanup |
| Placement/inputs | Required | Prepare B and execute on compatible C without assumed access to B's scratch; incompatible installed handling/target identity and unsupported scratch intent refused |
| Retained/shared compatibility | Required | Existing shared success and shared-only mode refusal cases remain applicable at their release boundary; Phase 2 schema-13 pending/terminal shared records reopen unchanged with worker schema 12; no second root migration |
| CLI/E2E | Required | JSON staged preparation, operation/read/wait, guarded reconnect, submit and explicit cancellation through both connection options with native outputs |
| Physical NAS / Codex | Deferred to Phase 4 release acceptance | Disjoint temporary roots establish transport behavior, not actual NAS or Codex integration |

Reuse Phase 2's general publication, bounded-report, identity, recipe and
post-claim cancellation evidence while unchanged. Add causal staged cases at the
new boundary; do not repeat every common case across all deployment dimensions.
Required new source-mirrored tests supplement these existing starting owners:

```sh
uv run --locked --group dev pytest tests/unit/loom/queue/test_deployment.py tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_agent_service_lifecycle.py tests/integration/queue/test_local_daemon_production.py tests/package/test_import_boundaries.py
```

Final commands:

```sh
make validate-pr
make test-summary
```

## Risks, Review, And Stops

Independent review focuses on archive containment/expansion, mode/capability
truthfulness, qualified installation, transfer/readiness and operation joins,
cancellation/retention, and compatibility with retained shared work.

Stop if actual predecessor source requires another durable schema/lifecycle,
loosening ordinary semantic paths, code installation, or a parallel transfer
framework. Resolve the smallest in-scope remedy with the manager; never broaden
the accepted product boundary silently. Accepted limits remain finite inputs,
one existing preparation environment, embedded authority/no SLURM profiles,
retained evidence and no automatic source deployment.

## Executor Handoff

Read this card, manifest Shared Constraints and the linked Phase 2 common-contract
headings. Reconcile actual merged native owners, then implement the four steps.
Do not reopen coordinator topology, lifecycle/receipt meaning, existing-environment
policy or target portability. Phase 4 consumes the same API with both modes.

## Workflow State

- Manager preparation: approved boundaries reconciled against the actual merged predecessor on 2026-09-11; no refinement needed
- Expanded planning: common design and four-phase boundary review passed
- Implementation: started; bounded archive/extraction work delegated, native lifecycle/assignment/qualification and journeys owned by manager
- Refiner: not needed
- Pre-submit gate: not run
- Independent review: required before implementation merge
- Blocker corrections: 0/3
- PR and merge: not created

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Not started |
| Tests added or updated | Not run; planning only |
| Validated revision/tree state and evidence | No implementation receipt |
| Validation-relevant changes after evidence | Not applicable |
| PR, review, and merge | Pending |
| Residual risk and cleanup | Retained Stage 40 worktree and phase branch verified; predecessor exact branches retired. No real roots or environments changed. |
