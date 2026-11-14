# Connected SLURM execution

SLURM is an explicit native stage route. The coordinator owns the DAG,
readiness, attempt and output authority; the submit agent owns scheduler
submission and observation. One already-ready attempt is submitted through a
protected profile and restricted bootstrap. No scheduler dependency graph or
whole-pipeline continuation is generated.

## Connected ready-stage execution

The native coordinator owns an explicit ready-stage route. A managed-stage run may resolve
different execution targets per stage, but the coordinator remains the one run
owner:

```text
preprocess -> managed agent
train      -> explicit SLURM profile "training"
evaluate   -> managed agent
```

`managed_agent` remains the default. A SLURM stage names exactly one protected
site-owned profile. No lack of agent capacity, wait, preference, command error,
or scheduler status changes that route or selects another profile. This avoids
silently submitting externally and avoids comparing exact Loom offers with an
unknown SLURM queue delay.

```yaml
runtime:
  stages:
    train:
      placement:
        execution_route:
          kind: slurm
          profile: training
```

This is an intentional hard cut-over for the exact managed-stage route record.
Current records use placement schema v3 and retain `profile_id`, the complete
profile descriptor, and its configuration fingerprint. The earlier provisional
`profile_name`/`profile_fingerprint` shape is rejected rather than translated.
Runs must be prepared again and daemon owner roots must be freshly initialized
when crossing this boundary. Historical whole-run SLURM manifests and the
single-job/`afterok` controllers use different owners and remain unchanged.

Protected deployment composition supplies the concrete profile separately from
authored stage configuration. The built-in bootstrap executes the local worker
inside its allocation. A profile can select an installed environment or an
explicit `submitted_container_policy` for submission-selected Apptainer images:

An optional profile `time` sets Slurm's allocation walltime (for example
`02:30:00`), including bootstrap and result publication. It participates in the
retained profile identity; it is distinct from a scientific training budget.

The optional profile `requeue` selects scheduler requeue eligibility. Omission
or `None` preserves the existing profile identity and emits no directive, leaving
the scheduler default in force. Explicit `false` emits `#SBATCH --no-requeue`;
explicit `true` emits `#SBATCH --requeue`. Only booleans are accepted. A selected
value participates in both profile identity and the retained request/script;
changing it cannot reinterpret a prepared submission or bypass replay checks.
This is distinct from Loom retry decisions and does not establish containment
after node failure or an administrative requeue. A deployment whose cleanup
policy does not support restarted allocations should select `requeue: false`
and still retain UNKNOWN when its required cleanup evidence is unavailable.

Three optional protected fields control batch entry before the bootstrap starts:
`batch_shell` selects an absolute Bash-compatible interpreter (for example
`/bin/bash`), `batch_working_directory` emits `#SBATCH --chdir=...`, and
`batch_output_path` emits `#SBATCH --output=...`. Slurm merges stderr into that
output by default; its filename substitutions such as `%j` remain available.
These paths must be absolute literals without whitespace, control characters,
quotes, backslashes, `#`, or `..` components. The operator must verify the
interpreter and writable directories on compute nodes before selection; Loom
does not create them or expand shell variables. Use an absolute interpreter
when the allocation's initial PATH cannot resolve Bash, including restricted
`--export=NIL` environments. A shared output path retains diagnostics even when
bootstrap registration fails and compute home differs from submit-host home.

Omitting each field (or selecting `None`) preserves its prior fingerprint and
script behavior: `/usr/bin/env bash`, inherited submission working directory,
and Slurm's default output path. Explicit selections enter profile identity;
working-directory/output directives and the shell also bind the retained request
and script. Change them only after retained work settles, through the deployment's
supported protected-profile transition, never by rewriting a pending job's script. These options neither
export caller environment nor change bootstrap credentials or start permits.

```python
from loom.pipeline.executors.slurm import SlurmReadyStageProfile
from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider

profile = SlurmReadyStageProfile(
    profile_id="training",
    partition="gpu",
    max_outstanding=8,
    bootstrap_argv=("loom", "slurm-bootstrap"),
    runner=runner,
    command_adapter_fingerprint="site-slurm-cli-v1",
    bootstrap_principal_id="slurm-training",
    credential_reference="slurm-training-mtls",
    coordinator_endpoint="https://loom.internal",
    project_fingerprint="project-v3",
    environment_fingerprint="environment-v2",
    executor_fingerprint="local-executor-v1",
    job_private_file_provider=SlurmJobPrivateFileProvider(
        fixed_path="/run/loom/capability",
        descriptor="site-prolog-v1",
        helper_argv=("/usr/local/libexec/loom-job-private-file-v1",),
    ),
)
```

The fixed bootstrap reads its protected TLS/workspace configuration from a
private deployment-owned file. Native profile declarations can select absolute
`bootstrap_executable` (the installed `loom` console script) and
`bootstrap_config_path` values. These produce the fixed command
`/site/bin/loom slurm-bootstrap --config /site/private/bootstrap.json`, and both
paths participate in the profile identity. This works with Slurm's clean export
environment. Omitting them keeps the existing `loom slurm-bootstrap` command and
`LOOM_SLURM_BOOTSTRAP_CONFIG` environment selection. The concrete
`job_private_file_v1` provider is selected only by protected site composition:
it invokes the site-owned helper with a strict non-secret JSON request on stdin
and an explicit non-inherited environment. The helper writes one
allocation-private regular capability file via a Slurm prolog or container
runtime and returns a strict non-secret replayable receipt. Loom retains that
receipt and verifier only for the exact assignment/job/bootstrap registration;
it never exports the capability through
the script, `sbatch` environment, arguments, or durable state. Ready-stage
submission uses `--export=NIL` and a protected explicit environment.

