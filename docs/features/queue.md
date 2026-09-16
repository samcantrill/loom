# Native coordinator and agent services

`loom.queue` contains the native coordinator/agent ownership implementation.
The public user interface is the [coordinator client](coordinator-client.md).
Installed service configuration and preparation are described in
[agent preparation](agent-preparation.md), and [execution](execution.md) owns
lifecycle and incompatible-version cutover guidance.

The old whole-run queue service, client, controller and dispatch adapters have
been removed. Historical queue records remain read-only inspection evidence.
A historical queue record is never admitted as new native work.

## Native stage scheduling

Native execution schedules each
dependency-ready executable stage attempt. The queue item and `run_uri` remain
the user-facing submission, status, and cancellation identities. Command-scoped
local execution, the persistent local daemon, and
several remote agents compose one durable run orchestrator, one fixed placement
correctness kernel with explicitly composed pure policy/resource interfaces,
one assignment lifecycle, and one agent runtime. Within a native run, an exact stage assignment may instead target one explicit SLURM
profile while the coordinator retains run/readiness/attempt ownership and SLURM
retains node placement.

New managed admission is unique for `(coordinator_id, run_uri)`. The durable
root's stable coordinator ID is the namespace. The
atomic create-or-return record pins a normalized immutable intent digest and one
execution owner (`managed_stage`). Exact replay—including
after a response timeout—returns the same
queue item/admission; changed intent or owner conflicts. Resume addresses that
admission and authority run, while rerun requires a new `run_uri`.  Historical managed-local rows are rejected and are not
converted into new admissions.

Acceptance is a recoverable two-owner protocol rather than a fictitious
cross-database transaction. The coordinator may first commit the admission as
`PENDING_AUTHORITY`, including an authority-operation identity and the expected
normalized intent, before asking per-run authority to bind the stable execution
owner. Only reconciliation of that exact owner, intent digest, and operation
receipt promotes the admission to `ACTIVE` and exposes stage work. An authority
outage therefore leaves a visible accepted-but-not-runnable admission; a
conflicting owner or intent leaves a visible blocked admission rather than a
second owner. A submit retry returns the same durable state.
If a cancellation request is already durable while admission is pending,
authority owner binding and the authority cancellation epoch are reconciled
before `ACTIVE` promotion/work exposure. This ordering does not make the
coordinator request lifecycle truth.

The scheduling subsystem has two deliberately separate decisions:

```text
run orchestrator   interprets the persisted plan and authoritative output state
placement engine   chooses where an already-ready executable attempt should run
```

One shared authority-side readiness predicate is used when authority
idempotently prepares an exact unassigned `PENDING` attempt, when its rebuildable
stage work is exposed, and again when that exact attempt is bound to an
assignment. Preparation records bound-input/readiness evidence but creates no
worker request, workspace, assignment, execution lease, or process. The
placement engine never interprets DAG edges. For `preprocess -> train -> evaluate`, only
`preprocess` initially appears in a placement snapshot. `train` appears only
after the preprocess output commit, and `evaluate` appears only after train
commits. Reuse, skip, blocked descendants, and retry remain planner/reliability
behavior and do not consume agent capacity.

Each prepared `PlanAction.RUN` attempt has an immutable resolved placement
built from its authored `ResourceRequest`, exact-stage runtime refinements,
run/pool policy, and site policy. Resources are never added across the whole
pipeline. CPU is a positive integer count; memory and VRAM normalize to integer
bytes. Hard constraints remove candidates; soft preferences rank only feasible
ones. A GPU-model preference affects a GPU training stage but not a CPU-only
preprocess stage. A hard run or stage target never spills; a preferred agent is
soft and follows explicit fallback.

The coordinator persists a rebuildable `StageWorkRecord` containing the exact
`(admission, run_uri, stage_name, attempt, readiness_generation)`, ready time/order, plan/authority revision,
upstream commit identities, and resolved-placement fingerprint. It does not own
stage success or failure. Its semantic key maps to one stable `stage_work_id`:
rebuild may refresh the projection revision but never re-key or discard a
referenced work record. Per-run authority remains the owner of plans,
attempts, statuses, bound inputs, output commits, and retry facts.

The scheduler receives one immutable bounded global snapshot:

```python
snapshot = SchedulingSnapshot(
    ready_stages=coordinator.ready_stage_window(),
    opportunities=fresh_agent_availability(),
    pool_policy=policy,
)

decision = scheduler.choose(snapshot, resource_planners)
```

Default stage order is run priority and enqueue order, ready time, topological
order, stage name, then attempt. The kernel creates one bounded
`WorkEvaluation` group per work item. Every resource search and composite claim
product must be complete before that work is assignable. An earlier work item
proven infeasible or typed `SEARCH_EXHAUSTED` may be bypassed so, for example,
idle CPUs can run another complete preprocess placement while training waits
for a GPU or a larger search bound. Exhaustion is not infeasibility, and Stage
29 has no partial-search winner-proof path.

