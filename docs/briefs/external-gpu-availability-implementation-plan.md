# External GPU availability: implementation plan

Status: implemented and merged into `develop` through
[PR #283](https://github.com/samcantrill/loom/pull/283).
An agent configured for GPUs 0 and 1 withdraws GPU 0 from new placements when an
external process uses it, reports the reason, and restores it after a successful
idle observation. The approved design and rationale follow; final delivery and
validation evidence appear in the execution record at the end.

The design baseline was Loom `develop` at
`09ece202ea6bcafb9e0cdeeabb6e2cbbcb5278f6`. The owner comparison below describes
that baseline and the changes implemented from it. Code and JSON snippets are
illustrations of the contracts, not complete copy-and-paste APIs. See
[runtime resource documentation](../features/runtime-resources.md#gpus-occupied-by-work-outside-loom)
for deployed configuration and inspection fields.

**1. The result we want and its limits**

Keep the configured inventory stable and compute current availability from it:

```python
available = configured - loom_claimed - externally_occupied - observation_unknown
```

These are sets of whole GPU identities, not memory quantities. CPU and memory
limits still apply independently. A job requesting two GPUs waits when only one
is available. An external job on an unselected GPU changes nothing.

| Observation on a configured GPU | New work allowed? | Reported reason |
| --- | --- | --- |
| Successful query, no GPU process, no Loom claim | Yes | `available` |
| Loom holds a prepared, active, or restored claim | No | `loom_claimed` |
| GPU process exists and Loom has no claim on the card | No | `external_process_detected` |
| Process query fails, times out, or is incomplete | No | `observation_unavailable` |
| Last usable observation is too old | No | `observation_stale` |
| Selected UUID is missing from otherwise usable evidence | No | `device_missing` |

The recommendation is to block both compute and graphics processes. This is a
deliberate conservative rule: a desktop compositor can make its GPU unavailable.
Do not silently ignore graphics or describe a compute-only query as proof that
the whole GPU is idle. If compute-only behaviour is selected instead, change
this policy and its tests explicitly; do not introduce a configurable policy
framework for one deployment requirement.

A process with an idle CUDA context still blocks the card. Neither low GPU
utilization nor spare VRAM makes a whole GPU available. NVIDIA documents process
queries separately from utilization, including compute and graphics contexts:
[NVML device queries](https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html).

For this version, `external` means GPU use outside this agent's current device
claims. It does not mean a different Unix user. We do not need to identify every
worker descendant: any process on an unclaimed card blocks it, while a claimed
card is already excluded. A leftover process after a claim's valid release also
blocks the card. Simultaneous foreign use of an already claimed GPU cannot be
reliably attributed by this rule; the status stays `loom_claimed`. Add ownership
attribution later only if contention diagnostics during active jobs are wanted.

Observation does not enforce ownership against other users. An external process
can start immediately after admission or during a Loom job. Preserve existing
claims and running processes when that happens. Do not kill, preempt, reset a GPU,
change NVIDIA compute mode, or release a claim because a monitor reports a
different state. Strong exclusion requires a shared scheduler or host controls.
MIG, fractional allocation, MPS client attribution, and enforced VRAM sharing are
outside this first implementation; unsupported observation environments must
not be presented as verified idle devices.

**2. Existing owners and the implementation changes**

| Owner | Behaviour before implementation | Change and reason |
| --- | --- | --- |
| [`queue/gpu/nvidia.py`](../../src/loom/queue/gpu/nvidia.py) | Explicit `nvidia-smi` inventory discovery, index selection, UUID binding, model and total VRAM. No process query. | Add a separate process observation operation. Inventory and rapidly changing occupancy have different lifetimes. |
| [`queue/_managed_local.py`](../../src/loom/queue/_managed_local.py): `GpuResourceProvider`, `AtomResourceProvider` | Subtracts Loom claims and provides exact private worker bindings. `prepare()` re-observes configured remaining capacity. | Give the GPU provider an injected occupancy observer and use it in observation and fresh claim preparation. Keep the existing claim journal and lock. |
| Same file: `ObserveResult`, provider composition | Carries available capacity atoms, a revision, and reflected live claim IDs. | Carry small status records alongside atoms and preserve them through composition, including devices with no available atom. |
| [`queue/deployment.py`](../../src/loom/queue/deployment.py) | Loads selected resources; standalone loop observes providers and then renews or publishes an offer. | Configure the observer once per agent capacity domain and schedule periodic refresh. |
| [`queue/agent_session_transport.py`](../../src/loom/queue/agent_session_transport.py) | Builds provider offers, retains mutations, prepares/declines assignments, and waits synchronously for a worker. | Report new observations, replay updates safely, and call due maintenance while waiting for execution or moving inputs/results. |
| [`queue/agent_sessions.py`](../../src/loom/queue/agent_sessions.py) | Owns authenticated offers, session revisions, renewal, expiry, polls and targeted deliveries. | Add an atomic availability update through this existing offer surface. An occupancy change must advance the session and offer together. |
| [`queue/local_daemon_execution.py`](../../src/loom/queue/local_daemon_execution.py) | Builds embedded and remote candidates; maintains reflected/unreflected claims and local worker futures. | Consume filtered atoms, refresh embedded observations during daemon cycles, and preserve admission ownership across offer replacement. |
| [`queue/local_daemon.py`](../../src/loom/queue/local_daemon.py), transport and CLI | Builds the embedded GPU provider; exposes agent and daemon projections. | Wire the same observer locally and expose per-GPU reasons through existing inspection commands. |

The canonical [resource specification](../features/runtime-resources.md) already
permits a provider to withdraw externally occupied resources, and distinguishes
inventory, availability, reservations, and physical admission. This proposal
fills in the built-in NVIDIA implementation of that existing separation.

There is no need for another scheduler, GPU inventory database, process registry,
monitoring daemon, downstream rphys dependency, or changes to pipeline resource
requests. The generic scheduling kernel continues to place work from available
capacity atoms. A capacity atom is simply Loom's existing record saying how much
of one resource is available.

**3. Observe processes without changing device identity**

Extend the existing NVIDIA boundary with one explicit method that queries the
selected UUIDs. Keep `NvidiaSmiGpuInventoryProvider.discover()` as inventory
discovery; do not make its result change whenever a job starts.

For the recommended compute-and-graphics policy, use the structured XML query:

```python
argv = (
    "nvidia-smi",
    "--query",
    "--xml-format",
    "--id=" + ",".join(selected_uuids),
)
completed = subprocess.run(
    argv,
    capture_output=True,
    text=True,
    check=False,
    timeout=query_timeout_seconds,
)
# Parse each GPU's uuid and processes/process_info records.
# Convert errors to per-device unknown observations, not an empty process list.
```

NVIDIA documents XML output and GPU selection by UUID in the
[nvidia-smi reference](https://docs.nvidia.com/deploy/nvidia-smi/index.html).
The installed tool's `--dtd` was inspected: it declares GPU UUIDs and process
records with PID, type and used memory. No GPU workload was launched or used as
acceptance evidence. `--query-compute-apps` alone would miss graphics workloads.

Use one batched query for selected devices. Parse only required fields with the
standard library; ignore unrelated XML fields. Require evidence for every selected
UUID. A valid explicitly empty process collection means idle; missing,
unparseable, unsupported or error-bearing process data means unknown. A process
record still blocks when its memory value is `N/A`. Known compute, graphics and
combined types block; an unrecognized process record never becomes evidence of
an idle card. A whole-command failure makes all selected devices unknown; a
localized failure only withdraws its affected device when the other records are
independently complete. Do not load the advertised DTD or external XML resources.

Keep raw process details agent-local. The coordinator only needs safe configured
device IDs, availability, fixed reason codes and observation times. Do not ship
command lines, private binding paths, stderr or usernames with offers. Distinguish
known failure categories such as timeout and permission denied where the tool
provides reliable evidence; otherwise report a generic query failure.

This reuses a dependency already required for selected NVIDIA inventory.
NVIDIA recommends NVML for compatibility across driver versions, so structured
CLI parsing is a conscious dependency tradeoff: qualify it with supported-driver
fixtures and fail safely on unsupported output. If CLI reliability proves
insufficient, replace this single observer with NVML behind the same private
callable. Do not build two backends or a plugin framework now.

**4. Let one GPU provider combine observations and claims**

Add an optional private observer dependency to `GpuResourceProvider`, or extract
a small GPU-specific helper used by it. Generic CPU/memory providers retain their
existing behaviour. A snapshot contains per-device query outcomes and process
presence, a UTC time for display, and a monotonic completion time for local age
checks. All profiles using the same agent capacity share the provider and its
observation cache.

```python
def gpu_status(device, held_claims, sample, now):
    if device.id in held_claims:
        return unavailable("loom_claimed")
    if sample is None:
        return unavailable("observation_unavailable")
    if sample.age(now) > max_age_seconds:
        return unavailable("observation_stale")
    observed = sample.for_device(device.uuid)
    if observed.missing:
        return unavailable("device_missing")
    if not observed.query_succeeded:
        return unavailable("observation_unavailable")
    if observed.has_gpu_process:
        return unavailable("external_process_detected")
    return available()
```

Keep physical inventory and its exact binding intact. Return capacity atoms only
for devices that pass this decision. Continue returning the real
`live_claim_ids`; external jobs are not Loom claims and must never appear there.
This prevents the coordinator from subtracting an already reflected Loom claim
twice or treating an external process as something Loom can release.

`ObserveResult` needs a small default-empty status collection with a typed record
such as resource kind, configured capacity key, available flag, reason code and
observation time. Its current consumers need this information, so this addition
has a concrete owner. The same-kind composition code must preserve status for
withdrawn atoms as well as available atoms and enforce one configured owner per
status key. CPU-only and existing synthetic providers can return no statuses.

A sample becoming old immediately excludes its unclaimed GPUs even if the next
query has not completed. A failed refresh invalidates previous positive evidence;
it does not keep using an older idle sample until its age limit. Newly observed
idle GPUs recover on the first successful complete query; a cooldown is not
needed for the accepted behaviour.

Use the provider's existing lock for claim accounting and consistent status
snapshots. Serialize observer refreshes separately; do not run NVIDIA subprocesses
while holding the coordinator scheduling lock or the provider claim lock.
When a query finishes, combine its result with the *current* claims under the
claim lock. A concurrent prepare or release must not be overwritten by an older
copy of the claim map. A forced refresh waits for usable current evidence rather
than falling back to an expired cache.

Advance the provider's existing revision when the effective available set,
reason codes, or held claims change. A timestamp-only refresh does not change
scheduling identity. Preserve a generation/counter so `free -> busy -> free`
does not reuse the earlier revision. Process samples never enter inventory,
configuration or private-binding fingerprints. Authored monitoring settings
belong in the role's existing active-configuration identity.

**5. Recheck during physical admission**

Ordinary `observe()` can use a fresh cached sample. A *new* `prepare()` must force
a query after inputs have been staged and before the claim becomes prepared.
Both local and remote paths already reach the GPU provider here.

```python
def prepare(command):
    replay = existing_exact_claim_result(command)
    if replay is not None:
        return replay

    sample = observer.refresh(force=True)
    with claim_lock:
        # Recheck replay and current claims after waiting for the query.
        decision = check_requested_gpus(command, sample, current_claims())
        if not decision.allowed:
            return ClaimResult(
                ClaimOutcome.DECLINED,
                command.operation_id,
                command.claim.fingerprint,
                decision.reason_code,
            )
        return reserve_with_existing_claim_accounting(command)
```

Replays of prepared or active claims preserve their existing outcome. Otherwise
Loom's own newly started process would cause a replay to reject its valid claim.
Restored claims likewise remain held without requiring idle GPU evidence.

A definite pre-grant refusal aborts other prepared resource claims through
`SQLiteAgentJournal.prepare_composite()` and uses the existing decline path.
The stage remains pending; no execution failure or retry-budget consumption is
introduced. Carry the bounded reason through the decline receipt/operator
projection where the transport currently drops the provider detail. Retain exact
claim and operation identity on replay.

This check belongs at preparation, where refusal is already supported. Do not
add a new `DECLINED` result after a grant or during activation: current activation
callers treat that as indeterminate, and the job already has a fence. The interval
between preparation and process start remains an explicitly documented external
race. Another check at that later point would require a separate post-grant
never-started settlement contract and is not needed for this proposal.

**6. Publish changing availability through the existing offer protocol**

`AgentOffer` already separates full `gpu_devices` from current `gpu_atoms` and
`capacity_atoms`. Keep all configured descriptors and remove only the unavailable
GPU atoms. Add the safe status collection to the offer wire value:

```json
{
  "inventory_revision": "inventory-A",
  "availability_revision": "availability-42",
  "resource_status": [
    {"resource_kind": "gpu", "capacity_key": "gpu-a", "available": false,
     "reason_code": "external_process_detected"},
    {"resource_kind": "gpu", "capacity_key": "gpu-b", "available": true,
     "reason_code": "available"}
  ]
}
```

This abbreviated example omits the existing descriptors, capacity atoms,
timestamps, session fields and claim IDs. `gpu-a` and `gpu-b` are illustrative
safe keys; use Loom's actual configured IDs and existing wire/private mapping.
Host indices 0 and 1 are labels used in this discussion, not new wire bindings.

Changing `observe()` is insufficient. Today the agent constructs a fresh offer
but calls `renew_current_offer()` whenever the session revision is unchanged.
Renewal extends the old offer's expiry. Also, both the agent journal and
coordinator require an offer's revision to equal the session's current revision.

Extend the existing authenticated `publish_offer` operation with an expected
previous availability revision. Under its current scheduling guard and database
transaction, it must:

1. Verify principal, active session, epoch, configuration, inventory, providers,
   safe resource bounds and the expected prior revision.
2. Validate the complete new snapshot, including statuses for configured IDs
   and consistency between positive statuses and available atoms.
3. Mark the previous offer noncurrent, advance the session revision and store
   the new offer atomically. Preserve every existing assignment and claim.
4. Return the new session and offer receipt. Persist the exact request in the
   agent's existing mutation-intent journal before sending it, and apply the
   receipt locally after acknowledgment.

```python
snapshot = provider_snapshot()
if snapshot.decision_content != last_acknowledged.decision_content:
    publish_offer(
        offer=make_offer(snapshot, new_revision()),
        expected_availability_revision=current_session.availability_revision,
        idempotency_key=persisted_operation_id,
    )
else:
    renew_offer_with_fresh_observation(snapshot)
```

The revision and operation ID are allocated once per persisted mutation, not
regenerated during retries. Replay a lost response before issuing a successor
update. Returning an old receipt must not make an older revision current again.
Use one frozen provider snapshot for a report; do not construct an offer from one
query and validate exact equality against a second changing query. A newer local
observation can follow as another update. Admission still performs its own query.

Renewal means scheduling content is unchanged and the agent has rechecked it.
Extend renewal with verification timestamps/status freshness for the exact
current offer; reject a renewal that tries to change available atoms, claims or
reason codes. Store latest verification metadata in the existing renewal receipt
and use it in inspection, rather than rewriting the immutable original offer
body. A changed reason, failed query or newly stale sample uses a replacement
offer. An unchanged unknown state may renew an offer containing zero GPU atoms.

Preserve offer TTL as the coordinator's bound on disconnected reports. The local
sample age limit and the coordinator's report expiry are distinct. UTC sample
times are diagnostic across hosts; local age uses monotonic time and coordinator
expiry uses its accepted-time owner. Five-second polling is a healthy-path target,
not a strict distributed detection deadline: queries and existing HTTP calls can
take time, and connectivity can fail. Never renew a positive GPU report from
locally stale evidence. A disconnected old report can remain visible until its
existing expiry, and physical preparation still protects admission.

**7. Preserve polls and outstanding work when offers change**

Availability updates are scheduling changes, not releases. This is the most
important integration boundary after NVIDIA observation.

Keep the current rule that a report cannot replace an offer during an active
work poll. The single-threaded maintenance path waits for that bounded poll to
return, handles any delivery, then publishes. Do not clear a poll or an uncertain
delivery to make publishing easier.

For already targeted or delivered work, retain the frozen assignment request and
its original revision. A new report never retargets it. While any admission is
still unresolved or its claim is unreflected, the coordinator must withhold new
admission from that agent as required by its existing ownership rules. Enforce
this across revisions: a new report must not bypass the one-unresolved-admission
gate. The current report may still explain which devices are occupied; the
admission gate is separate from those observations. Resume and replay must settle
the old targeted delivery using its recorded identity even after a status update.
In particular, `_take_targeted_delivery()` currently selects by the poll's
availability revision. Add a narrowly scoped reconciliation path for an existing
unresolved delivery in the same authenticated session and epoch: return its exact
stored request and original assignment revision. It must not reserve new work or
make arbitrary old polls valid. Check for and reconcile that retained delivery
before accepting a fresh placement; keep normal new-work polls bound to the
current offer. Cover a publication that wins just after targeting but before the
agent receives its response.

Once accepted claims are reflected, existing accounting permits disjoint capacity
to be reported. Never subtract reflected claims again; never infer release from
missing GPU processes, an expired offer, or a new revision. At completion/decline,
the serialized session writer must use the current acknowledged session and
preserve exact release replay, rather than overwriting a newer observation with a
stale session object captured at job start. Existing release and decline receipts
remain authoritative for the assignment; a fresh observation report follows them.

Test offer publication racing with coordinator reservation under the existing
cycle/scheduling guard. This should be an extension of current locks and journal
semantics, not a second coordination mechanism.

**8. Keep reporting while a job is running**

The inspected standalone service calls `execute_one()`, which waits for the
worker to finish before returning. Merely refreshing at the top of
`run_outbound_agent_service()` could leave GPU 0's status unchanged throughout
a long job on GPU 1.

Use a small private, due-time maintenance callback owned by that service. Call it
between work polls, between input/output chunks, and in the existing supervisor
wait loop. It observes resources and publishes/renews when due. Keep session
mutations serialized in this existing agent thread. Snapshot publication failure
should retain its pending intent and allow supervision/cancellation to continue;
it must not terminate the running job or authorize more GPU work from stale data.
Bound the probe and maintenance network work per call and give cancellation its
existing opportunity before maintenance.

```python
while worker_is_running():
    poll_assignment_control(session_id)
    availability_maintenance.run_if_due()
    receipt = supervisor.query(launch)
    if receipt.is_terminal:
        break
    wait_for_next_supervisor_check()
```

The current work poll is already bounded at five seconds; the HTTP timeout is ten
seconds and offer TTL is thirty seconds. Account for those existing delays in
documentation and fake-clock tests. Do not promise a strict five-second bound or
add an unrelated asynchronous runtime redesign. This plan improves reporting
during a standalone job; it does not claim to make the current synchronous
`execute_one()` loop launch multiple remote jobs concurrently.

For the embedded route, refresh due samples before entering the scheduling part
of the daemon cycle, including cycles with no ready work. In the inspected code,
`reconcile_once()` holds `_cycle_lock` when it calls `begin_cycle()`: run the
bounded query before acquiring that lock, then apply its result against the
still-current provider/configuration when the lock is held. Discard the sample
if a reload replaced that provider meanwhile. `observe()` reads the cache;
`prepare()` still forces fresh observation. The local daemon already manages
worker futures separately. If observation is ever offloaded for responsiveness,
it must use one owned worker and explicit shutdown, with stale samples excluded;
that is implementation discretion, not a requirement for a new service.

**9. Configuration, status and compatibility**

Recommended abbreviated agent configuration:

```yaml
resources:
  cpu_capacity: 16
  memory_capacity_bytes: 68719476736
  gpu:
    provider: nvidia
    devices: "0,1"
    occupancy:
      poll_interval_seconds: 5
      max_observation_age_seconds: 15
      query_timeout_seconds: 2
```

The `occupancy` block is new; the surrounding field names match the actual
loader. Recommend enabling observation by default for the built-in selected
NVIDIA resource path, with these defaults when the block is absent. CPU-only
`devices: "none"` starts no NVIDIA query or maintenance work. Reject nonfinite or
nonpositive timing values and require the configured freshness window to exceed
the intended polling interval plus query timeout.

Pass settings through both `_local_agent_service()` and
`load_outbound_agent_service_config()` to their provider construction owners.
Keep authored monitoring policy in the existing active role configuration; keep
live samples out of it. Normalizing omitted defaults and explicitly written
defaults must yield equal policy identity. Settings changes follow the existing
protected reload/drain rules; occupied GPUs do not make otherwise valid role
configuration fail to load.

Synthetic/explicit non-NVIDIA providers remain constructible without NVIDIA
tools. Custom provider composition must own its occupancy semantics; reject
combining the built-in occupancy configuration with a custom provider factory
that would silently bypass it. Do not infer NVIDIA support from arbitrary safe
IDs or binding strings. Preserve retained claims and binding descriptors during
restart; an observer is an admission policy, not authority to reinterpret them.

Extend `daemon-agent`/`daemon-agents` using `AgentProjection` for remote devices.
The existing `available` boolean describes an active offered agent and must not
be redefined to mean all GPUs are free. Add explicit per-resource fields. The
embedded agent does not have the same remote session row; expose its equivalent
GPU status in the existing `daemon-status` projection rather than fabricating a
remote session. Both projections consume the provider/report status shape.

```text
GPU 0  unavailable  external_process_detected  observed 2 seconds ago
GPU 1  available                              observed 2 seconds ago
```

Label expired reports as stale in inspection and show historical device state
only as last observed. Inspection must not launch GPU subprocesses. Maintain
status in the agent's live provider cache and the existing coordinator offer /
renewal records; there is no separate persistent telemetry history. Document the
distinction between GPU availability, agent/session state, and admission waiting
for a prior reservation.

The inspected protocol version is `10`, and serializers use exact field sets.
Adding status fields and conditional offer publication therefore requires the
next protocol version, updated handshake checks and all affected serializers;
do not assume additive JSON will work with older peers. Update agent and
coordinator together through the existing lifecycle. Old peers must reject the
new protocol clearly before advertising monitored capacity. Existing persisted
offer/renewal records need an explicit decoder/migration rule: absent old status
means unverified legacy evidence, never idle. Preserve historical assignment and
release receipts. Use existing schema/version machinery where required and
cover a supported old-root restart without root deletion or claim loss.

**10. Implementation order and proof**

Use three cohesive implementation slices. Their boundaries are suggestions for
review, not new numbered roadmap commitments. Every slice includes its affected
docs and tests; the behaviour is complete only when all three compose.

| Slice | Deliverable | Why this boundary is useful |
| --- | --- | --- |
| 1. Observe and admit | NVIDIA process parser; observation cache and statuses; GPU provider filtering; forced preparation check; embedded configuration, cycle and status wiring. | Demonstrates the complete behaviour locally, including a real scheduling decision from fake GPU evidence. |
| 2. Report safely | Offer/renewal status and revision protocol, mutation replay, admission fencing across revisions, standalone maintenance, remote status and compatibility. | Keeps the cross-process state transition and its consumer in one reviewable change. |
| 3. Qualify the full journey | Composed local/remote scenarios, deployed configuration examples, upgrade/restart evidence and operator documentation. | Proves the first two slices satisfy the accepted use case together. It is not a docs-only interlude. |

The essential composed scenario is:

```python
probe.set_idle("gpu-a", "gpu-b")
agent.refresh_and_report()
assert coordinator.available_gpus(agent.id) == {"gpu-a", "gpu-b"}

probe.set_processes("gpu-a", [external_process])
agent.refresh_and_report()
assert coordinator.available_gpus(agent.id) == {"gpu-b"}
assert coordinator.gpu_reason(agent.id, "gpu-a") == "external_process_detected"
assert place_one_gpu_job().device_id == "gpu-b"

probe.set_idle("gpu-a")
agent.refresh_and_report()
assert "gpu-a" in coordinator.available_gpus(agent.id)
```

Those helpers are illustrative test-fixture APIs. Implement the assertions
through actual providers, journals, scheduler and transport, not a duplicate
test implementation of the set subtraction.

| Reachable case | Required assertion | Existing test owner to extend |
| --- | --- | --- |
| Valid empty/process XML, compute/graphics/combined types, process with unavailable memory | Correct UUID-scoped blocked set; no utilization threshold or memory-zero shortcut | `tests/unit/loom/queue/gpu/test_nvidia.py` |
| Timeout, denied query, malformed XML, missing selected GPU, unrelated unselected GPU | Affected selected GPUs withheld with reasons; CPU remains usable | NVIDIA unit tests and `test_gpu_resource_provider.py` |
| Two profiles sharing one physical inventory | One observation/claim domain; no duplicated availability | Provider contracts and existing transport inventory tests |
| External job starts after offer but before preparation | Definite decline, no worker launch, other resource claims rolled back, stage still pending | `tests/integration/queue/test_agent_session_transport.py`, managed-local integration |
| Query failure or staleness followed by recovery | Old positive evidence is not renewed; a successful idle query restores capacity | Provider and deployment tests with injected clock/runner |
| Busy/free/busy transitions and successful unchanged refresh | New decision revisions never revive old offers; unchanged verification renews without new scheduling identity | `test_agent_sessions.py` and transport integration |
| Long Loom job on GPU 1 while an external job starts/stops on GPU 0 | Remote coordinator and embedded status change before the Loom job ends | Real service-loop integration with a controlled long-running fixture |
| Offer update races with an active poll, bound delivery, accepted/reflected claim or release | No lost delivery, duplicate reservation, double subtraction, stale session overwrite or premature release | Session, transport and managed-local coordinator contracts |
| Publish response lost, reconnect, replay, retained running job | Exact update replay; last acknowledged session preserved; retained claims remain held | Existing transport restart tests |
| Old wire peer or persisted report and CPU-only config | Clear protocol handling; unverified does not become available; CPU-only imports/commands remain NVIDIA-free | Package, deployment, serializer and lifecycle tests |

Run the smallest relevant test files through Loom's locked development
environment first, then `make validate-pr` and `make test-summary` for implementation
PR evidence. The completed receipts are recorded below. An optional physical smoke can use
two explicitly authorized GPUs and one owned external CUDA process; it must not
interfere with another user's process and is not a substitute for deterministic
race and failure tests.

Completion requires the exact idle -> external use -> alternate placement ->
recovery sequence on both deployment routes, explanation in coordinator-visible
status, a stale-offer decline before launch, reporting during an active job,
preserved retained claims, documented protocol/default changes and qualified
validation evidence. The residual external-start race remains explicit.


**Implementation execution record**

- Status: merged. [PR #283](https://github.com/samcantrill/loom/pull/283) was squash-merged into `develop` as `f870dd8a8f31e0140be8a3046085df6544cabe16` on 2026-09-08. Its tree exactly matches tested commit `029e2315347dffe93d40824c3da0b3ffba9b5152`.
- Scope: all approved behaviour is implemented in one feature PR: selected-UUID observation, shared cache and claim ownership, fresh pre-grant refusal, embedded and standalone maintenance, atomic offer/session updates and exact replay, safe status and durable refusal reasons, configuration, compatibility and composed acceptance evidence.
- Implementation owners: `queue/gpu/occupancy.py`, `_managed_local.py`, deployment, session/transport, daemon scheduling and existing inspection projections. Durable refusal reasons use the existing assignment event journals; state schema 12 and retained claim identities are preserved. Wire protocol is 11.
- Review: one independent review completed. Its missing durable-refusal reason and observer-failure coverage findings were corrected and verified manager-locally. Reload ownership and unsupported XML cases are covered. Three scoped corrections were used, including replacement of an obsolete empty-JSON test offer with a valid serialized offer. No remaining review blocker.
- `make validate-pr`: passed at the tested commit. Full Ruff and Pyright passed; default tests: 2,908 passed; configuration tests: 161 passed, 18 skipped; source distribution and wheel built successfully.
- `make test-summary`: passed. Package 122, unit 2,060, contract 300, integration 358, end-to-end 68 and configuration 161 passed; total 3,069 passed, zero failures/errors, 18 container-runtime tests skipped. The report and command logs are retained under `build/external-gpu-availability/` in the control checkout.
- Acceptance: both deployment routes cover idle -> external use -> alternate placement -> recovery using real workers and injected NVIDIA observations. Tests cover stale-offer refusal before launch, reporting during a worker, failed and stale queries, rollback, lost-response/reopen replay, retained claims, reload ownership and durable refusal inspection. Refusal leaves the stage pending without consuming an execution retry.
- Qualification: no physical GPU smoke test was run. The external-start race after the final observation remains an explicit cooperative-admission limit. Upgrade the coordinator and agents together for protocol 11.
- Delivery and cleanup: control `develop` was fast-forwarded to the verified merge; the original planning document was preserved. The feature worktree and local/remote feature branches were removed. Unrelated worktrees and changes were preserved.