The execution-only delivery uses schema v5, including admitted auxiliary project
artifacts and submitted-image bindings. Legacy coordinator execution databases
and the separate agent submission database use `PRAGMA user_version = 3`;
trusted-user coordinator deployments select version 4 as described below.
The protected allocation-private helper request/response envelope remains v2.
Earlier delivery records, helper
envelopes, unversioned databases, and mixed table shapes are rejected before
mutation. After a receipt is retained, Loom installs its exact verifier in the
assignment owner before the submission owner records `SUBMITTING`, then mirrors
submission eligibility before calling `sbatch`. This lets a fast bootstrap
register during the synchronous call without granting any profile-wide
authority. Definite rejection and terminal release remain logical until the
same retained receipt receives an exact replayable helper revoke acknowledgement;
unknown prepare, submit, or start outcomes are not revoked or inferred safe.

### Explicit trusted-user file delivery

Deployments that trust all processes running as the submitting UID can select
`loom.pipeline.executors.slurm.trusted_user.SlurmUserPrivateFileProvider` through
the existing `job_private_file_provider` field:

```yaml
job_private_file_provider:
  _target_: loom.pipeline.executors.slurm.trusted_user.SlurmUserPrivateFileProvider
  root: /persistent/private/bootstrap-credentials
  descriptor: trusted-user-files-v1
  ttl_seconds: 604800
```

This is `user_private_file_v1`, not allocation-private isolation. The provider
root must have the same absolute path on submit and compute hosts. The current
mode supports native bootstrap, including submitted-image execution, and refuses
fixed bootstrap containers. The existing helper-backed provider and its profile
fingerprints are unchanged when this mode is absent.

Construction creates no files. Preparation creates private mode-0700 directories
and mode-0600 files, refuses symlink paths, and locks a stable per-operation file.
An operation's SHA-256 selects its directory; its request digest is retained in
the receipt. Concurrent or response-loss replays return the same receipt.
The raw 32-byte secret is stored only in `capability`; returned/persisted receipts
carry its verifier. A consumed token is never regenerated. Revocation publishes
a synchronized tombstone before unlinking the token; replays finish that same
revocation. Lock files, receipts and tombstones have no automatic garbage
collection while operations may be replayed. Interrupted unpublished staging may
remain after an uncatchable process kill; it must not be treated as published work.

The new protected bootstrap JSON retains its existing TLS, workspace and profile
fields, replaces `capability_file_path` with the following declaration, and uses
strict file durability:

```json
{
  "schema_version": 1,
  "credential_delivery": {
    "kind": "user_private_file_v1",
    "root": "/persistent/private/bootstrap-credentials",
    "descriptor": "trusted-user-files-v1"
  },
  "durable_files": "strict"
}
```

This is a fragment, not a complete configuration. Mixed, unknown or unversioned
new-mode declarations fail. Legacy unversioned fixed-path bootstrap documents
remain accepted; they can explicitly select `durable_files: strict` without
changing credential delivery. Strict mode covers incarnation, deadline,
diagnostic and registration/delivery publication, plus capability unlink
synchronization. It acknowledges no failed fsync as success. A replay after an
uncertain publication preserves the original identity and re-establishes sync.

The coordinator persists the new credential kind and expiry. First registration
checks expiry against coordinator accepted time in the consumption transaction;
the worker clock is not authoritative. Exact already-consumed registration replay
remains valid after expiry, but changed request/token/job/incarnation bindings
still fail. Expiry does not establish containment or release a reservation.

Fresh coordinators selecting trusted-user delivery or an explicit
`slurm_admission` policy use execution schema 4 for credential metadata
and validated GPU quantity on assignments. The submission projection and
assignment store share this database and must initialize/reopen the same version.
The separate agent submission database remains version 3. Submission JSON also
remains version 3 unless operation-name accounting is selected, which uses the
version-4 receipt described below.
Old-mode fresh coordinators retain execution schema 3. Startup and scheduling
reload never convert schemas; selecting a different execution schema requires a
stopped-owner migration. The migration/operator installation path is still being
implemented; do not upgrade retained owners by editing `user_version` manually.

File privacy and successful software tests do not qualify shared-storage locking,
server durability, an actual scheduler or container execution. A site must test
its selected root and restart/result-recovery path before enabling submission.

## Optional GPU reservation budget and submission pacing

Coordinator role schema 3 accepts an optional aggregate whole-GPU ceiling:

```yaml
slurm_admission:
  max_reserved_gpus: 8
```

The existing assignment reservation transaction checks the sum of requested
GPUs on all unreleased Slurm assignments, across profiles and runs. It derives
each quantity from the same validated resource request used for Slurm mapping.
CPU-only work reserves zero. Pending, unknown, cancelling and terminal-but-not-
released assignments keep their quantity; scheduler absence and credential
expiry do not free it. Exact replay never reserves twice, and reopening reads
the same rows rather than reconstructing a separate counter. This limit covers
this coordinator's admitted Slurm work, not unrelated jobs or other coordinators.

Fresh runnable requests larger than the entire budget are rejected before
admission. A temporarily full budget leaves work waiting with
`slurm_gpu_capacity_reserved`. The profile can select `max_outstanding: null`
to remove its job-count cap; existing positive integer caps and their profile
identities remain unchanged. Run parallelism, per-job resources and finite
result retention still apply independently. Admission diagnostics distinguish
GPU reservations, profile counts and run counts from unavailable routes.

