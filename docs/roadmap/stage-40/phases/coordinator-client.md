# Phase 1 Execution Plan: Direct Coordinator Control

## Metadata

- Status: in_progress
- Roadmap stage and phase: 40 / 1
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-40-p1-coordinator-client
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `1a21a78df89f766ef5c19eb6607512a41866ea17`; planning evidence is `382065646608f4f19fed17a6fc0ecc9fce4a6e3f`.
- PR target: develop
- PR title: Stage 40 Coordinator Client, Agent Preparation, And MCP - Phase 1: Direct Coordinator Control
- Dependencies: stage plan approved on 2026-09-10; no earlier phase
- Workflow path: expanded for public API, authentication, failure and concurrency boundaries
- Blockers: none

### Execution startup

The manager bootstrapped the manifest's persistent stage worktree on 2026-09-11
before startup review or edits. The shared setup/preflight gates verified
`/nas/home/can134/work/loom-worktrees/stage-40`, branch
`agent/stage-40-p1-coordinator-client`, coordination branch `agent/stage-40`,
and the clean published base above. The control checkout is the manifest's
`/nas/home/can134/work/loom-worktrees/control`.

The approved packet is published by PR #295. The existing independent readiness
receipt is reused: changes since its evidence revision concern explicit GPU
process coexistence and repository workflow tooling. The GPU policy changes in
deployment/loading and the transport test remain compatible with this phase;
they do not change native client, authentication, inspection or wait contracts.
Current client and transport definitions still match the owner map below.
No refinement or new product-plan review is needed.

An optional executor authored the initial draft because the four implementation
steps span native dispatch, two transports, compatibility adapters, CLI and
concurrency tests. That handoff is complete. The manager now owns source, tests,
product documentation, acceptance correction and delivery. The delegation did
not change accepted scope or gates.

Validation selection starts with the owner map in Test And Validation Plan and
adds source-mirrored facade/config tests, real Unix/mTLS parity and fault/progress
tests. Read the assertions before selecting. Shared codec and dispatch changes
affect public Python, legacy socket and CLI consumers, so both approved full
commands remain required. New protocol consumers, changed worker/query behavior,
or failed legacy assertions trigger affected-suite expansion; no physical fleet
or scientific workload is authorized by these local validation commands.

## Objective And Context

Python and CLI users can submit, inspect, wait and cancel through the same client
on the coordinator host or another machine. An HTTPS client has no worker root,
registration, journal or supervisor. This delivers FR-40-01/02/08/09 and the
native foundation of FR-40-10/12; DQ-40-01/05 govern the design.

Preparation and MCP are later phases. Do not expose preparation methods that
only raise NotImplementedError in this phase.

## Current Source And Harness

Paths are repository-relative:

- `src/loom/queue/local_daemon.py`: LocalDaemonClientView, canonical admission,
  page, operation and wait models; actual authorization/application owners.
- `src/loom/queue/local_daemon_transport.py`: socket client/server, queue lookup,
  injected inspection, eight request slots/seven wait slots, half-second waits.
- `src/loom/queue/agent_session_transport.py`: HTTP dispatcher, certificate/role
  policy, worker-oriented HTTP client, separate query inspection route.
- `src/loom/queue/deployment.py`: protected client-file/path loading.
- `src/loom/diagnostics/run_inspection.py`: native inspection union and decoder.
- `src/loom/cli/queue.py`: current direct socket construction and projection injection.
- Existing tests: `tests/unit/loom/queue/test_local_daemon.py`,
  `tests/unit/loom/cli/test_queue.py`,
  `tests/integration/queue/test_agent_session_transport.py`,
  `tests/integration/queue/test_local_daemon_production.py`,
  `tests/contracts/test_run_inspection_contract.py`,
  `tests/package/test_import_boundaries.py`.

The HTTP client subset already implements submit/status/cancel. Its general
errors currently collapse into 403, and its worker client retains a shared
connection. Unix calls lack I/O deadlines. These are the gaps to address; this
is not a replacement scheduling or execution API.

## Scope

Implement the high-level `src/loom/coordinator.py` client facade, shared native
request/response mechanics, missing client HTTP operations, connection loading,
and CLI migration. Extract matching application dispatch and error ownership.
Keep transport authentication, framing and worker lifecycle with their owners.