All dependency-ready unassigned `PENDING` attempts in the bounded window may be
projected; they consume no `max_parallel_stages` slot. The coordinator
assignment CAS atomically counts the run's reserved, bound, accepted, granted,
running, and unknown assignments and rejects a new reservation at the limit.
This prevents concurrent scheduling cycles from over-admitting while leaving
compatible ready branches visible.

Every authenticated agent publishes configured inventory separately from
current availability:

```text
inventory     resources trusted local configuration permits Loom to manage
availability  exact resources assignable in this versioned offer revision
```

Inventory is the capacity that local configuration and its provider permit Loom
to manage, not an inference from arbitrary host telemetry. A provider may
conservatively withdraw capacity used outside Loom. If it cannot account for or
fence competing use, site configuration must withhold that capacity. Resource
requests prevent placements known to be impossible from the reported contract;
they do not prove that authored peak usage is accurate or guarantee against an
application OOM. An exclusive GPU claim grants a device, not a VRAM limiter;
VRAM sharing is schedulable only through a provider that enforces that mode.

Availability names the live claim summaries already subtracted from its net
remaining atoms. Coordinator logical reservations for those claims remain
ownership evidence but are not subtracted again. Only an unreflected admission
against the current revision consumes that baseline; one unresolved admission
is permitted before accepted/declined reconciliation publishes a fresh
revision. This serializes admission against one snapshot, not process execution:
once an accepted claim appears in fresh net availability, another disjoint
claim may run concurrently on the remaining atoms.

An offer binds agent/session/configuration, project and executor capabilities,
inventory and availability revisions, pool, resource-contract versions, and
coordinator-accepted receipt-time expiry. Coordinator restart requires session
reconciliation and a freshly received current-epoch offer/work request before
new delivery; a retained old offer cannot create a new assignment. Expiry
removes only future schedulability. It
does not prove process death, release accepted work, or permit session takeover.
One stage claim fits wholly on one agent; CPU from `machine-A` is not combined
with a GPU from `machine-B` for one stage.
This still permits different stages and independent pipeline branches to run on
different agents. A distributed stage is one attempt that needs several agents
simultaneously; its all-or-none multi-agent reservation is gang scheduling and
requires a different candidate, batch-commit, rendezvous, launch, and group-
failure contract.

A reconnect normally resumes the durable session. A clean new session is
allowed only after the authenticated old session withdraws/fences delivery and
coordinator plus agent reconciliation proves the complete assignment/claim/
control/transfer/outbox set empty; the old identity becomes a tombstone. If the
old journal is unavailable or anything remains unresolved, Phase 9 positive-
containment replacement is required. A new connection, expired offer, or changed
credential is not retirement.

The coordinator allocates a session identity idempotently and the agent commits
its registration operation identity before send and the returned session before
publishing an offer. A later phase that adds a session-scoped durable
reference must extend the one authoritative clean-retirement query. The agent
cannot mint a fresh identity to escape unresolved work.

Resource-specific matching is explicitly composed trusted code behind
`ResourcePlanner`; stored and wire values never load callables. The planner
validates/canonicalizes each resource opportunity, owns intrinsic quantity/
unit/mode/per-instance/same-resource-topology feasibility, produces complete
bounded claims, and validates them. A fixed concrete `SchedulingKernel` owns
composite completeness, mandatory checks, checked preference aggregation,
fallback eligibility, extension-result validation, and mutation exclusion.
Subsystem-public
`HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy` protocols
respectively add complete-placement rejection, bounded utility/quality-band
evidence, and selection of one existing grouped work/candidate pair or wait.
They cannot reserve, bypass fallback/run concurrency, bind, launch, or commit
lifecycle truth. CPU/memory planners propose exact scalar claims. A GPU
planner proposes exact devices and supports only explicit exclusive, provider-
enforced VRAM-share, or named provider-defined fractional modes. Native execution adds
no full replaceable lifecycle scheduler, payload-loaded callable, unrestricted
constraint language, or general solver.

Run priority and preferences affect selection of unstarted work only.
Preemption would checkpoint/stop a live assignment and prove physical release;
fair-share would add historical user/project entitlement and usage accounting.
Neither is a scorer. A general solver would optimize variables and an objective
across several work items/agents and normally return a snapshot-bound batch;
Native execution instead completely evaluates bounded one-agent candidates and its
policy selects one exact existing pair or waits. The default remains
non-preemptive deterministic priority/FIFO with safe bypass and no starvation
guarantee.