The budget participates in active scheduling identity. A scheduling reload
cannot lower it below the current reserved quantity. Already admitted,
unreserved work made oversized by a reduction waits with
`slurm_gpu_request_exceeds_budget` rather than becoming a failed scientific
execution. An explicit `max_reserved_gpus: null` disables the ceiling while
retaining schema 4. Omitting the entire policy preserves legacy schema selection
and fingerprints; removing it must not be used to downgrade a v4 owner.
Protected service reload reuses existing Slurm profile instances when their
declarations and source binding are unchanged. Changing a budget therefore does
not reinterpret retained profiles. Changed profile declarations are constructed
normally and remain subject to retained-identity checks.
Historical Slurm acceptance receipts remain available after native assignment
release. They no longer retain the old execution profile once the corresponding
assignment is fully `released`, including across coordinator restarts. An absent
assignment or any earlier release state still retains that profile; a terminal
scheduler observation alone does not authorize profile retirement.

Admission reconciliation reuses decoded retained intent in a bounded in-memory
cache. Every lookup still reads and hashes the run metadata, plan, exact runtime,
resolved snapshot, composition manifest and optional prepared-run metadata.
Changed bytes or missing documents require normal validation again; file sizes
and modification times alone never authorize reuse. Current profile permissions,
local preparation bindings and admission authority remain checked. The cache is
discarded on restart and retains at most 32 entries representing at most 256 MiB
of source documents. It changes neither accepted execution policy nor scientific
identity, and supplies no authority to dispatch or release an assignment.

Producer reconciliation opens one authority handle per run and pass, rather
than repeating run and audit-history initialization for each producer. It does
not cache lifecycle snapshots: each operation reads current durable state, and
the next pass opens the configured authority again. Preparation verification
uses each workspace's primary input paths, including isolated resident payloads;
Slurm's native relay layout and shared-root resolution remain unchanged.

Worker construction also reuses a bounded, process-local projection of checked
project contracts, shared by resident and Slurm routes. Each lookup reads and
hashes the primary report, every referenced composition companion and the
resolved configuration, and rechecks the prepared report reference/namespace.
Only unchanged evidence can reuse a projection; the requested stage declaration
is still checked on every call. Projections are capped at 32 entries and 8 MiB,
returned as independent mutable values, and discarded on restart. Whole reports
and composed configurations are not retained by this cache. Missing or changed
evidence cannot bypass the normal report validation, and no cached projection
authorizes reservation, release or an expired agent offer.

An outbound submit-agent declaration independently accepts:

```yaml
slurm_submit_interval_seconds: 1.0
```

This finite positive interval spaces fresh `sbatch` calls using the agent's
monotonic clock. A paced operation stays at INTENT, without sleeping in a database
transaction or blocking due observations and cancellation. The clock is sampled
after the existing durable SUBMITTING acknowledgement, at the call boundary.
Restart may allow one fresh call immediately; retained SUBMITTING/UNKNOWN work
still reconciles instead of issuing a second automatic call. The setting belongs
to active agent identity and uses the existing settled-work reload rules. Omitted
pacing keeps existing behavior and fingerprints. Each agent owns its own pacing;
this is not a distributed submission-rate limit.

Select independent observation/retry timing on the outbound agent with:

```yaml
slurm_observation_policy:
  failure_backoff_cap_seconds: 300
```

The finite positive cap is at most 3600 seconds and must be at least every
selected profile's `poll_interval_seconds`. Normal cadence continues to use that
profile setting. Each operation has separate monotonic deadlines for observation,
cancellation and containment. Failure delays increase from one normal interval,
doubling up to the cap: at a 30-second interval, 30/60/120/240/300 seconds. A healthy
observation resets its failure count, including an empty selected-name accounting
response; empty history still leaves execution unresolved. Legacy observations
that expose only `unavailable` cannot distinguish empty from failed queries and
back off conservatively. Inconclusive containment checks also back off.

An available fenced result is delivered before a due scheduler observation and
while observations are deferred, including while drained. Result acceptance does
not release an assignment without the existing containment/revocation protocol.
The first cancellation with a known handle proceeds independently of observation
backoff; repeated unsuccessful attempts respect their own deadline. Selected-name
cancellation still obtains fresh exact accounting identity. Reconciliation and
cancellation that already queried history do not immediately repeat ordinary
observation in that same step. Release/recovery requests no longer bypass retry
timing on every task cycle.

Retry deadlines are transient, not a new persistent job state. Restart permits
one immediate observation/cancellation retry; the retained submission journal
still forbids another automatic `sbatch`. A retained release proof is replayed
and acknowledged before finishing revocation, without needing a new helper
query. Timers are removed after acknowledged release. The option changes active
agent configuration only, follows existing settled-work reload rules, and leaves
legacy semantics/fingerprints unchanged when omitted. Its Python value is
`loom.queue._slurm_observation.SlurmObservationPolicy`.

The cap-only selection controls per-operation retry frequency and delivery
ordering. Select all three additional fields to batch ordinary accounting through
the actual outbound-agent cycle:

```yaml
slurm_observation_policy:
  failure_backoff_cap_seconds: 300
  max_jobs_per_query: 8
  max_queries_per_cycle: 4
  cycle_budget_seconds: 10
```