Preserve QueueClient/QueueService, worker polling/replay/supervision, operator
methods, query-only credentials, durable admissions and all existing record names.
No daemon-root migration occurs in this phase.

## Fixed Contracts And Private Discretion

### Public Python surface

`from loom.coordinator import CoordinatorClient, CoordinatorClientError` is
the new public integration entrypoint. Native models remain importable from their
existing owners. `CoordinatorClient.from_unix_socket(path, *,
expected_coordinator_id=None)` and `CoordinatorClient.from_connection_file(path,
*, expected_coordinator_id=None)` select connections without starting a service,
registering an agent or sending an admission. Every facade method also accepts the
same optional keyword guard for a saved receipt; a call value must equal a
configured connection default when both are present. The first operation connects/
negotiates. Context exit/close releases only client resources.

| Method | Native result / behavior |
| --- | --- |
| describe_connection() | Typed connection description: protocol_version, transport, coordinator_id, coordinator_epoch, capabilities, source_modes, preparation_profiles, source_roots; aliases only |
| status() | DaemonStatus |
| admissions(limit=20, cursor=None) | AdmissionPage |
| admission(admission_id) | LocalDaemonAdmissionDetail |
| admission_for_queue_item(queue_item_id) | LocalDaemonAdmission |
| agents(limit=20, cursor=None) | AgentPage |
| agent(agent_id) | AgentProjection |
| inspect_run(run_uri) | Existing RunInspectionResponse success/failure union |
| operation(operation_id) | LocalDaemonOperation |
| wait_operation(operation_id, timeout_seconds=25) | OperationWaitResult: TERMINAL or TIMEOUT |
| submit(LocalDaemonAdmissionRequest) | LocalDaemonAdmission |
| wait_admission(admission_id, expected_revision, timeout_seconds=25) | AdmissionWaitResult: CHANGED, TERMINAL or TIMEOUT |
| cancel(queue_item_id) | LocalDaemonAdmission acknowledging the native cancellation request |
| wait(queue_item_id, timeout_seconds=None) | Existing terminal-wait convenience; raises TimeoutError at its explicit deadline |

New observation methods accept finite durations in [0, 25]; zero makes one
nonblocking observation. The explicit terminal convenience renews bounded waits,
including an unlimited overall wait when its caller deliberately passes None.
Page limits are integers 1–100, with default 20 and native opaque cursors.

Lookup followed by detail is two observations, not an atomic combined snapshot.
Availability is observed capacity, not a reservation. Admission ACTIVE is not
proof a stage is running. Native run URIs refer to coordinator-owned runs, not
paths the client should open locally.

### Connection and application protocol

A protected HTTPS connection file has exactly this native schema:

```yaml
schema_version: 1
kind: loom.coordinator-client
transport:
  kind: https
  url: https://coordinator.example:8443
  server_ca_path: /etc/loom/ca.crt
  certificate_path: /etc/loom/client.crt
  private_key_path: /etc/loom/client.key
expected_coordinator_id: coordinator-production-001
```

`expected_coordinator_id` is the only optional top-level field and is the default
guard for calls through that file; omitting it preserves the original unguarded
connection behavior. Reuse protected owner/file/path rules and relative-path
resolution against the file's directory. This is not a worker deployment role.
TLS validates CA and service name, requires an enrolled client certificate, and
follows no redirects. Unix uses current owner permissions/peer identity. Client
permissions remain deployment-wide; MCP annotations and shared OS identity create
no new isolation.

Extend the existing handshake additively with `daemon-control-v1`; keep application
protocol version 1 and existing response keys. Preparation metadata lists are
empty until Phase 2 supports them. Older clients retain their existing operations.
A new facade requires the capability for its unified contract and reports
unsupported service before dependent mutations. The legacy socket facade keeps
working with the established old-server subset without requiring a new handshake.

The effective `expected_coordinator_id` travels in the common native request
envelope. The coordinator compares it with its stable ID before dispatch, including
before an operation/admission/run lookup or any mutation; a prior handshake or
client-side comparison alone is insufficient. Mismatch is a `conflict` at the
coordinator boundary, with null mutation outcome for a read and `not_applied` for
a mutation. The error IDs preserve expected and observed coordinator identity.
When the field is absent, the server follows the established request path. Older
clients and LocalDaemonSocketClient send no new metadata and retain their behavior.