Registered hard/preference components validate and canonicalize bounded tagged
specs during admission; only resolved immutable specs enter scheduling. A bad or
unknown spec fails admission instead of becoming indefinite queued work. Jobs
cannot select the scheduling policy or its weights/tier configuration.

Site policy assigns immutable ordered tiers and bounded weights. The kernel uses
checked integer arithmetic to compare one tier vector lexicographically, then a
stable identity tie-break; a large lower-tier score cannot override a higher
tier. A guarded fallback names one preference and uses durable `ready_at` plus
snapshot `as_of`, so only its `PREFERRED` band is selectable before the deadline
and restart does not reset the wait. Candidate vectors compare only within one
work item.

Every claim exposes exact agent-local capacity atoms namespaced by owning
resource kind and carrying exact unit/granularity, which the coordinator can
reserve atomically at the expected availability revision. Provider-specific
claim data remains separate and is contractually forbidden from hiding
additional consumption; trusted provider code is not sandboxed. Planner and
provider keep distinct implementation descriptors and negotiate a versioned
resource-claim contract; the assignment records all of them, while final local
provider admission remains authoritative.

Every scheduling/provider implementation has an immutable descriptor and is
explicitly supplied through an instance-local registry frozen for one
configuration epoch. Active bindings resolve fresh work; exact descriptor-keyed
retained bindings reconstruct accepted runtime placements, referenced nonterminal
stage work, and live claims, or a reload fails before swap. Admission and reload
are serialized: an intent accepted before reload retains its exact bindings, while
a stale not-yet-admitted intent is rejected before mutation. Ready work from
different epochs may coexist in one decision: each stage-work identity is
evaluated with its exact retained planner, hard-rule, and scorer bindings, while
the one active policy compares the combined evaluations. The descriptor has
distinct implementation and non-secret canonical configuration fingerprints.
Durable records keep identity/version/fingerprint only; unknown or changed
contracts fail before scheduling/launch. A separate agent-side
`AgentResourceProvider` observes and performs assignment-scoped prepare,
reconcile, activate, abort, and release through idempotent commands and closed
typed outcomes. Public bounded conformance checks cover custom examples, but
in-process implementations remain trusted code and are not automatically
discovered or sandboxed.

Reload is owner-local rather than one distributed configuration swap. An agent
atomically validates and swaps its pools, providers, inventory, and resident
capabilities while retaining every descriptor referenced by local durable work.
The coordinator separately validates and swaps resource planners, constraint
evaluators, preference scorers, and scheduling policy while retaining its own
referenced descriptors. Temporary claim-contract skew simply makes that
agent/opportunity ineligible until both sides negotiate a compatible contract;
neither owner rolls the other back.

Cross-store correctness is a recoverable protocol, not one imaginary
transaction:

1. Authority idempotently prepares or returns the exact unassigned `PENDING`
   attempt for its readiness generation; coordinator materializes rebuildable
   stage work.
2. Coordinator transaction rechecks the run's active-assignment limit, reserves
   current logical claims, creates an assignment intent, and records a bounded
   receipt identifying the policy epoch, work/candidate, snapshot/revisions,
   score/fallback evidence, and stable reason codes.
3. The shared readiness predicate is rechecked and authority CAS binds that
   still-`PENDING` prepared attempt to the assignment without advancing stage
   lifecycle.
4. Agent durably stages the immutable request and required inputs, then performs
   final physical binding. A definitive pre-grant decline may CAS-unbind only
   that same binding before coordinator capacity is released; ambiguous
   acceptance remains bound.
5. After acceptance, grant promotion changes the bound attempt to `SUBMITTED`
   and creates an authority execution fence independent of coordinator
   liveness. `SUBMITTED` means granted, not proven started. The agent records
   grant/start intent before at most one root launcher invocation and then
   journals confirmed, failed, or unknown start. Only exact current-fence
   confirmed process evidence advances authority to `RUNNING`; unknown start
   remains `SUBMITTED` and cannot be relaunched. `START_FAILED` is definitive
   only when no managed process was created or can later run; an uncertain
   spawn is `START_UNKNOWN`.
6. Agent retains output until an authenticated transfer/backend finalizer
   returns coordinator-accessible `ArtifactRef` values. Output upload grants are
   issued only after an authenticated durable manifest binds exact names,
   digests, sizes, assignment, and execution fence. Only their authority
   output commit unlocks descendants and releases the coordinator's logical
   reservation. On the ordinary path, the agent releases its physical claim
   only after process containment, durable terminal-result/output retention,
   and acknowledgement of authority terminal reconciliation; a fresh
   availability revision then makes released atoms schedulable. Authority
   terminality alone never asserts that provider release already occurred.

For the protected same-host resident route, Loom preserves the regular files in
the stage artifact directory as one atomically published local tree and stages a
separate copy beside each primary input. This lets a declared file artifact use
relative companion files without making those companions additional declared
outputs. It does not extend the authenticated remote relay: remote agents and
SLURM bootstraps still transfer only the declared immutable regular files.