Batching requires bounded command policy and named-accounting support on every
selected Slurm profile. Custom runners can opt into `discover_named_operations`;
the base runner protocol is unchanged. The agent delivers available authorized
results across its task page before fresh submissions or ordinary queries, then
rotates fairly through due operations. Compatible operations share a query within
one protected profile; each still validates its own full name, UID, cluster,
submission window and retained accounting incarnation. Unknown outcomes never
authorize another submission. Results are not containment evidence.

Each query receives the smaller of its command timeout and the remaining
monotonic cycle budget. Unqueried operations remain due. The call/time budget
covers ordinary accounting, not submission, cancellation, helper effects,
filesystem IO or HTTP. Cancellation keeps its independent fresh identity check.
Oversized capture is unavailable evidence and reduces later batch sizes down to
one operation; a still-oversized singleton stays unresolved. Malformed or
unattributable rows cannot become a false empty observation. Fairness, batch
sizes and retry timers are transient; durable operation and outbox state survive
restart. Omitted batching fields preserve cap-only encoding and behavior.

Repeated assignment reads reuse validation of immutable delivery documents by
their complete stored JSON contents. The process-local cache holds at most 128
documents of at most 256 KiB each; larger documents are validated without
caching. This bounds retained source text to 32 MiB, excluding decoded-object
overhead. Assignment state, execution fences, reports and release evidence are
still read afresh. Changed bytes, eviction and process restart require validation
again; the cache does not authorize submission or release.

Dispatch checks for an available submit agent before preparing or validating a
ready worker. Missing or expired offers defer that work, avoiding repeated
preparation-report IO while the agent reconnects. The coordinator checks agent
availability again after worker validation and before reservation; the early
check does not authorize submission or bypass the worker contract.

Draining an outbound agent holds unsubmitted INTENT operations without calling
`sbatch`. Existing jobs still progress through observation, cancellation, result
replay and release, including during startup recovery. Cancellation of a held
intent closes it as a definite non-submission. Resume may proceed when the only
retained work consists of acknowledged, unsubmitted intents under unchanged
bindings. The outbound service can also resume with known queued/running jobs
after the authenticated current session/epoch has redelivered their exact tasks,
their retained job handles and protected profiles agree, and their effects are
acknowledged. Startup publishes its session after this ownership reconciliation;
it does not wait for these allocations to exit. A startup hold still requires an
explicit resume naming that hold. Missing journals, uncertain submissions,
unacknowledged effects and an acknowledged release still awaiting local provider
retirement block admission recovery. A known job awaiting a containment proof
does not block unrelated admission: its exact current task and acknowledged
submission establish ownership, while its reservation remains held until the
ordinary release protocol completes.
Task confirmations are transient and must be reacquired after process/session/
epoch changes; they never release a GPU reservation. All these jobs remain
retained work for reload and retirement and keep their original assignments and
requests. Direct clients retain the stricter started-work resume restriction.

The profile, not authored stage data, supplies allowlisted account/partition/
QoS, resource/directive mappings, submission limits, resident bootstrap
environment, command adapter, credential delivery, data path, reconciliation,
and retention behavior. Authored data cannot inject raw `SBATCH` directives,
commands, preludes, submit hosts, or credentials.

For submitted workloads, `submitted_container_policy` uses the same protected
policy codec as managed container agents. It declares the runtime command,
allowed image roots, qualified shared roots, captured-input roots and authorized
mounts; it contains no selected image. The coordinator checks each Slurm stage's
submitted requirement against that policy before creating its prepared run.
The policy is part of the Slurm profile fingerprint and cannot be combined with
the older fixed `container_options` selection.

The native bootstrap authenticates and consumes the allocation's single start
permit before launching the submitted image. It retains the exact delivery,
image binding, policy and execution fence in its private assignment workspace.
Coordinator shared-input inspection runs in a dedicated bounded pool before
Slurm assignment reservation. A slow scan does not reserve a GPU. The current
implementation admits two inspections concurrently and retains at most eight
pending/completed requests; superseded running work keeps its slot until it
exits. Existing launch-boundary checks still inspect mutable inputs afresh.
Request preparation, artifact hashing and retry predecessor closure inspection
use a separate bounded preparation pool. Recovery binding rechecks current
predecessor ownership and cleanup reservations before consuming inspected
closure evidence; content verification runs outside coordinator locks and
database transactions. Publication and resource release use separate workers.
The outbound service drives scheduler reconciliation in a dedicated single-worker
lane. Its durable outbox acknowledgements return to the service owner thread in
order, while control receipts and offer renewal can progress during scheduler
IO. Profile/control effects retain their existing scheduler-boundary ordering;
there is no second submission writer. Closing the acknowledgement bridge rejects
pending callbacks rather than leaving a worker waiting on a stopped owner.

Exact admission detail includes `owners.input_validation`, a process-local
observation containing stage/work identity, waiting reason, entries examined,
elapsed seconds and the last progress timestamp. It has no percentage or input
paths and is not durable launch authority. Invalid inputs and unavailable storage
have distinct reasons and paced retries, permitting inputs to be repaired in
place. A finished worker reports `input_validation_complete` (or its failure
reason) even if an unavailable route prevents another dispatch poll. Completion
does not mean submission is authorized: current ownership and placement still
require scheduling checks. Cancellation invalidates launch authorization immediately; stopping a
scan is cooperative between filesystem operations. A thread blocked in kernel
IO cannot be force-cancelled, and process exit may still wait for it. Restart
repeats inspection under the existing attempt and submission identities.

Image bytes and selected shared inputs are verified before a new launch. The
contained worker consumes those bindings without importing project code on the
bootstrap host. CPU, memory and walltime remain delegated to Slurm; GPU work
requires matching allocation-provided `CUDA_VISIBLE_DEVICES`. The container
uses a clean environment and mounts only its authorized inputs and writable
assignment paths. Bootstrap configuration and credentials are not mounted into
the workload.