Use current Unix operation names and POST `/v1/client/<operation>`, including
reads. HTTP gains admissions, admission, admission_for_queue_item, agents, agent,
operation, wait_operation, wait_admission and inspect_run. Share matching
application behavior, request validation and native serialization once.
Authenticate every request at its current boundary. Query remains read-only;
worker/operator credentials do not acquire client actions.

Client inspection follows the managed-admission restriction of the existing
HTTP query projection on both new-client transports. Before target admission,
preparation evidence will be read through its operation/child. Retain the old
Unix inspection entrypoint's established behavior through its compatibility
adapter; do not silently narrow it while extracting the shared path. Preserve the
injected projection and versioned diagnostic failure union.

### Errors, bounds and concurrency

Keep successful native payloads intact, including all admission ownership and
revision fields. An inspected failed run and a failed preparation operation are
successful reads of failure evidence, not transport errors.

For new client calls, expose one `CoordinatorClientError` in the QueueServiceError
family with structured `code, boundary, operation, ids, evidence_refs,
mutation_outcome`. Add an `error_detail` schema-1 object with those fields to the
existing wire error envelope; retain its readable `error` string and `ok/result`
conventions. Do not rewrite native admission/result schemas. Minimum codes:
invalid_request, unauthorized, not_found, conflict, unsupported, unavailable,
deadline_exceeded, capacity_exhausted, result_too_large, invalid_response and
internal_error. Boundaries identify connection, authentication, client_protocol
or coordinator. Owner codes in native diagnostic/operation results remain native.

Mutation outcome is null for reads; otherwise not_applied or applied requires
authoritative evidence, and unknown is used when commitment cannot be determined.
A lost write response is unknown; failure before dispatch is not_applied.
An HTTP 403 alone does not identify authorization under the old protocol.
Server errors after possible mutation must not claim not_applied merely because
an exception occurred. Preserve evidence and original identifiers.

Reads may be repeated within budget. There is no blanket mutation retry helper.
A lost submit reply is reconciled by its same queue_item_id or exact replay;
an immediate not-found may race the original request. Changed run URI/queue ID
must retain native conflict semantics.

Use a 30-second cumulative client request budget for finite calls. Connection,
request write and every response read consume its remaining duration, preventing
a trickle sender from restarting the budget. A request admission wait consumes
the same budget. Observation time is at most 25 seconds; HTTPS renews at most
five-second server wait slices under the existing ten-second HTTP-call cap;
Unix keeps its current half-second server slices. Report TIMEOUT for an ordinary
completed observation budget; I/O failure is a classified error. A transport error
during an explicit terminal wait is not fabricated terminal execution.

Use bounded separate client connections and server wait capacity. A wait cannot
monopolize a worker connection, all ordinary request slots or the mutation lock.
Preserve existing Unix reserved ordinary capacity and add equivalent HTTP
backpressure. Replace the socket client's five-millisecond saturation retry loop
with bounded backoff/remaining-budget handling. Counts and executor implementation
are private, but worker/client progress under saturation is an acceptance contract.

Client responses allow up to the existing 1 MiB inspection/Unix bound, with the
supported native nested-failure decoder; oversized results produce an explicit
bounded error. Preserve worker-message limits and diagnostic structural limits.
Never silently truncate a canonical admission or flatten nested failure evidence.

### Migration, removal and dependency direction

One lower-level owner implements native control method behavior/decoding and
matching dispatch. The public integration facade decodes diagnostics above queue.
LocalDaemonSocketClient remains a thin compatibility adapter preserving its
constructor, default limit 100, old timeout keyword conventions, terminal
TimeoutError, AdmissionNotFoundError and other legacy QueueServiceError behavior.
Operator-specific methods retain their existing separate owner. Wrappers may
translate signatures/errors; they must not duplicate application logic.

Extract compatible HTTPS mechanics from LocalDaemonAgentHttpClient; keep worker
journal, supervisor, polling, resources and worker error semantics there. Do not
force this extraction to redesign query or worker protocol behavior.

CLI client commands obtain the unified client from mutually exclusive
`--endpoint PATH` or `--connection PATH` and accept optional
`--expected-coordinator-id ID`, forwarded as the native call guard. Preserve old
command names, positional arguments, defaults, JSON fields and exits when the new
option is absent; translate new errors at the existing CLI boundary. Keep
administrative commands out of this connection migration unless they already
belong to the client view. Remove duplicate decoding/dispatch branches after their
consumers switch. Update public API, queue/CLI, deployment, structure and glossary
docs with actual behavior.