The coordinator and each agent use separate explicit local-filesystem SQLite
state roots and process locks. Shared/NFS SQLite is not a cross-machine
communication mode. Preflight checks distinct roots, permissions, schema,
locking/durability behavior, and configured storage headroom; store/high-water
failure withdraws future work and never falls back to memory or drops
unacknowledged truth. A mutation response or agent-event acknowledgement is
success only after the required SQLite transaction satisfies the configured
crash-durability contract. Explicit initialization alone may create a verified
absent/empty target and its stable role identity; ordinary start is open-only.
A missing, corrupt, or identity-mismatched expected root is blocked lost-state
recovery, never an implicit empty coordinator or agent.
The coordinator persists one nondecreasing accepted-time high-water for offer
expiry, fallback, receipt, and freshness. Detected local regression or an out-
of-policy jump makes time health degraded, pauses new scheduling, and withholds
retained capacity until clock/session reconciliation; it never extends an old
offer by trusting a rolled-back clock.
A production command-scoped composition opens and retains those same kinds of
role roots; “embedded” changes process lifetime only. It connects to a compatible
active owner when configured/reachable or acquires the role locks itself. A held
but unreachable/conflicting root fails closed, and command exit never deletes
ownership, receipt, session, or tombstone state.
A granted stage continues while the coordinator is unavailable because its
request and inputs are already local; the agent journals and retains results
until reconnection. No new or downstream work starts until the coordinator
returns and authority commits the result. Agent loss removes capacity but does
not fail or reassign accepted work. Exact reconciliation or
positive-containment operator recovery is required.

All persistent HTTP peers use mutual TLS with expected service/client identity,
but authentication is followed by per-operation role, object, agent/session,
and pool authorization. One coordinator application owner presents separate
client, agent, and operator views. HTTP derives actor identity from the verified
connection; direct adapters capture a trusted principal at construction and
invoke the same authorizer. Body/path identity cannot expand authority.
Every operation, including each long-poll renewal, rechecks the principal
against the current credential-policy revision. Removing a credential therefore
fences future operations even on an established connection; it does not retire
the durable session, prove process containment, or release work.
Mutations use principal/content-bound idempotency plus expected generations,
revisions, and fences; codecs impose method/content-type/schema/version/size/
cardinality bounds and safe errors before mutation. One connection is delivery-
active per agent/session; reconnect fences only the old connection's future
protocol mutations, never its granted process. Actionable idempotency receipts
cannot be pruned without an unusable terminal/expired tombstone. Role locks
support restart from one durable state root, not HA from cloned databases/keys.
Configured principal/pool admission quotas bound pending work; site policy owns
accepted priority ranges and preference weights/tiers rather than job payloads.

The stable coordinator ID belongs to its durable root; a process epoch rotates
on restart and each assignment retains its issuer epoch. New work/control needs
the current epoch, while exact old-issuer events may be accepted only during
reconciliation for their retained assignment/session/fence. Critical agent
events have stable IDs and monotonic per-assignment sequence; acknowledgements
cover only durably persisted contiguous evidence. Timeout, disconnect, caller
cancellation, or 5xx after send is indeterminate and retries the same operation
identity/digest rather than assuming rollback. This includes the pre-grant
assignment-control poll: a lost control response retries through the assignment
reconciliation boundary, so an exact durable cancellation and its acknowledgement
replay before any grant or launch. Conflicts remain definitive, and exhausted
retries retain the pre-grant assignment rather than releasing or starting it.

Per-run authority remains a separate service/API owner. A narrow authenticated
coordinator principal is the only Native execution role allowed to invoke its expected-
state lifecycle operations; the coordinator also verifies authority service,
workspace, generation, schema, and capabilities. Owner-contained local IPC may
use verified peer identity, while persistent HTTP—including loopback—uses
mutual TLS. Agent, client, operator, and worker credentials cannot call this
view, and workers receive no authority endpoint or direct database access.
Authority loss pauses preparation, binding, grant/delivery, and terminal commit
without stopping already-granted work. Before every coordinator-originated
authority mutation, the coordinator persists a stable operation identity,
canonical intent digest, expected state/revision, and principal. Authority
commits the corresponding receipt atomically with its domain mutation. A
rotated authority generation is adopted from one consistent authority-relevant
cut only when each retained admission/tombstone either exactly matches the last
acknowledged checkpoint or advances through an ordered chain of matching
receipts. This receipt-aware path handles the valid case where authority
committed a request but its response was lost before both processes restarted.
Regression, a missing receipt, an unexplained mutation, owner/intent mismatch,
or torn per-run reads fail closed. The checkpoint remains comparison evidence,
not lifecycle truth. Pristine-empty bootstrap is valid only when there is no
authority-relevant retained admission or tombstone; missing or divergent
expected truth leaves the coordinator degraded.