Submitted preparation profiles can set
`execution_route: {kind: slurm, profile: hpc-cpu}` to run configuration composition
and scientific inspection inside a CPU allocation. This protected selection is
retained with the preparation operation; scientific stages retain their own
explicit routes. A Slurm-only deployment must configure this route instead of
relying on an available managed worker. Image building is separate from this
execution path: a verified prebuilt SIF can be installed without build privileges.

SLURM is a target, not a Loom resource pool. Unallocated cluster nodes are not
agent offers and a pending SLURM job holds no agent claim. Route feasibility
means the named profile can map every canonical hard requirement without
weakening it and is operationally admitted. SLURM still chooses the node and
enforces the submitted resource request. Unsupported VRAM, model, topology,
custom-resource, agent-target, or artifact semantics reject that route with a
safe reason; they are never silently omitted.

The assignment retains distinct identities:

```text
run / stage attempt / stage work
  -> tagged SLURM assignment target
  -> stable submission operation
  -> SLURM cluster/job handle
  -> bootstrap incarnation
  -> process execution ID + authority fence
```

It consumes the run's `max_parallel_stages` slot, any configured profile count
slot and any selected GPU quantity budget, but no resident-agent capacity. Submission uses a deliberate
at-most-one automatic invocation boundary:

```text
exact authority attempt PENDING and ready
  -> reserve assignment/run/profile slot
  -> bind exact attempt (still PENDING)
  -> prepare immutable request/script/input-access evidence
  -> persist SUBMISSION_INTENT
  -> persist SUBMITTING
  -> invoke sbatch at most once
  -> ACCEPTED(job_id) | DEFINITELY_REJECTED | OUTCOME_UNKNOWN
```

Loom cannot commit SQLite and call `sbatch` atomically. Therefore any crash,
timeout, interruption, unusable success output, or failure to durably retain a
returned handle after `SUBMITTING` is unknown and never automatically calls
`sbatch` again. The stable operation ID is placed in bounded scheduler-visible
metadata. Exactly one discovered match repairs the handle, zero unproven
matches remain unknown, and multiple matches are a conflict. This can sacrifice
liveness when the command was never actually invoked, but it prevents a blind
duplicate job.

Select bounded scheduler commands explicitly on a protected profile's runner:

```yaml
runner:
  _target_: loom.pipeline.executors.slurm.SubprocessSlurmCommandRunner
  command_policy:
    observation_timeout_seconds: 10
    submission_timeout_seconds: 60
    cancellation_timeout_seconds: 10
```

All three deadlines are required finite positive seconds, at most 3600 each.
They apply to `squeue`/`sacct` (including discovery), `sbatch`, and `scancel`,
respectively. The optional Python value is
`loom.pipeline.executors.slurm.commands.SlurmCommandPolicy`. Its normalized
values bind the ready-stage profile fingerprint. Omission preserves the legacy
runner behavior and profile fingerprint; do not select a new policy underneath
retained work that requires the old profile identity.

Bounded mode requires POSIX process groups. On timeout or interruption it kills
the owned command group and reaps the command, including wrappers whose children
keep output pipes open. This bounds ordinary subprocess work, not an
uninterruptible kernel/storage stall. Stdout and stderr are each limited during
capture to 4096 decoded characters; overflow stops the command group and rejects
the response as unavailable evidence rather than buffering unbounded output or
accepting truncation. A selected `sbatch` timeout has
`slurm_submit_timeout` evidence; an unclassified nonzero exit has
`slurm_submit_command_failed` evidence. Both remain UNKNOWN and reconcile without
a second automatic call. A selected `scancel` timeout/nonzero exit records
`slurm_cancel_timeout`/`slurm_cancel_unknown` and does not claim cancellation was
requested successfully. Neither a successful cancellation command nor an
observation is containment evidence.

The real and fake runners also accept an optional explicit `client_environment`:

```yaml
runner:
  _target_: loom.pipeline.executors.slurm.SubprocessSlurmCommandRunner
  client_environment:
    PATH: /site/slurm/bin:/usr/bin:/bin
    TMPDIR: /site/scratch/temporary
    TMP: /site/scratch/temporary
    TEMP: /site/scratch/temporary
    LC_ALL: C
```

This can be combined with `command_policy`. It replaces parent-shell inheritance
for every scheduler command and selects executable lookup in both preflight and
execution. `PATH` is required; all path entries must be absolute, without empty
entries or `..`. Optional keys are `TMPDIR`, `TMP`, `TEMP`, `LC_ALL`, `LANG`, `TZ`
and `LD_LIBRARY_PATH`; values must be nonempty literal text without control
characters. Constructors validate/freeze declarations without inspecting paths
or creating directories. Qualify executable/library/temp access at deployment.
No unlisted variables are accepted, including scheduler option overrides,
proxies, Python injection and `LD_PRELOAD`. These settings are non-secret and
bind the ready-stage profile fingerprint only when selected.

The selected environment is for the scheduler **client process**. `sbatch` still
uses `--export=NIL`, including when its per-call `environment` argument is omitted.
In this mode that argument must be omitted or empty; a nonempty override fails
before invoking a command. Bootstrap/workload setup is separately configured.
All selected accounting calls force `TZ=UTC` and
`SLURM_TIME_FORMAT=%Y-%m-%dT%H:%M:%S` for consistent parsing. Omission of
`client_environment` preserves existing lookup, environment/export behavior and
fingerprints. This is an application environment policy, not an OS egress
restriction. The fake runner records effective selected environments in
`client_environments`, in `calls` order (`None` for unselected mode), while its
existing `environments` list retains the original sbatch arguments.