Private transport/helper names, composition versus inheritance of adapters and
connection-pool mechanics are implementation choices. No global registry or
general call-any-method API is authorized.

## Implementation Walkthrough

This section explains how the fixed contracts fit together. Public examples use
the proposed API; internal helper names below are pseudocode, not additional
interfaces or a required module layout. Runtime implementation has not started.

### Core changes and why they belong here

| Area | Implement, migrate or remove | Reason |
| --- | --- | --- |
| New `src/loom/coordinator.py` | Add connection selection and the typed integration facade; combine queue results with the existing inspection decoder above queue | Python, CLI and MCP need the same operation meanings without importing a worker service |
| `queue/local_daemon.py` and shared native control helpers | Reuse client-view authorization and application operations; share their request/result handling | The coordinator already owns admission, scheduling and durable state |
| `queue/local_daemon_transport.py` | Delegate common control mechanics, preserve Unix authentication/framing and the legacy adapter, add finite I/O | Existing callers retain their behavior while the new client gains bounded requests |
| `queue/agent_session_transport.py` | Complete client HTTP routes and extract compatible HTTPS mechanics from the worker client | A remote submitting client needs neither a worker journal nor polling/supervision |
| `queue/deployment.py` and `cli/queue.py` | Load the protected client connection and migrate client command construction | Deployment changes the connection option, while commands and native results keep their meaning |
| Extracted internal branches | Remove duplicated codecs/dispatch after migration and replace busy saturation retry | One correction should fix both transports; long waits must leave control and worker capacity |

The dependency direction is deliberate: the public facade can use queue and
diagnostics, but the queue compatibility adapter delegates to shared helpers
below that facade. Importing `loom.coordinator` back into queue would create the
wrong dependency merely to share a few calls. Worker-specific state stays in the
worker HTTP client, and operator/query operations retain their own policy.

### A native client call from start to finish

The following proposed usage assumes a run has already been prepared by an
existing workflow. Phase 1 itself adds no preparation engine. Sample paths and
IDs must be replaced with deployment values.

```python
from loom.coordinator import CoordinatorClient
from loom.queue import LocalDaemonAdmissionRequest


def submit_and_observe(connection_file, prepared_receipt, coordinator_id):
    with CoordinatorClient.from_connection_file(
        connection_file,
        expected_coordinator_id=coordinator_id,
    ) as client:
        admission = client.submit(
            LocalDaemonAdmissionRequest(
                queue_item_id="experiment-042",
                run_uri=prepared_receipt.run_uri,
            )
        )
        detail = client.admission(admission.admission_id)
        observation = client.wait_admission(
            admission.admission_id,
            expected_revision=detail.admission.revision,
            timeout_seconds=25,
        )
        return admission, observation
```

Using `from_unix_socket("/path/to/coordinator.sock", ...)` changes connection
selection only. The returned admission, revision, wait result and error meanings
are identical. Closing the context releases the connection and leaves accepted
work running. A client on a fleet worker host follows this same direct path;
its worker daemon does not forward the call.

On the server, both transports reach the same application behavior. This sketch
shows the ownership/order rather than prescribing helper signatures:

```python
# Pseudocode at the authenticated native request boundary.
principal = authenticate_current_request(transport_request)
request = decode_native_control_request(transport_request)
check_expected_coordinator_id(request, coordinator.stable_id)
result = dispatch_authorized_client_operation(principal, request)
response = encode_native_result(result)
```

Transport authentication identifies the caller; the native client view still
authorizes the requested action. The identity check precedes lookup and mutation
on every request. The surrounding native boundary classifies failures using the
existing error envelope plus `error_detail`. A successful earlier handshake
cannot replace that per-request check after reconnect.

### What a caller keeps and how it recovers

| Value | Meaning and next use |
| --- | --- |
| `coordinator_id` | Namespace owner; send it back as `expected_coordinator_id` when recovering saved work |
| `queue_item_id` | Caller-selected submission identity; retain it for same-intent replay, lookup and cancellation |
| `admission_id` | Coordinator's admission record identity; use it for detail and revision waits |
| Admission `revision` | Version of the last observation; use it to wait for a change, not as a resource reservation |
| `run_uri` | Canonical run identity used for submission/inspection; it is not a promise of a client-local path |

