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
Current records use placement schema v2 and retain `profile_id`, the complete
profile descriptor, and its configuration fingerprint. The earlier provisional
`profile_name`/`profile_fingerprint` shape is rejected rather than translated.
Runs must be prepared again and daemon owner roots must be freshly initialized
when crossing this boundary. Historical whole-run SLURM manifests and the
single-job/`afterok` controllers use different owners and remain unchanged.

Protected deployment composition supplies the concrete profile separately from
authored stage configuration. The current built-in bootstrap executes only the
resident local executor:

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
private deployment-owned file and removes that file reference from the process
environment before authored stage code runs. The concrete
`job_private_file_v1` provider is selected only by protected site composition:
it invokes the site-owned helper with a strict non-secret JSON request on stdin
and an explicit non-inherited environment. The helper writes one
allocation-private regular capability file via a Slurm prolog or container
runtime and returns a strict non-secret replayable receipt. Loom retains that
receipt and verifier only for the exact assignment/job/bootstrap registration;
it never exports the capability through
the script, `sbatch` environment, arguments, or durable state. Ready-stage
submission uses `--export=NIL` and a protected explicit environment.

The ready-stage request, submission, and delivery records are schema v3; both
ready-stage SQLite owners require `PRAGMA user_version = 3`; and the protected
helper request/response envelope is v2. Earlier ready-stage records, helper
envelopes, unversioned databases, and mixed table shapes are rejected before
mutation. After a receipt is retained, Loom installs its exact verifier in the
assignment owner before the submission owner records `SUBMITTING`, then mirrors
submission eligibility before calling `sbatch`. This lets a fast bootstrap
register during the synchronous call without granting any profile-wide
authority. Definite rejection and terminal release remain logical until the
same retained receipt receives an exact replayable helper revoke acknowledgement;
unknown prepare, submit, or start outcomes are not revoked or inferred safe.

The profile, not authored stage data, supplies allowlisted account/partition/
QoS, resource/directive mappings, submission limits, resident bootstrap
environment, command adapter, credential delivery, data path, reconciliation,
and retention behavior. Authored data cannot inject raw `SBATCH` directives,
commands, preludes, submit hosts, or credentials.

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

It consumes the run's `max_parallel_stages` slot and a configured profile
outstanding-submission slot, but no agent capacity. Submission uses a deliberate
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

### Durable ready-stage results

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
Larger checkpoints require separate transfer support. Worker scratch space is
separate and is not the durable transport.

The bootstrap writes complete output files and report version 3, fsyncs them,
and atomically publishes manifest version 1 last. The manifest binds the stable
coordinator, original agent/root, assignment, attempt, execution fence, bootstrap
incarnation and submission operation, with paths, digests and byte counts. A
compute process can exit while the coordinator is unavailable. After same-root
restart the original submit agent verifies only that bound location and relays
through the existing authenticated result/finalization path. Old session tokens
are not required. Partial, stale, linked or corrupt evidence cannot commit and
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