Command deadlines alone do not change historical matching: omitted history
policy preserves the existing comment-based discovery. A site can explicitly
select operation-name accounting on the profile, alongside bounded commands:

```yaml
cluster: example-cluster
accounting_history:
  user_id: 1000
  clock_skew_seconds: 60
```

Use the actual submitting UID and one explicit cluster. The optional Python
policy is `loom.pipeline.executors.slurm.history.SlurmHistoryPolicy`. Its values
bind the profile fingerprint only when selected. It requires a command policy
and runner methods `discover_named_operation` and `scancel_named_operation`;
the built-in real/fake runners implement them. Existing runner implementations
remain usable with unselected history policy.

Mapping adds `--job-name=loom-<sha256(operation_id)>` and the selected cluster to
the retained script/directives. Accounting uses explicit name/UID/cluster/time
filters, `--duplicates`, allocation rows and adequate field widths. The runner
fixes TZ and SLURM_TIME_FORMAT to UTC. Its lower bound is original intent creation
minus the configured skew, not an invented actual-call timestamp. The upper
bound advances with each observation plus the skew. This permits later controller
acceptance/accounting after a client timeout; no empty query proves rejection.

A unique complete row must match the full name, UID, cluster and submission
interval and include DBIndex and SLUID. Missing, truncated, contradictory or
multiple rows remain unresolved, even when multiple incarnations share a numeric
job ID. The selected mode may wait for accounting while a job is live; it never
falls back to a weaker name prefix or comment-only match. Ordinary scheduler
status observation also uses this exact accounting binding. Accounting delay or
an incarnation mismatch yields unavailable evidence and keeps capacity held.

Selected submissions use receipt schema 4 with a retained `accounting_identity`;
legacy submissions keep the exact schema-3 shape. This is independent of the
SQLite database schema: existing agent journal tables remain version 3, and
the coordinator's assignment/projection version is selected separately. New
code reads both receipt versions; old code cannot interpret selected receipts.
First activation requires drained work and coherent compatible installations.

Before cancellation, selected mode obtains matching current accounting evidence.
It then constrains `scancel` by job ID, operation name, UID and cluster. A reused
ID or unavailable identity causes no cancellation call. Ordinary release and
guarded-recovery helper requests include the retained accounting identity; the
native helper boundary refuses positive evidence without its exact operation,
UID, cluster and job binding. A valid accounting row alone is not proof of step
cleanup or containment. The site helper and actual cancellation/cleanup behavior
still require physical qualification. Job requeue or operator changes that alter
the retained incarnation remain unresolved for explicit recovery.

The selected scheduler client environment must also supply
site libraries and permitted temporary paths; `--export=NIL` controls job
environment propagation, not the command's filesystem or network behavior.

After a long coordinator outage, retain the accepted-time guard. An authorized
local operator can use the existing revision/epoch-bound time recovery operation
after verifying the clock. A result from an already granted Slurm execution can
replay across restart and time-recovery epochs; recovery does not issue another
start permit or scheduler submission. Workers without a start permit cannot
begin authored work while the coordinator is unavailable.

The generated job does not immediately run authored stage code. It starts a
fixed restricted Loom bootstrap:

```text
SLURM starts bootstrap
  -> authenticate assignment/submission/job/incarnation
  -> reconcile the exact handle
  -> stage and verify request + inputs
  -> request the exact authority grant
  -> authority changes PENDING -> SUBMITTED and creates the fence
  -> record grant/start intent
  -> invoke at most one execution-only stage-worker root
  -> durably publish outputs, report and manifest last
  -> exit; original submit agent relays the retained exact-fence result
```

Bootstrap identity is assignment-scoped and least-privilege. It is not an agent:
it publishes no offer, receives no arbitrary work, owns no durable agent
session, and has no direct authority credential. Secret bytes must not appear in
the generated script, arguments, scheduler metadata, logs, or authored worker
environment. Duplicate or scheduler-requeued bootstrap incarnations reconcile
the same assignment but cannot obtain a second start permit. Transparent requeue
or checkpoint resume is not claimed.

Lifecycle and observation remain separate:

```text
authority lifecycle | Loom dispatch | SLURM observation
bootstrap/process    | transfer/result | cancellation/control
```

SLURM `COMPLETED` alone is not Loom success. Success requires an authenticated
current-fence Loom result and verified coordinator/backend-accessible outputs
committed by the authority. Missing `squeue`/`sacct` evidence is unknown. A
successful `scancel` call means only cancellation requested. Run cancellation
first installs the authority cancellation epoch so an ungranted bootstrap
cannot start, then fans out exact Loom and SLURM controls. Manual close/retry of
unknown work requires positive containment tied to the exact profile,
submission, job, bootstrap, and fence; queue absence, timeout, or operator text
is insufficient.

Coordinator startup does not require SLURM to be up. An unavailable named
profile leaves explicitly routed work visibly pending/blocked. Restart reopens
known and unknown submission records, retains the exact profile descriptor,
inspects/reconciles the same stable operation, and never resubmits. A bootstrap
that starts while the coordinator is unavailable waits with no authored effects
until it can obtain the grant. Granted work may continue through coordinator
loss and later replay its result within the profile's bounded retention model.

The protected containment helper can opt into bounded communication:

```yaml
containment_helper:
  _target_: loom.pipeline.executors.slurm.ready_stage.SlurmContainmentHelper
  descriptor: site-qualified-cleanup-v1
  argv: [/site/python, /site/containment-helper.py]
  timeout_seconds: 30
  process_policy: bounded-v1
```

Selected mode requires a finite timeout in (0, 3600] seconds. It delivers JSON
stdin and captures stdout/stderr concurrently under that one monotonic deadline,
with a 16384-byte bound on each output stream. A request already larger than
that cannot fit in the required response echo and is refused before launch.
Timeout, overflow, nonzero exit or malformed output is unavailable evidence,
never positive containment. Timeout, overflow or communication failure kills
the owned POSIX process group and reaps the helper leader, including when the
leader exited before its children closed inherited pipes. This does not bound
kernel-uninterruptible IO or contain
descendants that deliberately create another session. The trusted helper must
keep any nested commands bounded within its outer budget; configured timeout
ordering must leave room for their cleanup.

The helper inherits the service environment, including the deployment's explicit
scratch settings. Bounded mode does not choose a filesystem or qualify the site
predicate. Its selected policy is part of the retained profile fingerprint;
omission preserves the previous helper behavior and identity. Normal/inert
native profile composition accepts the same selection without launching it.

### Durable ready-stage results

The authenticated Slurm registration reply carries a versioned stage delivery.
Its fingerprint, resolved runtime and worker metadata each have a separate
64-level JSON depth budget and accept finite plain-data scalars. This accommodates
nested authored factory configurations, which exceed shallow control objects. The HTTP
and registration wrappers do not consume those semantic budgets. The complete
reply still has the 65,536-byte limit, collections remain bounded to 64 entries,
and control fields retain their original eight-level depth and scalar restrictions. This
decoder selection applies only to the Slurm bootstrap registration response;
the native delivery decoder still checks schema, identities and shared scope.
Input artifact metadata also accepts finite plain-data scalars, such as a
checkpoint's selection metric. Its existing envelope depth and collection
bounds remain unchanged, and descriptor identity fields remain strict.
An indeterminate reply must replay the same registration, never create a new
allocation or regenerate its consumed credential.
The bootstrap converts the transport's recursively immutable response to plain
JSON data before retaining registration or publishing the result identity. This
preserves the response values and exact replay bytes; it does not change the wire
schema or permit a second execution.

Every executable protected profile requires `result_storage`:

```python
result_storage = {
    "agent_root": "/site/shared/loom-results",
    "compute_root": "/compute/shared/loom-results",
    "retention_bytes": 1024 * 1024 * 1024,
}
```

Both paths must denote the same existing private durable directory. Different
mount prefixes are explicit; no project/output-directory scan or fallback is
performed. The entire binding and finite quota participate in the protected
profile fingerprint. A changed binding requires new prepared work. The submit
agent reserves 65 MiB per attempt before submission (64 MiB aggregate artifact
limit plus bounded report/manifest overhead). Quota exhaustion retains existing
attempts and blocks new submission; it never evicts unacknowledged output.
Submitted workloads with an admitted shared-publication root retain checkpoints
and prediction trees directly on that storage, under its explicit payload,
member-count and manifest budgets. These payloads do not cross the 64 MiB byte
relay. Their authenticated report carries the publication references; the
coordinator verifies the complete closure and rechecks execution authority before
publishing it. Downstream Slurm workers resolve the same references through their
qualified roots. The result journal never copies or deletes those artifact trees.
Worker scratch space is separate and is not the durable transport.

Submitted Slurm assignments with a shared-publication root also receive the
native assignment-owned recovery binding. The delivery carries only qualified
root/tree identities; the worker resolves the current writable directory and
immutable predecessor directories inside its execution namespace. Preparation
deliveries and older deliveries without that binding retain their behavior.
Never substitute a coordinator run-state path inside a remote worker.

After the agent supplies exact positive provider-release evidence, the
coordinator seals recovery progress and retains its reference before releasing
the assignment. An interrupted seal replays from the same retained delivery and
fence. A subsequent explicit retry can select only earlier started, failed or
result-less attempts that have been positively released and sealed. Resident
and Slurm history use the same ownership and closure checks; live progress,
changed bytes and recovery reserved for cleanup cannot be selected. Application
code still decides which checkpoint is scientifically eligible.
The saved worker request is reused only for the same attempt. When authority
admits the immediate successor of a failed attempt, Slurm prepares a new worker
request using the same guard as resident dispatch; it does not relaunch the
earlier request or reinterpret an unrelated request as the retry.

Recovery preview and operator cleanup include Slurm attempts and authorize the
assignment's recorded agent. The existing complete-output, published-log,
containment and dependent-attempt requirements still apply. A successful Slurm
wrapper exit alone neither seals recovery nor authorizes its deletion. Upgrading
this worker behavior requires a matching workload image; a host-only upgrade
cannot add the binding to an older image's worker.

The bootstrap writes relayed output files and report version 6, fsyncs them,
and atomically publishes manifest version 1 last. The manifest binds the stable
coordinator, original agent/root, assignment, attempt, execution fence, bootstrap
incarnation and submission operation, with paths, digests and byte counts. A
compute process can exit while the coordinator is unavailable. After same-root
restart the original submit agent verifies only that bound location and relays
through the existing authenticated result/finalization path. Old session tokens
are not required. Result identity comparison normalizes immutable protocol
views and retained JSON to the same plain values; JSON arrays and their frozen
tuple representation do not change identity. Outgoing report, output and commit
requests convert that identity recursively back to JSON values, including a
commit replay after retained-byte cleanup. Every identity field still matches
exactly. Partial, stale, linked or corrupt evidence cannot commit and
remains with a bounded `delivery-failure.json` diagnostic in the transport root.
A worker result exceeding the existing transport bounds also records a retained
delivery failure; it does not become success.