A normal observation TIMEOUT means the observation window ended. It does not
mean the job failed or authorize cancellation. A lost submission response may
mean the coordinator accepted the request but the reply disappeared; the native
error therefore reports an unknown mutation outcome. Recover using
`admission_for_queue_item()` or the exact original submission under the same
guard and queue ID. An immediate missing admission may race the original call.

The finite budget includes capacity admission, connection, writes and reads.
Repeated wait slices consume the same call budget instead of resetting it.
Separate bounded wait capacity lets a quick status or explicit cancellation and
worker traffic continue while other clients observe jobs. These rules are part
of native control, so Phase 4 inherits them rather than reimplementing them.

## Proportionality

The three current callers justify a shared API. Existing codecs, TLS, view policy
and diagnostics provide most of it. Public record renaming, changing HTTP to a
REST resource design, merging opaque queues, new service daemons and automatic
root upgrades are unnecessary.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| One admission and exact replay | Existing daemon admission transaction | Lost client response could tempt new identity | Exact retry and same-ID lookup |
| Current authorization | Client view plus transport principal resolution | Worker/query credential used as client | Negative role and policy-revocation cases |
| Diagnostic meaning | Existing projection/decoder | Remote result serialization could flatten failure | Native success/failure parity within bounds |
| Bounded observation and progress | Transport admission/I/O owner | Slow peer or saturated waits stalls control | Deadline and simultaneous worker/ordinary call |
| Receipt coordinator identity | Native application dispatcher | Saved ID is replayed after endpoint now names another coordinator | Server rejects before lookup/mutation on both transports |
| Old API compatibility | Socket and CLI adapters | Existing caller uses old defaults/errors | Representative prior API and CLI tests |

## Implementation Slices

Each step includes focused tests. These are reviewable steps within one phase PR;
authentication, mutation uncertainty and finite I/O are part of the first release.

1. Establish shared native control validation, serialization/decoding and matching
   dispatch from existing fixtures; prove representative native/legacy behavior
   and import direction.
2. Complete the public facade, both transports, diagnostic composition, protected
   connection loading and capability/identity guards; prove real Unix/loopback TLS
   parity, role scope and wrong-coordinator rejection.
3. Complete classified errors, finite I/O, response bounds and independent wait
   capacity; prove lost-response semantics and worker/ordinary progress under
   saturation without changing worker/query behavior.
4. Migrate CLI and socket consumers, delete extracted duplicates and update docs;
   prove prior defaults/errors/output and the complete native/CLI journey.

## Test And Validation Plan

| Suite | Required or deferred | Minimal assertions |
| --- | --- | --- |
| Package | Required | Facade imports without MCP SDK, worker service startup or project imports; legacy imports preserved |
| Unit | Required | Codecs/config/deadlines; expected-ID defaults/keywords/error adapters; CLI connection exclusivity |
| Contract | Required | Same native admission/inspection/wait payloads; stable replay; optional guard omitted compatibility; query-only and client scope |
| Integration | Required | Real Unix and loopback mTLS; remote client has no worker root; wrong CA/role; expected-ID mismatch reaches no lookup/mutation; lost response and wait saturation with progress |
| E2E | Required where CLI changes | Submit/status/lookup/wait/cancel via both connection options; guarded reconnect; old output preserved |
| Physical multi-machine / Codex | Deferred to Phase 4 acceptance | These are not needed to prove extraction and loopback parity |

Targeted commands, adjusted only for new source-mirrored test paths:

```sh
uv run --locked --group dev pytest tests/unit/loom/queue/test_local_daemon.py tests/unit/loom/cli/test_queue.py tests/integration/queue/test_agent_session_transport.py tests/contracts/test_run_inspection_contract.py tests/package/test_import_boundaries.py
```

Final commands:

```sh
make validate-pr
make test-summary
```

Run required new tests as well; the existing command is an owner map, not a
permission to omit new-client coverage. Reuse successful evidence until changed.

## Risks, Review, And Stops

- Independent implementation review focuses on role scope, mutation uncertainty,
  server-side coordinator identity guarding, passive waits, compatibility and
  dependency direction.