Agents connect outbound using bounded long polling and own no prefetched durable
queue. Coordinator policy authorizes pool membership, while one exact agent
availability domain backs every allowed pool view so capacity is not duplicated
per pool. Work names a prepared resident stage and safe versioned values, not
arbitrary shell text or implementation targets. Worker environments exclude
daemon service credentials and role internals by default, while same-user
project code remains trusted. A bounded initial coordinator relay accepts
immutable regular-file payloads only and provides network-only input/output
movement through coordinator-issued assignment-scoped transfer identities,
derived traversal/symlink-safe staging roots, quotas, digests, temporary-first
promotion, and manifest-last publication. A transfer identity and its exact
byte/finalize progress are stable and durable; a separately versioned
short-lived authorization is renewable. Authorization expiry or coordinator
restart blocks the next byte operation but does not erase staged bytes, release
the assignment, or change lifecycle state. Exact offset/content/finalize replay
is idempotent; conflicting overlap or content fails closed.
Payload paths or arbitrary fetch URLs do not select host/network access, and
agent-local file paths are never committed as remote output refs. Directory/
tree, special-file, and ambiguous payload forms make a remote candidate
ineligible but do not block an eligible local placement; no implicit archive
contract is assumed.

Protected deployment configuration supplies explicit local role roots,
coordinator/authority endpoints and expected identities, trust/certificate/key
references, current principal/pool policy, configured manageable resources and
providers, scheduler components, and resident capabilities. First initialization
creates each stable role identity; ordinary start is open-only. Remote agent
startup follows authenticate service -> capability handshake -> register/resume
session -> reconcile durable facts -> publish fresh current-epoch offer -> hold
one revision-bound work request. Authority -> coordinator -> agents is the
recommended low-noise start order but not a correctness dependency: an early
agent reconnects at zero availability, a coordinator without authority admits
only `PENDING_AUTHORITY`, and a coordinator without agents retains no-capacity
waiting work. Private keys and service credentials never enter job data,
committed `.env`, offers, or workers.

Role applications use schema version 3. `daemon-check`, `daemon-init` and
`daemon-serve` read a `loom.coordinator-service` document. Its `local_agent` is
either `null` for a pure coordinator or an explicit reference to a
`loom.local-agent-service` document. `agent-check`, `agent-init` and `agent-serve`
read a `loom.outbound-agent-service` document. Worker installation and resource
settings belong to the agent. A pure coordinator requires no local worker or GPU.

Every command accepts an explicit `--env-file`. Weave composes the protected
YAML against that file's values without inheriting missing values from the
service process. There is no automatic dotenv search or shell execution. A local
agent reference chooses its own `config` and `env_file`; their paths resolve
beside the coordinator YAML, while paths inside the agent YAML resolve beside
that agent file. Preserve virtualenv executable spelling when setting
`python_executable`: resolving `.venv/bin/python` to its system-Python target can
lose the environment. Role inputs must be owned by the current user with no
group/other permission bits.

