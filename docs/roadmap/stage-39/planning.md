# Roadmap Stage 39 Planning: Independent Resource Accounting And Enforcement

Status: evidence-backed draft; detailed design and independent review pending
Roadmap stage: 39
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-39-resource-policy-plan`
at `0e14d503cc2932207aece0765cb2da111cf2154b`, branch
`agent/stage-39-resource-policy-plan`; relevant dirty paths before drafting: none.
Planning route: expanded, because this changes runtime options, persisted
placement/recovery meaning and cross-backend resource controls.
Current gate: functionality accepted; source reconciliation and minimum design
Blockers: new-job enforcement default requested from the maintainer; exact design/readiness not yet claimed

## Current State

The maintainer's 2026-09-08 implementation request includes generic separation
of resource demand, scheduling accounting and enforcement. This is separate from
rphys Stage 81's causal diagnostics and Stage 85's deployment ownership. Existing
Stage 38 delivery and the original dirty Loom checkout remain preserved.
This work is not a prerequisite for the managed CPU diagnostic proof. A physical
experiment can depend on it only through an explicit published prerequisite.

| Gate | Locked result | Remaining work |
| --- | --- | --- |
| Functionality | Independent accounting/enforcement; explicit none; truthful delegation; preserve lifecycle ownership | Resolve concrete current runtime/placement/adapter propagation |
| Minimum design | Reuse existing demand, claims, capabilities, timeout and backend mappers; composition/timeout owners resolved below | Confirm the new-job default, finalize public shape and retained-run migration |
| Validation / phase shaping | Distinguish selections through real admission/command boundaries | Complete finite supported matrix and independently reviewable phase cards |
| Quality / implementation | Not ready; no runtime edits | Expanded design/plan review, then normal Loom phase workflow |

## Evidence And Scope

| Existing owner | Current behavior | Consequence for this work |
| --- | --- | --- |
| `pipeline/resources.py::ResourceRequest`, `ResourceEntry` | Schema-2 entries hold kind, amount, unit and attributes | One authoritative demand representation; do not create CPU/RAM/GPU amount copies in each policy |
| `pipeline/runtime/options.py::RunOptions`, `StageRuntimeOptions` | Resource, execution, environment, reliability and adapter options compose into exact runtime choices | Add generic policy through these existing composition/serialization owners |
| `queue/local_daemon_runtime.py::_runtime_payload` | Every runtime resource kind currently needs a configured planner; authored/runtime resources resolve into persisted placements | Account only selected demand kinds without dropping unselected original intent |
| `queue/local_daemon_runtime.py::_stage_placement_policy` | Current default resource demand includes one CPU | Explicit empty/GPU-only accounting must not accidentally reintroduce CPU claims through this default |
| `pipeline/runtime/placement.py::ResolvedStagePlacement` | Immutable schema-2 placement and fingerprint feed admission, recovery and SLURM mapping | Policy must survive this boundary and replay comparison; command generation cannot reconstruct a different selection |
| `pipeline/runtime/placement.py::resolve_stage_placement` and `ResolvedStagePlacement.from_dict` | Planners own authored/default/runtime demand resolution; decoding currently reconstructs scheduling requests for every resource entry | Apply accounting selection after semantic demand resolution; persist the selection so decoding cannot recreate excluded claims |
| `pipeline/execution/runner.py::_acquire_stage_resource_admission`, `resource_admission.py::resource_requests_from_runtime` | The serial runner separately turns all runtime entries into integer authority leases | Apply the same resolved accounting selection here; managed-daemon placement is not the only admission owner |
| `queue/local_daemon_runtime.py` schema-2 prepared payload | Exact runtime/placement payload participates in replay comparison | A policy change needs an explicit retained-payload version/read/upgrade rule, not only new Python defaults |
| `pipeline/runtime/capabilities.py::ResourceCapability`, `ResourceEnforcementExpectation` | Metadata already distinguishes enforced, best-effort, not-enforced and not-applicable | Extend truthful reporting at its current owner; static capability is not measured host enforcement |
| `pipeline/executors/apptainer/commands.py::_append_resource_limits` | `cpu_memory_enforcement=runtime/scheduling_only` selects CPU/RAM flags from mapped container resource intent | Replace the adapter-specific switch after generic policy and consumers exist |
| `pipeline/executors/_reliability.py`, reliability policy | One existing timeout policy and metadata path | Do not introduce a second deadline model merely to nest timeout under a new config key |
| `pipeline/executors/slurm/resources.py::map_slurm_resources` | Maps request entries into SBATCH directives | Scheduler request and inner process enforcement are different owners |
| `pipeline/executors/slurm/ready_stage.py::map_ready_stage` | Maps the persisted placement request and rejects unmappable hard requirements | Preserve hard semantics, profile identity and request digest on delegated execution |
| `pipeline/executors/slurm/planning.py` | Whole-run/stage job planning also maps resource directives | Do not update only ready-stage delegation while silently changing other supported routes |
| `queue/_managed_local.py::_worker_environment`, local resident launch and `agent_session_transport.py` remote launch | Active claim providers always contribute launch environment; the GPU provider contributes `CUDA_VISIBLE_DEVICES` | Select additional job binding independently of claim activation and pass the admitted policy to both local and remote launch owners |

Current consumers are native managed agents, direct container executors,
protected SLURM ready-stage and existing SLURM planning, their dry-run/preflight
views, resume/recovery readers and maintained configurations/tests. Agent offered
capacity stays with the deployed provider/role and is not rewritten by a job.

Non-goals: new schedulers/providers, distributed/gang execution, hardware
discovery, hostile-code isolation, live migration, modifying host cgroup/D-Bus
settings, scientific changes, or Stage 85 role-schema implementation. No real
SLURM/GPU result is inferred from command construction or capability metadata.

## Minimum Useful Change

Declare each demand once. Resolve two independent selections against it:

1. Demand kinds used by Loom when admitting work against capacity.
2. Controls requested for execution, with their actual enforcing owner recorded.

The same job may account for GPU only while applying GPU binding and a timeout,
CPU/RAM controls, or no additional controls. It must remain inspectable which
demands were not accounted or enforced. Removing all resource declarations to
avoid unavailable cgroups is not equivalent: that loses useful scheduling intent.

Reuse current resource and timeout models. A new policy is justified because
the existing adapter-specific CPU/RAM switch cannot express independent GPU,
CPU/RAM and timeout behavior across backends. No global registry, second resource
schema, alternate scheduling engine or new lifecycle store is required.

## Functional Requirements

| ID | Behavior | Boundary / validation |
| --- | --- | --- |
| FR-39-01 | Offered capacity, job demand, accounting and enforcement remain separate; effective demand amounts have one authority | Config composition, placement and replay preserve all four meanings |
| FR-39-02 | Accounting can select GPU only, another supported subset, all demands or none without imposing limits | Actual admission/claim tests; excluded CPU/RAM demand does not block GPU-only work |
| FR-39-03 | Enforcement selection is independent, including explicit none; unmapped/absent demand creates no invented limit | Resolved runtime to actual argv/environment/deadline tests |
| FR-39-04 | Explicit requested unsupported enforcement fails with actionable explanation; no silent downgrade | Capability/preflight/executor failure cases |
| FR-39-05 | No-enforcement preserves cancellation, assignment ownership, deadlines needed for control-plane protocols and process cleanup; it disables only selected job limits | Existing containment/lifecycle tests plus explicit no-job-timeout case |
| FR-39-06 | SLURM requests/delegation are distinct from inner limits; no duplicated container cgroups | SBATCH and nested launch assertions for supported SLURM routes |
| FR-39-07 | Metadata reports demand, accounting, requested/delegated/applied/unavailable controls and actual mechanism without overstating guarantees | Public inspection/preflight and runtime metadata tests |
| FR-39-08 | Existing composed/persisted options and retained work have an explicit migration/recovery rule; old adapter switch is retired only with migrated consumers | Codec, profile, restart/replay and maintained example tests |

## Functionality Agreement

The attachment explicitly authorizes FR-39-01..08's behavior. GPU accounting is
reservation bookkeeping, not VRAM or compute isolation. GPU binding controls
visibility/selection, not a security boundary. Excluding CPU/RAM from accounting
allows oversubscription; this is deliberate and must be reported honestly.

Unmapped demand imposes no extra restriction. Selecting no additional enforcement
cannot remove inherited host or scheduler constraints. Actual control support is
backend-specific and must not be guessed from a generic resource label.

## Behavior Baseline And Design Questions

The following are named source-reconciliation tasks, not delegated product choices:

- Finalize the smallest typed policy placement in current runtime options,
  including per-stage overrides, exact collection/absent semantics and defaults.
  Do not conflate an omitted override with an explicit empty selection.
- Preserve all effective demand for provenance while deriving accounting claims
  from the selected subset. Account for the existing default-CPU path and current
  unsupported-planner check. A selection without a demand must not invent one.
  A resource planner also owns semantic refinement/unit rules: excluding a kind
  from capacity accounting does not justify bypassing its demand-resolution
  invariant. Separate semantic normalization from availability/claim validation.
  The current decoder rebuilding all `scheduling_requests` is a required negative
  regression: a GPU-only prepared placement must remain GPU-only after decode.
- Trace the policy through exact resolved runtime, persisted placement,
  assignment launch, preparation/replay and adapter command generation. Runtime
  receipt metadata must distinguish selected intent from applied control.
- Keep job timeout in the existing reliability owner, with one declared amount
  and explicit enable/disable behavior. Control-plane/cleanup timeouts are not job
  resource limits and stay active.
- Distinguish SLURM allocation requests from additional controls inside the
  allocation. An SBATCH allocation may result in scheduler-imposed constraints;
  no-enforcement must not promise an unconstrained allocation. Map every explicit
  hard request or reject it before submission, preserving current profile/digest
  authority and no silent dropped semantics.
- Decide the narrow supported old-runtime/placement read and retained-run
  migration from actual producers; do not create a generic compatibility engine.
  Source-shaped default behavior alone must not silently change retained claims
  or launch controls on restart.

The syntax in the user attachment is illustrative. Final public shape, default
behavior and durable migration must be fully specified and independently reviewed
before writing runtime code. A new amount field for the same demand is not an
acceptable solution to an adapter handoff gap.

### Current-Owner Design Resolution

The replacement continuation attachment confirms this workstream, including
design, review, implementation and normal PR/merge delivery. It does not turn
this draft into an implementation-ready packet or authorize physical execution.

Source reconciliation at the recorded Loom base establishes these owners:

- `runtime/options.py` owns `RunOptions` and `StageRuntimeOptions`; their strict
  field sets, constructors, `to_dict`/`from_dict` and metadata are the invocation
  boundary. Introduce typed resource policy there, not in the open-ended
  `ExecutionOptions.settings` bag or the separate pipeline `RuntimeRequest`.
- `runtime/profiles.py` owns source normalization and run/stage override merging.
  It has separate allowed-field sets and merge paths; adding a constructor field
  alone would lose policy from composed profiles. An omitted stage selection
  inherits, whereas an explicit empty selection clears that axis. Do not merge
  selection lists by union or conflate an empty list with no override.
- `runtime/metadata.py::resolve_run_runtime` is the resolved per-stage handoff.
  Thread the effective policy through this owner before preparation or executor
  mapping, so persisted intent and the selected launch use the same choice.
- `reliability/_models.py::TimeoutPolicy` already owns `enabled` and
  `duration_seconds`; enabled requires a positive duration. `ReliabilityPolicy`
  defaults to no timeout, and its merge replaces an explicitly supplied timeout
  object while inheriting an omitted one. Keep this existing schema and use
  `reliability.timeout: {enabled: false}` to disable an inherited job timeout.
  Do not add `timeout_seconds`, a second duration or a resource-policy timer.
- `ResolvedStagePlacement` currently requires the resource, scheduling-request,
  validator and planner key sets to match. Its schema and fingerprint need an
  explicit accounting selection: retain full normalized demand and its semantic
  identities while allowing scheduling requests to be the selected subset.
  The decoder must reconstruct exactly that subset, not all declared demands.
- `_runtime_payload` persists both normalized invocation and placements and
  reuses their exact content for replay. Any introduced policy default or
  schema upgrade must be resolved before this payload is admitted; a restart
  must not re-resolve an old job using a changed implicit policy.

Focused coverage follows the existing runtime-options/profile integration,
reliability model and managed placement/preparation/recovery owners. A combined
profile test must prove independent per-stage clearing and inheritance. A
prepared-placement round trip must prove full demand remains inspectable while
CPU/RAM claims stay absent for GPU-only accounting. Existing timeout tests own
duration validity; resource tests need only prove the selected timeout reaches
that owner without disturbing cancellation and cleanup.

The proposed public vocabulary below resolves the invocation shape for design
review. New-job defaults, the narrow old-runtime/placement admission rule, raw
whole-run local queue disposition and complete executor/control receipts remain
unfinished. No phase cards or runtime changes are admitted yet.

### Proposed Configurable Policy Shape

Add one import-light `ResourcePolicy` value at the existing runtime-options owner,
exposed through `RunOptions.resource_policy` and
`StageRuntimeOptions.resource_policy`. It selects resource kinds, not amounts or
backend commands. Proposed authored form:

```yaml
runtime:
  resource_policy:
    account_for: [gpu]
    enforce: []
  reliability:
    timeout:
      enabled: false
  stage_options:
    fit:
      resource_policy:
        enforce: [gpu]
      reliability:
        timeout:
          enabled: true
          duration_seconds: 600