- Stop for manager resolution if an upstream protocol change invalidates the
  preserved subset, or a required public contract cannot be maintained.
- Do not expand into operator redesign, worker transport replacement or root
  migrations to fix a local client problem.
- Accepted debt: legacy public names remain; a separately justified compatibility
  decision is required to remove them.

## Executor Handoff

Read this card in full and the manifest's Shared Constraints. Implement the four
slices above. Do not reopen direct coordinator topology or the ownership split.
The manager reconciles new published upstream changes before branch creation.

## Manager Acceptance Correction

One scoped correction completes the native control boundaries missing from the
initial draft at `49295a67c2ea0d5eaef728e82dee2d918624f2b2`. The manager owns
this correction; accepted behavior and phase scope remain unchanged.

The implementation now shares request validation, dispatch, native result
codecs and client observation behavior below the public facade. Unix and HTTPS
use that dispatcher; the legacy socket adapter delegates to the same client
owner with its original defaults, timeout conventions and inspection scope.
The public facade keeps diagnostic decoding above queue. Deployment owns the
protected connection loader; the worker and native clients share the compatible
HTTPS connection factory. CLI client commands always select the unified client.

Finite I/O uses cumulative budgets and bounded concurrent exchanges, including
capacity admission and stalled connection setup. HTTP waits reserve ordinary
capacity independently of worker requests. Client request decoding accepts native
fractional wait durations without widening worker-message decoding. HTTP response
reading preserves structured errors when the completed response closes its
connection. Capability negotiation rejects an older application service before
any dependent mutation. Server identity checks precede lookup and mutation on
each request. Error outcomes preserve original IDs and distinguish known refusal
from an unknown outcome after possible commitment.

Causal coverage includes real Unix/HTTPS lost-reply recovery with same-ID replay,
per-request guards bypassing negotiation, new-versus-legacy inspection scope,
revocation and wrong CA/role, post-commit receipt failure, slow Unix replies and
HTTP headers/bodies, independent HTTP observers with ordinary/worker progress,
stalled setup capacity, native nested failure evidence and response size limits,
portable imports, and native/legacy page and CLI timeout compatibility. The CLI
submit/status/lookup/cancel/wait journey runs over both connection options.

Final full validation and independent PR review remain required. Targeted passes
are evidence for the selected contracts only, not a substitute for those gates.

## Workflow State

- Manager preparation: startup verified on 2026-09-11; approved contracts and current source reconciled
- Expanded planning: common design and four-phase boundary review passed
- Implementation: shared native boundaries implemented; manager validating the completed correction
- Refiner: not needed
- Pre-submit gate: pending final validation and manager acceptance
- Independent review: required on the actual PR head before implementation merge
- Blocker corrections: 1/3 in progress; native control boundary completion
- PR and merge: not created

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Public coordinator facade; private queue control/client/transport owners; Unix/HTTPS adapters; deployment connection loader; queue CLI; native client product docs |
| Tests added or updated | Native client unit tests, import boundary, CLI compatibility, real Unix/mTLS control recovery/guards, native error and size bounds, and HTTP deadline/capacity/authentication fixtures |
| Validated revision/tree state and evidence | The manager's working-tree focused run passed 37 tests with 165 deselected using the native/coordinator/CLI selectors over the transport, import, client and CLI owners. Changed-file Ruff passed. Earlier static typing passed; one new test required a mapping cast, now corrected. The source-mirrored, legacy socket, CLI, inspection-contract and import pass completed with 164 passed and 1 deselected. The required fresh full gates have not started |
| Prior full evidence | The earlier draft at `49295a6` completed `make validate-pr` with exit 0: 3161 baseline tests passed, 2 skipped, 156 deselected; 162 config-extra tests passed, 18 skipped, 3166 deselected; static checks and distributions passed. `/tmp/loom-stage40-final-validate.log` and its `.exit` receipt record that result. This is not evidence for the current runtime refactor. `make test-summary` has not run |
| Validation-relevant changes after evidence | Shared runtime/transport extraction supersedes the earlier full-run evidence. The final checkpoint requires fresh full validation and test summary. Product documentation link/example checks remain valid where unchanged |
| PR, review, and merge | Pending |
| Residual risk and cleanup | Full regression and required independent review remain before merge. Persistent stage worktree retained; no PR or root migration |
