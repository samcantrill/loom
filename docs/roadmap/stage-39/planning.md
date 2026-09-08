# Roadmap Stage 39 Planning: Independent Resource Accounting And Enforcement

Status: evidence-backed draft; detailed design and independent review pending
Roadmap stage: 39
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-39-resource-policy-plan`
at published source `cf9e2850476e4526c4884e34412c26e38de08b6e`, branch
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
| Minimum design | Reuse existing demand, claims, capabilities, timeout and backend mappers; composition/timeout owners and retained-work boundaries traced below | Confirm the new-job default and finalize the proposed hard cut, raw-queue disposition and control receipts |
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

### Retained Work Boundary — Proposed Hard Cut

Current executable readers already reject unsupported versions instead of
migrating retained work. `RunOptions.from_dict` accepts only its current explicit
schema (an omitted version means fresh authored input); `ResolvedStagePlacement`
checks its current version and content fingerprint. The exact managed runtime
reader requires its closed field set, version, digest and plan identity.
`managed_local_preparation._replay_receipt` preserves a failed replay's cause and
does not rewrite an existing run to make it executable. The queue feature spec
also documents hard cuts for its existing persisted formats. Reuse this design,
not a new compatibility engine.

Recommended version boundary, still subject to the expanded design review:

| Existing executable owner | Proposed change | Old-data behavior |
| --- | --- | --- |
| `RunOptions` schema 1 | Schema 2 includes independently composed resource policy | Explicit version 1 is rejected with migration guidance; no silent change to serialized invocation meaning |
| `ResolvedStagePlacement` schema 2 | Schema 3 retains full semantic demand and explicitly selected accounting kinds in its fingerprint | Reject schema 2; do not rebuild all claims from the full demand |
| Exact managed runtime record schema 2 | Schema 3 embeds the new invocation and placements with concrete effective selections | Reject schema 2 before admission; never rewrite the saved record during replay |
| `StageWorkerRequest` schema 1 | Schema 2 requires the resolved policy in its existing `resolved_runtime` mapping | Reject old prepared requests before launch instead of substituting new defaults |
| Resident assignment bundle schema 3 | Schema 4 carries and validates that same resolved runtime | Reject old retained bundles; local/remote launch cannot reinterpret omitted policy |

The worker and resident boundaries are material, not additional copies of the
policy. Current `StageWorkerRequest.__post_init__` only checks the nested runtime's
stage identity and executor, while the resident bundle checks stage identity and
plain data. Both can currently retain policy-free mappings. Updating only the
top-level managed record would therefore leave direct prepared-worker and remote
replay paths without the same executable-version decision. Use one runtime-owned
policy decoder at these actual process/serialization boundaries; do not add a
parallel remote policy envelope or infer choices from claim-provider data.

New, unversioned authored configurations continue to compose under the new-job
default once the maintainer chooses it. They are new invocations, not retained
execution records. Migration documentation must show explicit selections for
users who want to preserve an earlier backend's controls; maintained examples
must declare their intended choice. Existing explicit adapter-specific controls
cannot be silently ignored or translated by guessing: their removal ships with
the accepted replacement and current consumer migration.

The operational guidance for incompatible prepared work is to preserve its
artifacts, use the compatible pinned Loom environment to finish or explicitly
cancel live work, and prepare a new run identity with the new policy. Do not
instruct users to delete a record, edit its version, or reprepare over a live run.
This is not live upgrade or cross-version adoption. Ordinary result inspection
and scientific artifact schemas are not cut merely because execution policy
changes; existing lifecycle ownership must remain intact when a new reader
refuses an old executable record.

Required oracles: serialize/decode selected policy without reintroducing CPU
claims; exact replay preserves bytes and file timestamps; a changed selection
conflicts; previous supported writer versions fail before claim/launch effects
and preserve saved state. Extend the existing runtime-options, placement,
`test_managed_local_preparation`, local-daemon-production and resident transport
owners. Keep the preserved cause plus actionable next step at the reader error
boundary. Version constants above are based on the recorded source revision;
reconcile then-current owners before implementation, without rewriting unrelated
formats. This proposed boundary does not settle the pending new-job default or
the separate legacy opaque `LaunchContract` disposition.

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

### Control Evidence At Its Actual Owner

`runtime/capabilities.py::_resource_capability_diagnostics` currently derives
diagnostics from all declared stage demands and special-cases the Apptainer
CPU/RAM switch. Merely filtering container argv is insufficient: this earlier
boundary could still reject an unselected Docker GPU control, or claim that
declared resources are enforced when no control was requested. Replace the
special case with the same resolved selection used at launch. Keep resource
semantic validity separate from enforcement availability, including custom
registered resource kinds whose control is not selected.

Use existing capability diagnostics for preflight and existing executor/attempt
metadata for execution facts, rather than adding a resource-control state store.
The design must distinguish these meanings at the current consumers:

| Evidence | Authoritative point | Meaning and limit |
| --- | --- | --- |
| Demand and accounting selection | Resolved runtime/placement | Requested amount remains at its existing owner; selecting accounting alone proves neither admission nor isolation |
| Reservation | Existing admitted claim/lease | The selected capacity is reserved; no environment binding or measured GPU isolation follows from this fact |
| Requested control | Capability/preflight and prepared command | The selected mechanism can be attempted; constructing argv is not execution evidence |
| Applied launch configuration | Actual local/remote/container launch owner | The selected argument or binding was supplied for the launched process; this does not establish measured kernel enforcement |
| Delegated control | SLURM mapping and existing submission receipt | Directives request constraints from SLURM; successful submission is not proof of site enforcement |
| Not requested / not applicable | Resolved policy and full effective demand | An excluded control adds nothing; a selected kind without demand invents no amount, mask or limit |
| Unavailable / failed application | Existing preflight or executor failure | Explain the requested kind, mechanism and prerequisite; preserve the underlying failure and do not continue as if enforcement succeeded |

The existing Apptainer and Docker `_setup_metadata`/`_process_metadata` owners
already distinguish setup failure, command construction and process outcome.
Extend their metadata at those boundaries; do not mark a failed container setup
as applied simply because its command contained resource flags. Existing timeout
metadata remains authoritative for deadlines. Keep current redaction of raw GPU
allocation tokens; diagnostic message approval is not permission to copy tokens,
credentials or complete environments into resource receipts.

Required comparisons use the existing capability contract/integration tests and
container executor tests: an unselected unsupported control is not an error;
selecting it produces an actionable failure; a preflight or failed launch does
not claim applied enforcement; a successful fake launcher proves supplied argv
and environment only. Actual host-limit guarantees require separate physical
evidence and are not a condition for the managed CPU diagnostic proof. Exact
metadata keys and any necessary existing-owner codec changes remain part of the
expanded design review, not an additional policy or lifecycle API.

The public `build_apptainer_exec_command` and `build_docker_run_command` functions
also serve callers without a pipeline executor. They currently accept container
intent and adapter options, not `RunOptions`; a policy stored only on the executor
would leave these maintained APIs using the old implicit controls. Pass the
effective policy explicitly through the existing builder boundary and consume
only its enforcement selection there. Builders cannot claim to perform capacity
accounting. Use the same policy value/decoder, not a second adapter-specific mode
or resource-amount representation. Direct callers must have a documented default
and migration matching the approved new-job decision.

Migrate both executor call sites, SLURM's inner-container call and the Apptainer
preflight projection at `diagnostics/preflight.py` together with the builder
change. Preflight currently calls the public builder and extracts CPU/RAM flags;
it must not report old implicit limits after the execution path stops adding them.
The executor's existing `_with_runtime_resources` selects runtime demand when
present and otherwise uses container intent. Preserve that authoritative
precedence while resolving policy against the effective demand once; do not
filter away full demand before preserving provenance, or reintroduce the
fallback after an explicit empty enforcement selection. Existing command contract,
executor and preflight tests must assert matching selections and flags. These
are current supported consumers, not additional backend capability.

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

There is a concrete attribution gap, not just a missing runtime argument:
`LaunchContract.resources` and `ResourceAssignmentRequest.resources` use arbitrary
logical pool keys, whereas the proposed runtime selection names semantic resource
kinds. `StaticSlotAssignmentProvider.acquire` knows each slot's resource name,
but flattens selected bindings into `LaunchEnvironmentBindings.environment` before
returning them. The local adapter therefore cannot safely infer which resource
produced a variable. Neither parsing names such as `CUDA_VISIBLE_DEVICES` nor
reading the provider's display-only `safe_evidence` is an authoritative mapping.

The raw-queue disposition must explicitly choose its supported policy boundary
before implementation: either a reviewed typed attribution/selection extension
at those existing owners, or an explicitly documented legacy boundary with a
clear policy-aware replacement route. Do not silently claim coverage or silently
drop this route from the accepted work. Any proposed extension must preserve
arbitrary logical resources, assignment leases/renewal/release and enqueue replay;
it must not reinterpret immutable opaque argv. The existing assignment and local
adapter tests must distinguish retaining a reservation from adding its binding.
This unresolved scope/compatibility disposition remains visible for design
agreement; no queue-format cut is authorized merely by the pipeline hard-cut
proposal above.

Resource-provider GPU/readiness probes also call the environment helpers, but
are explicit probe operations rather than configured experiment jobs. Keep their
current binding evidence and Stage 85 readiness ownership; an experiment's
no-enforcement choice must not weaken the probe's existing contract.

Source reconciliation includes published Loom PR #286 (`cf9e285`), merged into
this draft without conflicts. Its lifecycle changes do not alter demand,
runtime policy, placement, container limits or `_worker_environment`, but do
change remote application suspension, cancellation and terminal settlement.
Preserve these current contracts when adding policy at launch: stopping the
agent application suspends observation rather than cancelling supervised jobs;
claims and fences survive reconnect; missing worker results are settled only
with continuous containment evidence; cancellation and provider release remain
durable ordered operations. No-enforcement must not disable any of these owners.
The existing lifecycle tests are regression obligations in the final full Loom
gate, not evidence of resource enforcement or authorization for physical work.

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