Output acknowledgements report the cumulative stored byte position. After a
lost response, the agent advances to that bounded position, including when the
coordinator already has a complete output. An upload acknowledgement alone does
not commit the result or permit transport cleanup.

The authority alone validates the accepted fence and exact admitted output
predecessor and performs commit/replay. Losing its acknowledgement leaves shared
bytes for replay of the same commit. Cleanup follows final acknowledgement;
bootstrap/client exit never cleans transport evidence. If acknowledged cleanup
is interrupted after deleting some files, the agent obtains the same authority
commit/replay acknowledgement again using the coordinator's retained result
before finishing cleanup. A published result racing
with cancellation does not obstruct the existing containment path: retirement
waits for the acknowledged terminal cancellation/rejection disposition, including
replay after a lost rejection acknowledgement. Scheduler observation,
result publication, authority acceptance and execution containment remain
separate facts. Missing accounting is unknown. Unresolved assignments/delivery
retain service lifetime, and accepted output alone does not release capacity.

A qualified site must permit services on the selected submit host, provide a
reachable grant endpoint and an installed worker environment, and qualify
shared-root visibility, fsync, atomic rename and advisory locking across both
mounts after compute exit. Shared artifacts do not qualify role SQLite storage.
Role journals remain on their separately qualified roots; journal loss, copying
role databases to another host and transparent failover are unsupported.
Native Slurm workers are baseline. Container claims additionally require the
selected runtime and a writable binding of the compute result root. An already
granted allocation needs separately qualified native/container resource and
`srun` step binding; this feature does not discover allocations, provision them
or nest `sbatch` automatically.

Local tests use a fake scheduler plus a real compute process that exits during
coordinator loss; these fixtures do not qualify a physical site. The opt-in
qualification owner is `tests/slurm_acceptance/test_slurm_result_recovery.py`.
The site operator archives the public run/inspect, outage, scheduler, shared
publication, commit/replay and cleanup/containment evidence using approved site
service controls, then supplies `LOOM_SLURM_RESULT_QUALIFICATION_RECEIPT` to audit
that receipt with `LOOM_RUN_SLURM_ACCEPTANCE=1`. The test states the receipt fields
and requires nonempty evidence artifacts; it is an audit, not an automated live
journey runner. Missing site access or receipt remains an explicit qualification
gap. No physical Slurm/shared-filesystem/container qualification is claimed without
its site receipt. The legacy single-job/afterok acceptance suite does not prove
this result-recovery journey.

Current `SlurmCommandRunner`, resource/directive mapping, deterministic script,
job-ID parsing, `squeue`/`sacct`, and `scancel` seams are reused where their
semantics fit. Historical whole-run manifests remain read-only records.

Allocation-fed agents remain a later, distinct integration:

Allocation-fed agents would first obtain a bounded SLURM allocation, then start
a Loom agent inside it:

```text
SLURM grants allocation
  -> allocation-bound Loom credential/session starts
  -> agent publishes only resources granted to that allocation
  -> The native coordinator schedules one-agent stages inside the allocation
  -> agent reconciles/retires before allocation release
```

This is a possible later route when already-granted SLURM capacity should
join the managed pool. It needs allocation-bound ephemeral identity, lifetime/
expiry and clean-retirement behavior, exact prevention of double publication,
and a decision about multi-node distributed stages. SLURM remains authoritative
for the enclosing allocation; Loom owns only the exact capacity handed to its
agent provider. A physical resource must never be advertised simultaneously by
a standalone Loom agent and through a SLURM allocation.

The native coordinator does not implement allocation-fed agents, automatic allocation
provisioning, automatic managed-agent/SLURM fallback, multiple-profile ranking,
or a generic external-scheduler plugin. Those capabilities are not implied by
`ResourcePlanner`, `SchedulingPolicy`, the ready-stage route.


Existing coordinator assignment stores require the complete current schema,
including agent acknowledgement evidence, even when they contain no assignments.
Older column layouts and incomplete tables are refused before repair or mutation.
Initialize fresh current owner storage after settling work through its original
installation; there is no schema conversion. Current interrupted SQLite writes
still recover normally, and inspection leaves original database/journal bytes
unchanged.

## Operator lifecycle

Detach and reconnect through the native client without changing admission
identity. Cancellation records a native operation and requests scheduler stop;
settlement still needs terminal scheduler and retained result evidence.
Missing accounting remains unknown, not successful or retryable by inference.
When a job finishes during an outage, the original submit agent/root retains
and relays its exact-fence result after reconnect. Restart with the same root;
never reset a submission record to force another `sbatch`.

A connected mixed deployment can execute independent admissions and stage
routes while preserving one readiness and output owner. Select a route
explicitly; no automatic fleet/SLURM fallback or allocation provisioning exists.
Allocation-native agents remain deferred and unqualified.

Settle all old-version jobs before cutover. Preserve historical manifests and
outputs for read-only inspection. Old generated whole-run continuation commands
and the old scheduler-status/cancel CLI are removed. Native admission detail
reports retained scheduler observations; inspection does not contact SLURM or
rewrite a scheduler snapshot.

See [example coverage](slurm-example-coverage.md) for synthetic versus physical
qualification. No example run or local test establishes a live site result.
