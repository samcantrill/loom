# Roadmap Stage 39 Planning: Independent Resource Accounting And Enforcement

Status: complete plan approved; implementation tracked by the manifest and phase cards
Roadmap stage: 39
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-39-resource-policy-plan`
at published source `719e016c6fe5e1ec3e70994bca6b3716964fc200`, branch
`agent/stage-39-resource-policy-plan`; relevant dirty paths before drafting: none.
Planning route: expanded, because this changes runtime options, persisted
placement/recovery meaning and cross-backend resource controls.
Current gate: functionality/default and complete migration/phase packet approved after independent review
Blockers: none at planning exit

## Current State

The maintainer's 2026-09-08 implementation request includes generic separation
of resource demand, scheduling accounting and enforcement. This is separate from
rphys Stage 81's causal diagnostics and Stage 85's deployment ownership. Existing
Stage 38 delivery and the original dirty Loom checkout remain preserved.
This work is not a prerequisite for the managed CPU diagnostic proof, now merged
in rphys PR #597 (`410b1eb3`). A physical experiment can depend on it only through
an explicit published prerequisite; that proof grants no physical authority.

| Gate | Locked result | Remaining work |
| --- | --- | --- |
| Functionality | Independent accounting/enforcement; explicit none; truthful delegation; preserve lifecycle ownership | Approved; no unanswered default |
| Minimum design | Existing demand/claims/timeout/mappers; typed queue extension, exact compatibility boundaries and bounded receipts; EDR-39-01/02 confirmed | Approved |
| Validation / phase shaping | Causal admission/command/replay comparisons; two vertical phase cards; plan review passed after bounded SLURM delivery correction | Approved |
| Quality / implementation | Design and plan review passed; concrete plan approved | Normal Loom phase workflow; current state in manifest |

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

The maintainer explicitly approved the outstanding default question: new jobs
account for all declared resources and apply no additional resource enforcement
unless configured. Job timeout remains separately configurable through existing
reliability policy. This approval resolves the default, not permission to modify
host settings, erase retained work, or execute a protected physical/GPU smoke.

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

The sections below supply the candidate design for expanded review. The new-job
default is approved; executable hard cuts, the narrow raw-queue read-only legacy
path and public control receipts are proposed together for final plan approval.
No runtime changes or phase execution are admitted by this draft.

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
effective choices before admission: `account_for: all`, `enforce: []` when no
earlier explicit selection supplies that axis. Timeout keeps its separate owner.

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

The public `loom.pipeline.runtime.ResourcePolicy` owns the two selection axes
and their strict plain-data codec. Its constructor accepts keyword-only
`account_for` and `enforce`; omitted values remain unspecified for composition.
Explicit lists are immutable/detached, unique and canonicalized by identifier;
`all` is the only special string. Normalize defaults at the new-invocation
boundary, not inside each backend or when decoding retained executable data.
An effective policy has both axes present. Preserve the resolved selection
alongside the existing full demand; derive actual claim keys by intersection
at the admission owner. Keep explicit absent identifiers available for honest
not-applicable reporting. No amount duplication or implicit name conversion.
The shared value may live in a small private runtime module to keep queue and
command-builder imports lightweight; the public facade and meaning are fixed,
not its private file/helper layout.

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

Design-reviewed and maintainer-approved version boundary:

| Existing executable owner | Proposed change | Old-data behavior |
| --- | --- | --- |
| `RunOptions` schema 1 | Schema 2 includes independently composed resource policy | Explicit version 1 is rejected with migration guidance; no silent change to serialized invocation meaning |
| `ResolvedStagePlacement` schema 2 | Schema 3 retains full semantic demand and explicitly selected accounting kinds in its fingerprint | Reject schema 2; do not rebuild all claims from the full demand |
| Exact managed runtime record schema 2 | Schema 3 embeds the new invocation and placements with concrete effective selections | Reject schema 2 before admission; never rewrite the saved record during replay |
| `StageWorkerRequest` schema 1 | Schema 2 requires the resolved policy in its existing `resolved_runtime` mapping | Reject old prepared requests before launch instead of substituting new defaults |
| Resident assignment bundle schema 3 | Schema 4 carries and validates that same resolved runtime | Reject old retained bundles; local/remote launch cannot reinterpret omitted policy |
| `SlurmStageDelivery` schema 3 | Schema 4 carries the same exact resolved demand/policy/selection; enclosing assignment store schema is unchanged | Reject schema 3 at the existing delivery codec before input acceptance or resource/worker launch; never wrap old flattened runtime in a current worker request |
| Whole-run `LaunchContract` schema 2 | A dedicated launch-contract schema 3 includes policy; other queue record and DB versions stay 2 | Preserve the legacy contract for inspection; reject fresh admission and terminally fail a retained queued item through queue ownership, before resource/launch effects |

The worker and resident boundaries are material, not additional copies of the
policy. Current `StageWorkerRequest.__post_init__` only checks the nested runtime's
stage identity and executor, while the resident bundle checks stage identity and
plain data. Both can currently retain policy-free mappings. Updating only the
top-level managed record would therefore leave direct prepared-worker and remote
replay paths without the same executable-version decision. Use one runtime-owned
policy decoder at these actual process/serialization boundaries; do not add a
parallel remote policy envelope or infer choices from claim-provider data.

The SLURM delivery is a separate retained executable boundary:
`queue/slurm_ready_stage.py::SlurmStageDelivery` persists flattened runtime in
SQLite and workspace `delivery.json`; `worker_request` reconstructs a request
using the current worker schema constant. A worker-format cut alone therefore
does not cut the outer delivery. Reject its old schema at the delivery codec,
before workspace input acceptance or worker reconstruction, using the same
pinned-environment/fresh-identity guidance. Keep saved artifacts and the enclosing
store schema unchanged. The existing SLURM ready-stage integration owns old-writer
pre-effect rejection and new exact runtime/selection round-trip coverage.

New, unversioned authored configurations compose under the approved new-job
default. They are new invocations, not retained
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
formats. This proposed boundary implements the approved new-job default without
silently reinterpreting retained work; the narrow opaque `LaunchContract`
read-only compatibility rule is specified below.

### Default Decision And Backend Boundary Evidence

Approved default: account for all declared resources, but apply no additional
resource enforcement unless explicitly selected. Existing timeout ownership is
unchanged. This makes enforcement deliberate and avoids requiring unavailable
host cgroups merely because useful demand was declared. It intentionally changes
direct container CPU/RAM defaults for new invocations. Migration documentation
must explain how old unversioned authored configs become new invocations under
this default and how to retain earlier controls explicitly; retained executable
records must not silently acquire new meaning. Finalize that version/admission
boundary as part of the reviewed design.

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
evidence and are not a condition for the managed CPU diagnostic proof. The exact
candidate metadata shape is owned by Public Inspection And Execution Evidence
below and remains subject to expanded review, not a separate lifecycle API.

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

#### Raw Whole-Run Queue — Recommended Typed Extension

Extend the existing whole-run owners rather than silently exclude this maintained
route. This design and queue-format migration have passed independent review
and final concrete plan approval. Preserve arbitrary logical resources,
assignment leases/renewal/release and enqueue replay; never reinterpret saved
opaque argv or treat a pipeline option as authority over an arbitrary command.

The bounded producer inventory shows that binding attribution can use current
logical names, without a registry or device-name inference:

| Current binding producer | Existing authoritative logical identity | Required extension |
| --- | --- | --- |
| `StaticSlotAssignmentProvider.acquire` | `slot.resource_name` and matching `EnvironmentListBinding.resource_name`; constructor already requires unique environment names | Preserve the logical resource associated with each emitted variable before flattening values |
| `gpu.local._LocalGpuAssignmentProvider._assignment` | The provider's configured plan `resource_name`, distinct from physical device keys | Attribute its visibility binding to that logical resource; keep tokens out of public evidence |
| Maintained `PairedMemberAssignmentProvider._assignment` example | The provider's requested `_resource_name` for the indivisible bundle | Attribute the aggregate binding to the bundle, not to the physical member names appearing in display evidence |
| `NoOpResourceAssignmentProvider` | No concrete assignment binding | Emit no fabricated control; an explicit unsupported binding request cannot be reported as applied |

Extend `LaunchEnvironmentBindings` at its current public boundary with immutable
logical-resource attribution for its emitted environment values. Keep live
bindings separate from `safe_evidence`, and preserve attribution through provider
renewal. The exact field is specified in the compatibility rule below; the observable
contract is that selection is based on producer-owned logical identity, never a
variable name or physical slot label. All maintained producers above must migrate
together. Missing attribution from an external provider follows the candidate
Narrow Whole-Run Compatibility Rule below, not guessed ownership or a fallback.

Propose carrying the same independent policy value through `QueueEnqueueRequest`
and its authoritative `LaunchContract`, resolved and persisted at enqueue. Keep
the full existing integer demand mapping as its only amount authority. On this
API the selection namespace is that mapping's logical pool keys; pipeline APIs
continue to use their existing semantic resource-kind keys. Document the boundary
explicitly: a key such as `lab-accelerators` is not implicitly translated to `gpu`.
Do not introduce another global name mapping, duplicate demand schema or a second
adapter-specific policy. Existing authored launch environment/argv stays immutable;
the queue policy governs only Loom-owned accounting and added assignment bindings.
It does not remove an authored container flag or an inherited scheduler mask.

Filtering only final argv would also leave earlier queue scheduling incorrect.
These exact current consumers all read `LaunchContract.resources` and need the
same selected accounting view while full demand remains available for provenance:

| Current consumer | Policy-sensitive behavior |
| --- | --- |
| `selection._is_eligible` | Excluded demand must not fail the advisory capacity filter before dispatch |
| `selection._evaluate_selection` / `QueueSelectionCandidate.resources` | The injected selection-policy candidate must receive the same accounting meaning as built-in eligibility |
| `QueueController._advisory_available_resources` | Subtract only accounted demand for claimed/dispatched items, not the whole declaration |
| `local._resource_admission_request` | Acquire scalar capacity leases only for selected demand |
| `LocalQueueDispatchAdapter.dispatch` / `ResourceAssignmentRequest.resources` | Do not reacquire excluded resources as concrete assignments after scalar admission |
| `local._merge_assignment_environment` | Select attributed added bindings independently; unchanged reservations still renew/release when enforcement is empty |

An explicit binding request still requires an authoritative concrete assignment
or inherited allocation. Excluding a resource from accounting must not secretly
reserve it just to manufacture a binding. If this route cannot supply the
selected control from its existing evidence, fail with actionable guidance;
do not claim resource isolation or parse the opaque command to invent support.
Readiness/probe behavior and delegated SLURM prepared-command ownership remain
outside this raw local binding policy.

An empty accounting selection also reaches a concrete current edge: the GPU and
paired-bundle providers reject an empty acquisition request. The adapter must
reuse the existing no-assignment path when nothing is requested, not call those
providers with a newly invalid request or invent a reservation to satisfy them.
Queue claim, process supervision, cancellation and cleanup remain required.
Cover this through the configured-provider dispatch boundary, not just selector
normalization.

Minimal new comparisons belong to existing `test_assignments.py`,
`test_local_gpu_assignment_provider.py`, `test_example_paired_assignment_provider.py`,
`test_local_adapter.py`, `test_scheduler.py`, queue-record contracts and SQLite
repository tests. Distinguish GPU/logical-bundle accounting with no added binding,
an independently selected binding, unchanged authored environment, real lease
release, and enqueue/replay of the exact policy. A combined controller case must
prove an excluded capacity demand does not prevent selection and is not subtracted
from later advisory capacity; a final-launch-only test would miss this defect.

The Narrow Whole-Run Compatibility Rule below proposes an isolated launch-contract
version and read-only legacy path; other queue record/DB versions stay unchanged.
The expanded review and final plan approval cover its executable rejection,
old-provider disposition and inspection consequences. The pipeline hard cut alone
does not authorize this queue migration. Apply the approved new-job default only
at the documented new-invocation boundary, never as old-record recovery fallback.

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

The draft also incorporates published P11/P12 owner delivery through `719e016`.
Their changes remove eager factory checking and add inspection diagnostics;
the runtime options, resource admission/placement, container command mappers and
managed preparation owners traced here are unchanged. Keep Loom's structural,
resource-semantic and transport checks, but do not reintroduce project factory
construction as resource preflight. This reconciliation supplies current source,
not design approval, a new runtime-policy implementation or physical evidence.

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
| Whole-run policy and binding attribution | The maintained opaque-command queue currently schedules, admits and adds assignment bindings from the same declared resources | Required in the existing `LaunchContract` and `LaunchEnvironmentBindings`; no resource-name inference, argv rewrite or provider registry |
| Separate pre-placement effective-policy record | No consumer can resolve `all` before planner defaults and semantic refinement are known | Reject; keep authored/composed selectors in runtime options and designate one post-demand-resolution projection for each executable handoff |
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

## Candidate Design Decisions For Expanded Review

These complete the proposed contracts above. The default is maintainer-approved;
the concrete compatibility changes remain part of final plan approval. Review
may correct a qualified gap without reopening the approved default or adding
future resource mechanisms.

### Supported Control Boundaries

| Route | Additional controls supported by this change | Explicit unsupported control | Required preserved behavior |
| --- | --- | --- | --- |
| Native serial process | No new CPU/RAM/GPU mechanism | Fail before application execution, with guidance to a supported adapter or empty enforcement | Independent capacity admission; authored/inherited environment, timeout/cancel/cleanup |
| Managed local and remote agent | Existing attributed provider GPU/other binding with authoritative admitted assignment | Fail when a requested binding has no supported provider/evidence; do not secretly add a reservation | Claims, renewal, fencing, reconnect, termination and provider release |
| Direct Apptainer/Singularity | Existing CPU/RAM flags and supported allocation-visible GPU binding | Existing unmappable demand/absent binding evidence fails only when that control is selected | GPU driver access is distinct from a new visibility restriction; no cgroups under empty enforcement |
| Direct Docker | Existing CPU/RAM flags | GPU enforcement remains unsupported; a GPU declaration without selected enforcement does not trigger that control error | Full demand provenance; no additional flags under empty enforcement |
| SLURM planning/ready-stage allocation | Existing full allocation-demand mapping delegated to SLURM | Unsupported hard allocation requests still fail before submission, regardless of inner policy | Existing SBATCH identity/digest and inherited allocation constraints; no duplicate inner CPU/RAM cgroups |
| Whole-run local opaque command | Attributed bindings from the existing assignment provider | No inferred CPU/RAM flags or arbitrary argv rewrite; missing selected binding support fails | Exact authored snapshot and independent selected logical-resource leases |

All routes use the existing reliability timeout, not another resource selector
for time. Job timeout disabled does not disable control-plane/cleanup deadlines.
The table is a support matrix, not permission to add new host enforcement.

### Public Inspection And Execution Evidence

Existing runtime metadata includes `resource_policy` with both composed selector
axes. Placement/command metadata includes the post-demand `resource_selection`
defined below; it is not an expansion performed by `resolve_run_runtime`.
Extend the existing command/attempt/launch metadata with
`resource_controls`, an ordered plain-data list whose entries have exactly:

```json
{
  "resource": "cpu",
  "owner": "apptainer",
  "mechanism": "container_cpu_flag",
  "disposition": "requested"
}
```

`resource` is the existing declaration identifier (semantic kind or whole-run
logical key). `owner` and `mechanism` are owner-authored diagnostic identifiers,
not dynamic import targets or registered mechanism plugins. `mechanism` is null
when no mechanism applies. Sort by resource, owner and mechanism for reproducible
presentation. Dispositions are `not_requested`, `not_applicable`, `requested`,
`applied`, `delegated`, `unavailable` or `failed`. These are evidence descriptions
at existing emission points, not a persisted resource-control lifecycle.

Prepared argv/preflight can report only requested support, not applied controls.
`applied` means that the actual launch owner supplied that additional binding or
flag to a launched process, never measured kernel enforcement. A known setup or
container-creation failure is `failed`, not applied; ordinary application failure
after a launched job does not erase the launch evidence. Use existing process
result/error evidence to distinguish them and do not infer inner-container
success merely from a non-null outer command result. When evidence cannot
establish application, retain requested/failed status rather than overclaiming.

SLURM allocation evidence is owned by the existing request/submission receipt:
resource policy does not suppress those directives. `delegated` describes that
allocation request, while a separate inner-owner entry can be `not_requested`.
This permits truthful reporting of inherited scheduler controls with no extra
Loom limits. Existing claim/lease facts remain the only reservation evidence;
do not copy raw lease capabilities, device tokens or environment values into
this list. Existing diagnostic failures preserve the actionable underlying reason.

No new store, endpoint, report file or global schema is required. These values
extend existing metadata mappings and use their current plain-data boundary.
Older inspection records missing these keys remain readable as unreported;
absence must not be presented as verified no enforcement. Control constructors,
serialization and the renderer share the same definition rather than validating
ad hoc copies at every private helper.

### Narrow Whole-Run Compatibility Rule

Give only `LaunchContract` its new executable version, 3. Keep
`QUEUE_RECORD_SCHEMA_VERSION` and `QUEUE_DB_SCHEMA_VERSION` at 2. Its public
codec accepts the exact old schema-2 shape for inspection and preserves its
original `to_dict()` bytes/fields, including the absence of policy, so enclosing
queue-item admission digests remain valid. A legacy record carries no effective
policy; it must never be passed through new-job default normalization.

All fresh constructors/enqueue requests produce version 3 with the composed
policy and concrete selection, included in existing admission/replay identity.
`QueueService._admit` rejects supplied old launch contracts before repository
writes. For already retained queued items, the controller claims queue ownership
and persists the existing invalid/unsupported FAILED result before resource
admission, assignment or spawn, as specified in the correction below. Direct
adapter dispatch keeps its public pre-resource/pre-launch guard. The error
names the incompatible launch version and instructs the operator to
finish/cancel active work in the compatible pinned environment, preserve the
old artifacts, and enqueue a fresh identity with explicit policy. Do not rewrite
the nested legacy launch contract or restart/recover it under new defaults.
Only the existing outer lifecycle can record that incompatible execution failed.
Ordinary read-only queue
inspection remains usable; no new migration command or automatic live adoption.

The existing `LaunchEnvironmentBindings` gains authoritative attribution as
`resource_names: Mapping[str, str]`, keyed by emitted environment name and valued
by its declaration's logical resource key. The environment and attribution are
both immutable/detached. Supplied attribution must refer to existing environment
keys; unattributed values remain representable for existing external providers.
At a new policy-aware launch, no requested enforcement ignores those values
without dropping their assignment leases. A selected binding requires matching
attribution and a supported request; otherwise fail before spawn and perform
existing pre-start release/cleanup. Do not guess that all raw values belong to
the one requested GPU. Maintained static/GPU/paired providers populate the field
and preserve it on renewal. No new provider protocol or amount field is needed.

The old-provider compatibility comparison is deliberate: a flat external
provider remains usable with the approved no-enforcement default, while opting
into binding requires adding attribution. Documentation names that small update
and the unavailable-control error. Enqueue/replay, old-schema read-only digest
preservation, durable pre-resource rejection, direct-dispatch rejection and actual binding
selection each have a current consumer and a discriminating existing test owner.

### Bounded Design Correction — Effective Selection And Legacy Disposition

EDR-39-01: `ResourcePolicy` remains the composed selector, including `all` and
explicit names absent from a particular demand. `resolve_run_runtime` knows
invocation/profile/stage options, not placement defaults, and must not expand
those selectors. One runtime-owned projection computes sorted concrete identifier
lists only after its caller has the full semantically normalized effective
demand. The plain mapping is `resource_selection` with exactly `account_for`
and `enforce`, each a list of selected applicable identifiers. Omitted/zero
demand cannot create a claim/control. Selector intent and full demand remain
available for not-applicable explanations; no new effective-policy class/store.

For managed execution, `resolve_stage_placement` calls that projection after
authored demand, deployment defaults and planner refinement are resolved. The
schema-3 placement owns the saved `resource_selection` alongside its full
`resource_request`; both participate in its fingerprint. Its strict reader
checks the selection against those saved inputs, never against changed runtime
defaults. `local_daemon_execution.load_managed_local_intent` currently rebuilds
runtime options before loading placements: change that join so the worker-facing
runtime consumes the saved full demand and exact concrete selection from its
placement. Do not expand `all` again in resident/remote launch code.

`StageWorkerRequest.resolved_runtime` carries that projection through its existing
mapping and the existing resident/remote request, without another transport
envelope. At preparation and retained-worker replay, compare it with the
authoritative placement before launch. All native/remote provider-binding and
worker/command consumers use that exact projection. A mismatch is an actionable
pre-effect error, not a reason to silently refresh a saved worker request.

Non-managed consumers use the same projection at their existing effective-demand
boundary, not a new managed placement: serial admission resolves its actual
declared/runtime demand before the lease-specific integer check; direct container
construction uses the unchanged runtime-over-container demand precedence; whole-run
enqueue uses its validated logical-resource map. Store the projection in each
existing executable handoff with that full demand. A public builder used on its
own is such a first boundary; a builder receiving a prepared projection must
consume/validate it rather than apply new defaults. This is one definition used
at distinct current ingress owners, not multiple competing projections of the
same prepared job.

Required discriminators: managed default CPU with selector `all` appears only
after placement resolution; GPU-only accounting preserves full refined demand
without CPU claims; planner ABSENT/zero does not invent a selection; persisted
placement → worker → remote/local launch uses identical selection, and a changed
worker selection is rejected before launch. Existing direct-runtime/container
and queue tests cover their distinct normalization boundaries.

EDR-39-02: retain schema-2 decoding for inspection without new policy defaults.
Within the existing bounded candidate page, a legacy QUEUED item must be eligible
for compatibility disposition independently of its old capacity request or custom
preference: a request larger than available capacity must not strand it forever
ahead of new work. Claim only the existing queue-item ownership, using the exact
attempt/claim guards, then supply the existing NOT_STARTED result with
INVALID_OR_UNSUPPORTED cause and NOT_REQUIRED cleanup. The existing
`_apply_dispatch_result` persists FAILED and permits bounded cycle continuation.
Do not acquire scalar/concrete resource leases or call an adapter to discover
the known incompatible version. Preserve the nested legacy shape and admission
digest; only the normal outer claim/attempt/failure/audit facts change.

Keep selection/claim races and cycle/page limits at their current owners. Do not
add another lifecycle state, unbounded scan, migration queue, compatibility
registry or exception-based retry loop. A current-version candidate still follows
ordinary capacity/preference selection. Test a bounded mixed old/new queue where
legacy demand exceeds capacity: legacy becomes FAILED once, with actionable
version evidence and no resource/launch calls; new work remains selectable and
subsequent cycles do not rediscover the same queued legacy item. Direct adapter
calls retain their guard for bypassing callers. Existing active old work is not
adopted or restarted by this compatibility disposition; use its pinned environment
to finish/cancel it, as the migration guidance states.

### Design Review State

Initial removal-first review found two qualified design blockers; targeted
confirmation accepts the bounded correction above. The approved default is not
reopened. The public selector, whole-run attribution, existing-owner evidence and
hard executable cuts are proportionate with the two handoff/lifecycle gaps
resolved; optional host measurement, new
mechanism registries and broader migration tooling remain deferred.

| ID | Disposition | Accepted contract / current consumer | Finding and smallest correction | Status |
| --- | --- | --- | --- | --- |
| EDR-39-01 | clarify one owner | FR-39-01, FR-39-02, FR-39-03 and FR-39-08; `local_daemon_runtime._runtime_payload` calls `resolve_run_runtime` before `resolve_stage_placement`, while placement alone knows authored demand, planner defaults and semantic refinement | The draft requires concrete effective choices before admission but assigns them to the pre-placement resolved-runtime handoff as well as schema-3 placement. `account_for: all` cannot be expanded truthfully there: the current default CPU and planner-refined demand do not exist yet, and independent reconstruction risks placement/worker drift. Keep `ResourcePolicy` as the composed selector only. Name the post-demand-resolution projection as the sole owner of concrete selected identifiers, persist that result with the full demand, and require the worker/command handoff to consume or compare that exact projection rather than resolve `all` again. No second effective-policy type or store is needed. | resolved: placement-owned post-demand projection and exact handoff comparison confirmed |
| EDR-39-02 | correct legacy disposition | FR-39-08 and the narrow read-only rule; persisted schema-2 `QueueItem` values remain decodable, and `_evaluate_selection` currently treats every queued item as eligible before `_select_and_acquire_for_pool` claims it | “Reject before queue claim” has no current transition or durable result. A legacy queued item can therefore be selected repeatedly, abort a cycle, or occupy the bounded candidate page while newer schema-3 work waits. Use the existing controller lifecycle: claim only queue ownership, then return the existing invalid/unsupported, not-started result with cleanup not required, persist `FAILED`, and continue the cycle before scalar admission, assignment or spawn. Preserve the nested schema-2 launch contract and admission digest unchanged. Direct adapter dispatch retains its public pre-effect guard. | resolved: bounded claim-to-FAILED disposition before resource/launch effects confirmed |
| EDR-39-03 | keep | FR-39-01 through FR-39-04; whole-run selection, advisory capacity, scalar admission, concrete assignment and binding merge all currently consume `LaunchContract.resources` | The typed whole-run extension is not future-only: leaving it unchanged would violate the approved default and make final-launch filtering too late. Reuse the same selector value, existing amount map and producer-owned binding attribution; add no logical-to-semantic name registry. | pass |
| EDR-39-04 | keep | FR-39-04, FR-39-06 and FR-39-07; capability/preflight, container launch metadata and SLURM submission receipts are current inspection consumers | The bounded `resource_controls` projection is justified, provided each existing emission point reports only what it can establish and absence remains unreported rather than verified none. It is not a lifecycle store or proof of measured kernel enforcement. | pass |

Domain neutrality, import direction, timeout ownership, provider compatibility,
examples and non-Cartesian validation otherwise pass. Manager verification read
the concrete `_runtime_payload`/placement/intent-loader/worker preparation join
and the bounded queue selection/claim/NOT_STARTED-to-FAILED transition. Targeted
confirmation found both corrections complete: default CPU and planner refinement
precede the single concrete projection, retained worker paths compare that saved
projection, and legacy demand beyond capacity cannot bypass the compatibility
disposition or block later current work. No runtime test is claimed by this
design-only verification.

## Phase Shaping And Quality Gate

The minimum-design tasks are resolved. The compact
[implementation manifest](implementation-plan.md) links two vertical phases:

1. [Pipeline resource policy](phases/pipeline-resource-policy.md): compose policy,
   resolve/select full demand, admit it, preserve exact local/remote worker
   handoffs and migrate all container/SLURM consumers with truthful diagnostics.
2. [Whole-run queue policy](phases/queued-resource-policy.md): reuse those policy
   semantics at the distinct opaque-command/logical-resource API; migrate every
   selection/admission/binding consumer and its retained-contract boundary.

Pipeline composition, admission and executor migration stay atomic: otherwise
the approved no-enforcement default would coexist with implicit old controls.
The whole-run API keeps its old behavior until its complete Phase 2 migration;
Phase 1 documentation explicitly scopes its new default. Phase 2 starts after
Phase 1 remotely merges. Neither phase is foundation-only or tests-only.

Required local gates for each implemented Loom phase remain `make validate-pr`
and `make test-summary`; independent correctness review is required for these
public/durable/runtime changes. Hosted CI remains disabled. Normal Loom isolated
phase branches/PRs target develop, with verified merge and exact cleanup.

Current quality gate: expanded design review passed after one bounded correction
and targeted confirmation. Independent packet review found one missing retained
SLURM delivery cut; its bounded correction adds the existing delivery codec's
3→4 boundary, pre-input/pre-worker rejection and exact old/current integration
oracles. Manager verification confirms the source path and corrected card.
No other qualified plan findings remain. Documentation diff, links and targeted
test paths pass mechanical checks; no runtime tests or resource guarantees are
claimed. The maintainer approved the concrete migration and two-phase packet;
implementation can proceed through the linked manifest and canonical workflow.
This approval does not authorize physical/GPU runs or host configuration changes.