Initialization uses fresh roots and retains the resolved role and private launch
binding. Start and explicit reload check compatibility before offering more
work. Startup does not migrate or reinterpret populated older roots. The explicit
[coordinator schema-12 upgrade](../downstream-operations.md#upgrade-a-retained-coordinator-root)
preserves existing work and worker roots while enabling preparation storage.
Other incompatible roots stay on their compatible runtime until work settles,
before deliberately initializing a replacement.

### Resident installation checks

Install the project before checking its agent. A uv-created environment and a
pip-created environment are both usable: Loom runs the configured installed
Python directly. It does not create a virtualenv, install packages, run `uv run`
or `uv sync`, clone a repository, or select a job from a repository name. The
prepared pipeline's stage factory chooses the work; the resident profile chooses
the Python executable and working directory.

An agent profile can declare a finite installation requirement:

```yaml
resources:
  cpu_capacity: 1
  memory_capacity_bytes: 0
  gpu: {provider: nvidia, devices: none}
resident_profiles:
  - descriptor:
      profile_id: project-cpu
      revision: v1
    project_root: ${oc.env:LOOM_PROJECT_ROOT}
    python_executable: ${oc.env:LOOM_PYTHON}
    cpu_capacity: 1
    memory_capacity_bytes: 0
    gpu_devices: []
    environment:
      PROJECT_MODE: dummy
    readiness:
      python_version: "3.12"
      imports: [loom, my_project]
      distributions: [loom, my-project]
      import_roots:
        my_project: src/my_project
      source_roots: [src/my_project]
      required_environment: [PROJECT_MODE]
      timeout_seconds: 5
```

The default requirement imports `loom` and observes its installed distribution.
Python must be at least 3.12; an optional `python_version` selects a prefix such
as `3.12` or the exact three-component version. `python_implementation` and
`python_abi` can constrain the observed implementation and ABI.
`distribution_versions` maps declared distribution names to exact versions;
it is not a dependency resolver or a version-range language.
`required_programs` checks availability on the actual worker's PATH.
`import_roots` asserts that a declared import comes from the expected private
directory. Merely importing a same-named package elsewhere does not satisfy
that assertion. Source and import roots resolve against `project_root`.

`readiness.preparation: true` additionally checks Loom's preparation stage and
Weave's configuration loader in the selected Python. A nonempty
`preparation_shared_roots` mapping or outbound `preparation-input-v2` capability
requests this check automatically. It reports `packages.preparation_imports`
without adding imports to the portable software fingerprint declaration. See
[preparation rollout](agent-preparation.md#operator-configuration-and-rollout)
for profile and capability selection.

First the selected executable must answer a fixed stdlib handshake; only then
does another bounded process import the declared packages and inspect metadata.
Both processes use the worker environment builder and configured cwd. Profile
variables are explicit; the service's ambient environment and complete dotenv
file are not copied into workers. Unassigned probes have no assigned GPU
visibility, disable bytecode writes, and use private temporary scratch/cache
directories. Output, elapsed time and process descendants are bounded. Raw
subprocess output and private path/environment values are omitted from ordinary
findings. Trusted import code is not sandboxed.

```sh
loom queue daemon-check coordinator.yaml --env-file coordinator.env
loom queue agent-check agent.yaml --env-file agent.env --format json
loom queue agent-check agent.yaml --env-file agent.env --probe-io
```

Default checks create no durable deployment, run, claim or authority state.
Reports reuse `PASS`, `WARN`, `FAIL` and `SKIP`, with stable check IDs, groups,
owner, consequence, repair, applicability and evidence. Independent installation
failures are collected together; a failed Python handshake blocks its dependent
imports. A required failed check returns exit code 3. Communication checks run
at actual startup/reconnect; scientific data, cache and run/artifact-contract
checks remain with the project preparation boundary. Their `SKIP` findings do
not claim that those checks passed.

Use these role commands for installation groups such as `python`, `packages`,
`environment` and `identity`. The generic `loom preflight` command checks pipeline
configuration and rejects role-only `--check` groups as unsupported selections.

Filesystem access inspection is not proof of a write. `--probe-io` explicitly
creates, writes, reads, renames and removes a tiny temporary file beneath each
named existing execution root. It never probes a dataset directory, and removes
only its own files. Missing roots and incomplete IO/cleanup are reported as
failures. Initialization owns durable root creation and storage checks.

The agent-level `resources` block supplies the shared inventory and supported
host-limit observations. Missing evidence is shown as `null`; it is not proof of
unlimited capacity. Legacy profile-only capacity remains readable and receives a
warning that host limits and GPU selection were not discovered. Neither resource
enumeration nor an unrequested GPU compute check proves that a kernel ran.

### Optional GPU compute qualification

For an agent that selects GPUs and declares `torch` in its readiness imports or
required distributions, `--probe-gpu` runs a fixed tiny Torch computation on each
selected device, sequentially for each resident profile. It uses that profile's
Python, cwd and explicit environment, plus the active GPU provider's exact device
binding. It does not install Torch or select an environment manager.

Run the command after initialization and before serving:

```sh
loom queue agent-init agent.yaml --env-file agent.env
loom queue agent-check agent.yaml --env-file agent.env --probe-gpu --format json
loom queue agent-serve agent.yaml --env-file agent.env
```

For an embedded local agent, use `daemon-init`, `daemon-check --probe-gpu` and
`daemon-serve` with the coordinator files. During maintenance, settle existing
work and stop the owning service before probing. Draining a running service is
insufficient: it still holds the agent's lock. Checks never start a supervisor,
register an agent, or submit a job to obtain probe ownership.

Only a `PASS` for `resources.gpu_compute` proves that the assigned computation
and cleanup completed. `SKIP` with `busy/deferred` means the agent is running,
has retained work, or its provider declined busy capacity; retry after that condition
is resolved. CPU-only agents and pure coordinators report `inapplicable` without
NVIDIA discovery or Torch imports. An unrequested probe reports `SKIP`. A requested
GPU probe fails if the root is uninitialized, the declared Torch runtime is
absent, readiness/bindings fail, or computation or cleanup fails. A fresh root is
not initialized by checking it. The overall report can remain successful when
GPU compute is skipped; inspect the individual finding when compute qualification
is required.

Both agent setups use their configured providers and NVIDIA occupancy policy.
The explicit probe refreshes occupancy before checking each selected device;
the provider also rechecks during claim preparation. An externally occupied GPU
reports `SKIP` with `external_process_detected`. An unavailable or stale observation,
or a missing selected device, reports `FAIL` with its existing reason code and
does not establish hardware failure. Other selected devices can still qualify.
Default checks do not perform this active occupancy refresh.

Initial busy/unavailable observations create no diagnostic reservation and launch
no computation for that device. A definite refusal during claim preparation
settles its already-recorded reservation before reporting busy versus unavailable.
Uncertain release remains retained even if a later GPU observation appears free.

Unlike default inspection, this explicit probe persists diagnostic ownership in
the existing agent journal when it reserves a device. Findings with a reservation
include a probe ID for correlation. It uses
no coordinator assignment, execution grant, training result, or separate database.

| Last durable fact | Meaning on interruption or restart |
| --- | --- |
| `reserved` | Exact provider claim persisted before activation; retain capacity. |
| `launch_intent` | The child may have started; retain capacity. |
| `contained` | The owned process group is gone, but provider release is not durably complete; retain capacity. |
| `released` | Process containment and provider release both succeeded and completion was persisted; capacity is available. |

A failed computation still releases its claim when containment and provider
release are positively established. Uncertain activation, launch, cleanup or
release leaves the claim held and stops further probes. Rechecking defers;
restart restores the retained claim and suppresses new execution eligibility.
The probe is never automatically replayed. Preserve the journal and compatible
provider/launch binding for verified recovery. A recorded PID, a missing parent,
or elapsed time cannot prove containment after a crash; there is no automatic
PID-based cleanup or force-clear probe command. Successful probes retain their
completion row for ownership inspection.

### Observed software identity and restart

The role loader derives the existing project, environment and executor
fingerprints from actual Python implementation/version/ABI/platform evidence,
declared import/distribution versions and available immutable install origins,
and selected source contents. Old authored software fingerprint fields remain
readable in agent declarations, but their values are replaced by observations.
An agent-check report's `execution.identity` finding includes the portable
`descriptor` under `details.evidence`. The coordinator's `remote_profiles` uses
that complete observed descriptor; the coordinator does not inspect a remote
agent's filesystem. The managed remote example demonstrates this handoff.

Declare source files or directories narrowly. Digests include each root's resolved
project-relative location, relative member names and contents, including untracked
files. They exclude Git metadata, virtualenvs,
bytecode, conventional dataset/cache/run/build directories and symlink members.
An optional `lockfile` (default `uv.lock`) supplies a provenance digest when
present. It does not affect observed identity or prove that all installed
packages match that lock. Absolute source/interpreter paths, hardware UUIDs and
unrelated packages are not portable software identity. Private launch bindings
still prevent moving an initialized profile to a different interpreter or cwd.
This narrow observation does not attest every transitive package, driver,
package tampering or edits made after the observation.

The observation is reused within a role operation. There is no durable readiness
certificate or per-scheduling-cycle import scan. Startup compares the observed
profile to initialized ownership; source/package drift or a changed private
launch binding rejects startup before new offers. A rejected local reload
withholds local candidates while the coordinator continues reconciling retained
work; status reports `resident_profile_unready`. A valid compatible reload can
restore local eligibility. An outbound reload drains availability, and resume
rechecks a configured role loader before restoring offers. Neither rejection
releases claims, changes retained descriptors, nor relaunches old assignments.
Settle retained work using its compatible installation before qualifying a
deliberately changed profile or deployment.

### Status and cancellation

Queue status preserves separately versioned admission/control, authority
lifecycle/cancellation, scheduling/route, assignment/execution, external-
scheduler dispatch/observation, transfer/result, and service-health/freshness
axes. Authority terminal state remains lifecycle
truth; a concise summary is derived rather than last-writer state. This is a
coordinator-built join, not a globally atomic snapshot: every axis carries its
owner revision plus coordinator-accepted receipt/observation time and freshness, and the
top-level `as_of` names the coordinator join boundary. Remote wall clocks are
informational only and never decide ordering, expiry, or freshness. Cancellation
first commits the coordinator request, then installs one canonical authority
cancellation epoch that blocks readiness, bind, grant, descendants, and retry;
only then are exact active-assignment controls fanned out. Status distinguishes
requested, effective, settling, and terminal cancellation. After grant, an exact agent
acknowledgement may prove no start intent/launcher invocation; once start intent
exists without a known outcome, work remains unknown until reconciliation or
containment. Cancellation becomes terminal only after terminal or positive-
containment evidence. The canonical cancellation request contains the complete,
exact plan stage set. Once all physical owners settle, one authority transaction
cancels prepared attempts and never-ready descendants, refuses any live binding,
preserves an already-terminal success/failure winner, and CASes the run to
`CANCELLED`.

A stage's `context.stop_early()` enters this shared run-cancellation path: active
siblings settle, downstream work cannot start, and authority run truth becomes
`CANCELLED`. Ordinary terminal admission waiting includes result settlement and
physical provider release, including when cancellation arrives after a terminal
stage result. Explicit guarded recovery is the exception: its recorded decision
can retain uncertain capacity for operator recovery. A terminal run alone is not
permission to reuse such a retained claim.

The [local starter](../../examples/operations/managed-local-basic/README.md)
demonstrates controlled cancellation followed by reuse of its sole CPU slot.
The [remote operations journey](../../examples/operations/managed-remote-operations/README.md)
demonstrates foreground restart while supervised work remains active.

The old request shape without that stage set is rejected; it is not
filled in or upgraded. Existing whole-run queue rows remain readable and
cancellable. New managed work uses a distinct orchestration state rather than
silently reinterpreting historical `DISPATCHED`.

Native execution retains compact admission/owner, retired-session, idempotency, and event
tombstones needed to reject duplicate or stale operations. It does not add an
independent age-based queue purge that forgets an admitted managed run while
authority or agent safety facts remain. Cross-owner run deletion needs a future
explicit acknowledged run-forget contract.

Historical delegated pools retain their existing boundary: Loom submits a whole
run according to the delegated adapter and the external scheduler owns ordering,
resource placement, and dependency submission.

Native execution separately implements explicit ready-stage delegation inside the
managed-stage run owner. The resolved stage names one protected profile; it has
no agent candidate and never falls back to an agent or another profile. The
coordinator atomically consumes the run concurrency slot and configured profile
admission slot, binds the exact ready `PENDING` attempt, persists one stable
submission operation and `SUBMITTING`, then invokes `sbatch` at most once. An
ambiguous operation stays bound and is reconciled by exact scheduler-visible
identity rather than resubmitted.

The SLURM job starts a restricted Loom bootstrap. A protected profile may select
one Apptainer/Singularity container for that fixed bootstrap. Its image, mounts,
resource projection, redacted command, and bootstrap-config environment name
are bound into the ready request; the config value is supplied only by the job
environment, and the bootstrap capability path must remain writable inside the
container. Missing delivery fails before the bootstrap can start and never falls
back to host execution. Only an authority grant/fence allows one authored root,
and only a fenced Loom result with accessible outputs commits stage terminal
truth. SLURM status and cancellation stay separate owner axes: `COMPLETED` is
not Loom success and `scancel` success is not containment. See
[slurm.md](slurm.md#02-stage-29-managed-scheduler-boundary) for the full
submission/bootstrap contract.

Allocation-fed agents remain a later distinct integration. Such an agent would
publish only an already-granted allocation for its fenced lifetime. Unallocated
nodes are never Loom offers. Native execution does not implement allocation provisioning,
automatic agent/SLURM fallback, multiple-profile ranking, or a generic external-
scheduler backend.

### Recovering an enrolled Linux worker after reboot

For native and Apptainer resident workers, the supervisor records the Linux
machine identity, kernel boot ID, canonical execution root and ownership
generation before launching work. After a reboot, keep the same protected local
agent root, profiles, credentials and session. With the agent stopped, run:

```sh
loom queue agent-recover-reboot /private/agent.yaml \
  --env-file /private/agent.env --operation-id worker-reboot-001
```

Keep the operation ID for a lost-reply replay. The local command takes exclusive
root and supervisor ownership, reads host/boot evidence itself, and durably
reports `contained` or `blocked`. It starts no process, releases no resource
claim and makes no scientific success or retry decision. A successful operation
rotates supervisor ownership while preserving exact historical launch identities;
replaying an old launch can never launch another process.

Start the ordinary `agent-serve` command with that same configuration. Retained
work keeps capacity unavailable while the agent reconciles. For each unresolved
attempt, use `daemon-recover-unknown` with the exact assignment, execution fence,
authority revision and a retained recovery ID. Its containment control consumes
the supervisor's durable receipt. Proven ordinary terminal results retain their
precedence. After the guarded authority close wins, the same agent session
releases its providers, persists release proof, releases the coordinator claim
and settles its retained delivery. Fresh provider observations are required
before capacity returns. Retry or checkpoint resume remains an explicit separate
scientific operation.

A missing supervisor in the same boot, changed host, relocated execution root,
unavailable Linux identity, legacy active state without pre-launch boot evidence,
or missing/corrupt journals cannot establish containment. Preserve those roots
for diagnosis; deleting state or replacing identity is not recovery. Schema 4
opens schema 2/3 supervisor journals without inventing historical boot proof.
This route does not cover SLURM, remote Docker engines, cloned VM snapshots,
state copied between hosts or hostile host attestation. Controlled-boot tests
exercise native settlement; actual host reboot qualification is separate.