```

Stage resource declarations and their runtime refinements continue to use the
existing `ResourceRequest` entries. In this example, all stages account only
for their effective GPU demand; only `fit` requests extra GPU binding and a
ten-minute job timeout. No amount is repeated in `resource_policy`. The spelling
is a design proposal, not a currently accepted executable Loom configuration.

Each selection accepts `all` or an explicit list of resource-kind identifiers.
An empty list selects none. An omitted axis inherits the earlier profile/run
choice independently; a supplied axis replaces that axis without list union.
An empty policy mapping changes neither axis. Authored `null` is not a second
spelling for explicit none. The immutable Python representation preserves missing
axes until composition finishes; its exact private representation is discretionary.
Resolve the approved new-job defaults only after composition, then record concrete
effective choices before admission. The pending default decision below still
applies; this proposal does not silently decide it.

Resolve selections against the full normalized demand after existing semantic
refinement. `all` means all effective demand kinds for that stage, not a fabricated
host capacity. A selected kind with no effective demand produces no claim, limit
or visibility mask and is reported as not applicable. An explicitly requested
control for a present demand must be supported and actually applicable at its
backend, or fail with the requested kind, relevant mechanism/prerequisite and
correction guidance. No additional mechanism registry is proposed: use the
existing capability descriptors and concrete backend mapping owners.

`enforce: []` disables additional resource controls only; timeout remains its
existing reliability option. To disable every job limit, set both `enforce: []`
and `reliability.timeout.enabled: false`. Cancellation, leases, supervision and
cleanup timeouts remain active. SLURM allocation directives continue to derive
from full effective allocation demand, independent of which kinds Loom itself
accounts for; no extra inner controls does not remove scheduler constraints.

The default policy can therefore express GPU-only accounting with GPU binding,
CPU/RAM controls, timeout, combinations of those, or none, without backend-specific
mode names or duplicated amounts. Existing codec/profile and command-boundary
tests own selection shape, independent inheritance/clearing, absent-demand
behavior and correct controls. Add no selector grammar, priorities, policy
plugins or per-control amounts for hypothetical future consumers.

### Default Decision And Backend Boundary Evidence

One material default question is with the maintainer: should new jobs account
for all declared resources but apply no additional resource enforcement unless
explicitly selected, or retain each backend's current enforcement defaults?
The recommendation is the former, with unchanged explicit timeout ownership.
It makes enforcement deliberate and avoids requiring unavailable host cgroups
merely because useful demand was declared. The tradeoff is an intentional
change from direct container CPU/RAM defaults; neither retained jobs nor old
authored configuration may silently acquire this new meaning. Finalize the
version/admission rule together with the answer, not independently. This question
does not block the independent rphys diagnostic phases.

The source distinguishes the following backend behaviors that the design must
preserve or deliberately migrate, rather than treating one capability label as
evidence of actual isolation:

| Current owner | Observed behavior | Required policy consequence |
| --- | --- | --- |
| `runtime/capabilities.py` built-in descriptors | Local execution reports CPU/RAM/GPU not enforced; direct Apptainer CPU/RAM/GPU are best-effort; Docker CPU/RAM are mapped but GPU unsupported; SLURM currently labels directive mapping enforced | Explicit controls must be checked against their real owner; disabled/unselected controls cannot trigger unsupported-enforcement errors; scheduler mapping is delegated intent, not observed host enforcement |
| `executors/apptainer/commands.py::_append_resource_limits` | Direct CPU/RAM entries produce cgroup flags unless the adapter-specific scheduling-only switch is set | Select the generic control subset before command construction and migrate the old switch atomically with callers; preserve the full demand in provenance |
| `executors/docker/commands.py::_resource_flags` | Iterates all container intent entries and rejects unsupported GPU mapping | Accounting-only GPU demand must not become a Docker enforcement request; explicit Docker GPU enforcement remains an actionable unsupported-control failure, not newly implemented GPU support |
| `executors/gpu_visibility.py`, Apptainer executor | Bare GPU demand currently enables NVIDIA passthrough and validates/forwards allocation-visible tokens | Distinguish driver/device access from additional visibility restriction. Do not invent tokens or a host-device selection when no authoritative binding exists; explicit binding needs existing allocation/host evidence or a clear unsupported/unavailable result |
| SLURM `container.py` and `rendering.py::_gpu_allocation_lines` | Removes direct CPU/RAM limits and forwards allocation visibility into a clean-environment container | Preserve inherited allocation constraints and access while avoiding duplicate Loom limits. No-enforcement cannot erase scheduler-provided visibility or promise access outside the allocation |

The existing GPU projection accepts an attribute-free count, not arbitrary GPU
share/VRAM semantics. A generic resource label must not widen that implementation
silently. Current supported demand normalization remains owned by resource
validators/planners; control capability is checked separately. Keep GPU-only
accounting, GPU binding and driver passthrough distinct in examples and tests.

### Admission And Managed Binding Coverage

The serial pipeline runner has its own authority-lease admission in addition to
managed placement. It consumes `ResolvedStageRuntimeOptions`, already available
to each `StageExecutionRequest`. Derive its requests from the selected accounting
subset before applying that admission owner's integer-lease constraint; excluded
demands retain their semantic validation and provenance but must not create
leases or fail an irrelevant lease-amount check. Do not reinterpret lack of a
configured coordination store as verified capacity accounting.

Managed local and remote execution currently activate all admitted claims, then
build the worker environment by calling each provider's `worker_environment`.
The GPU provider derives visibility from the active claim. Preserve claim
activation, renewal, fencing and release even when binding is not selected.
Filter only the additional launch controls; do not remove claims or deactivate
their lifecycle to suppress `CUDA_VISIBLE_DEVICES`. The admitted choice must
reach both launch paths and their retained launch comparison so reconnect does
not reconstruct different controls. Deployment-owned base environment and
inherited scheduler constraints remain their existing owners' responsibility.

No new remote policy envelope is needed: `StageWorkerRequest.resolved_runtime`
already crosses `_remote_stage_execution.py::from_worker_request` into the
resident request, and `_ResidentAssignmentWorkspace.worker_request` reconstructs
it unchanged. Local and remote parent launch owners can consume this admitted
mapping before launching the child. Keep the policy at that existing runtime
owner, not duplicated in claim provider data or a new assignment field. Test its
round trip and retained launch comparison together with the actual environment.

The older whole-run queue is a separate boundary requiring a final disposition:
`QueueItem.launch_contract` supplies opaque command/environment snapshots and
integer resource demands; `queue/local.py::_merge_assignment_environment`
merges assignment bindings without reading pipeline runtime policy. Its only
production constructor is `QueueService._admit`, fed by `QueueEnqueueRequest`.
The maintained service-less SLURM example passes a previously prepared scheduler
launch snapshot, so policy must already be reflected in the upstream SLURM
planning/script owner; queue dispatch must not reinterpret it. The many-run
admission example does not supply a resource-enforcement choice. The feature
specifications explicitly distinguish this whole-run API from the dependency-ready
managed-stage route. Finish the raw local launch-contract disposition without
claiming that a RunOptions field reaches arbitrary opaque commands, silently
rewriting saved queue items, or introducing a second demand schema.

Resource-provider GPU/readiness probes also call the environment helpers, but
are explicit probe operations rather than configured experiment jobs. Keep their
current binding evidence and Stage 85 readiness ownership; an experiment's
no-enforcement choice must not weaken the probe's existing contract.

Coverage must distinguish actual serial lease selection, local managed launch
environment, remote-agent launch environment and retained-launch reconstruction.
Use existing resource-admission, managed-resources, local-daemon-production and
agent-session-transport tests. Assert that a no-binding job still owns and
releases its GPU reservation, and that a selected binding uses authoritative
tokens without inventing devices. These are distinct supported routes, not a
backend-by-policy Cartesian matrix.

## Complexity Delta

| Addition | Current necessity | Simpler alternative / disposition |
| --- | --- | --- |
| Independent accounting/enforcement policy | Current GPU scheduling with unavailable local cgroups | Required; existing CPU/RAM-only switch cannot represent it |
| Policy in existing runtime/placement representations | Preparation, restart and execution must agree | Required at current durable boundary; no new policy store |
| Mechanism/delegation metadata | Existing capability labels can overstate what actually happened | Extend current metadata; no separate audit database |
| Additional scheduler/provider framework | No current need | Defer |
| Second timeout schema | Existing reliability owner already serves all consumers | Reject duplication |

## Examples And Validation

| Case | Discriminating behavior |
| --- | --- |
| GPU-only accounting; CPU/RAM demand also present | GPU admission works without consuming/checking CPU/RAM capacity; original demand remains inspectable |
| Accounting includes CPU/RAM, enforcement none | Capacity admission still applies; direct container launch adds no CPU/RAM limit flags |
| GPU accounting, CPU enforcement and enabled timeout | Each axis reaches its own real owner; GPU binding is not added merely because GPU was accounted |
| Explicit empty accounting | Existing default CPU does not reappear as a hidden claim; supported no-resource lifecycle remains owned |
| Enforcement selection with no corresponding demand | No fabricated amount, limit, mask or deadline |
| Unsupported explicitly requested mechanism | Clear failure with requested control, backend limitation and correction guidance |
| SLURM allocation and inner container | Correct SBATCH request; no duplicate inner cgroups; delegated/inherited constraints reported accurately |
| Retry/restart of retained prepared work | Selected policy and ownership remain identical or migration fails explicitly before effects |
| No job enforcement with cancellation/cleanup | Owned children terminate and reservations release under existing lifecycle rules |

Use existing runtime-options/profiles/capabilities, placement/managed-runtime,
daemon admission/recovery, Apptainer/Singularity command/executor, reliability and
SLURM planning/ready-stage tests. Combined cases are required only where policy
axes meet at admission or launch. A fixture for a real supported no-cgroup
container smoke may prove launch and timeout behavior; it does not prove hard
CPU/RAM enforcement on the host. Live SLURM and hard GPU isolation are not claimed.

## Phase Shaping And Quality Gate

Do not create execution cards before the named minimum-design tasks are resolved.
Likely merge boundaries are a complete managed accounting/config/replay change,
then generic executor controls and adapter migration, with SLURM delegation
kept separate only if each prior state remains supported. No preferred phase
count overrides atomic durable migration or a usable current consumer.

Required local gates for each implemented Loom phase remain `make validate-pr`
and `make test-summary`; independent correctness review is required for these
public/durable/runtime changes. Hosted CI remains disabled. Normal Loom isolated
phase branches/PRs target develop, with verified merge and exact cleanup.

Current quality gate: draft, not implementation-ready. No runtime tests or
resource guarantees are claimed. Next action is concrete current-owner design,
then the expanded independent design/plan review and approved phase packet.
