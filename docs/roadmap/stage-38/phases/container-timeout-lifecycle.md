# Phase 3 Execution Plan: Container Timeout Lifecycle

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 38, Phase 3
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p3-container-timeout-lifecycle`
- Worktree: `stage-38-p3-container-timeout-lifecycle` under the recorded root
- Base: `71d24525c21a57be4cf5db8ad325d28254273e3c`
- PR target: develop
- PR title: `feat(execution): supervise container timeout cleanup`
- Dependencies: Phase 2 PR #278 merged at `0c0dbf2`; independent design review
  accepted at `2441182`, with identity-order correction `0786e55`
- Workflow path: expanded, cross-process ownership and cleanup proof
- Blockers: independent implementation review found that repeated managed
  containment calls renew the cleanup observation budget. The 3/3 correction
  allowance is exhausted; one further bounded correction needs maintainer
  direction. PR #280 is open and must not merge until correction and verification.

## Objective And Context

FR-3 requires a truthful configured deadline and supported-process cleanup, not
just a timed-out launcher. A fresh real-process baseline probe proves the
existing Apptainer command runner can return while its ordinary child survives.
The local patch's timeout wiring is useful evidence but is not a supervision
implementation. FR-4 prohibits weakening managed resource release or existing
ordinary/no-timeout semantics.

## Current Source And Harness

Read direct Apptainer command/executor/result owners, ordinary subprocess
command construction, `cli/stage.py`, and execution `stage_worker.py` along with
`StageContext`. Ordinary worker reconstruction explicitly says STAGE; resident
agent and SLURM entries explicitly say OUTER_BOUNDARY. Stage-owned downstream
work may establish its own child groups. Merely adding a launcher process group
does not cover that supported behavior.

Read agent supervisor `contain` as a reference for positive observation/order,
not as a private helper to import. Also trace historical queue `local.py`
inspect/cancel: a new nested session can escape an existing enclosing group.
Direct, legacy whole-run managed, resident agent, and scheduler boundaries must
not be conflated. Existing Apptainer fake-runner tests need real-process
companions; reuse `tests/container_acceptance` for actual runtime evidence.

Independent audit confirmed A-10: the legacy adapter releases after its root
exits while a child can survive in the inherited group. The existing Stage 23
contract requires descendant cleanup. A bounded legacy process-group settlement
observation plus root-first-exit regression is a concrete necessary correction,
not optional hardening. Its integration/phase placement must be resolved in the
expanded lifecycle design; do not copy the resident daemon or silently redesign
the full queue to address it.

Removal-first candidate for A-10: strengthen the built-in process handle's
terminal observation so its adapter retains/renews leases while the owned group
still exists, preserving the root exit code separately. Inspect whether that
can satisfy existing `LocalProcess` obligations without adding a required
protocol method or breaking supported injected runners. Cancellation must still
reach remaining group members after root exit. This is a candidate to review,
not authorization to change the public protocol before the design gate.

### Runtime Evidence And Unapproved Candidate

The inspected host exposes SingularityCE 3.10.4 and cgroups v2. Its CLI exposes
`--pid`, `--no-init`, `--cpus`, and `--memory`. These are availability facts, not
proof of permitted namespaces, delegated cgroups, or actual container cleanup.
A bounded unprivileged user/PID-namespace probe failed while writing its UID map;
that does not establish whether the installed setuid runtime can create a PID
namespace. The maintainer-approved shell SIF from Phase 2 is now available;
its checksum matches the recorded `2ee9ccf7...99e`. No new image or host setting
is required for the bounded design probes below.

The [Linux PID namespace contract](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)
provides a possible boundary: namespace-init termination causes the kernel to
kill the namespace's processes, including processes in different process groups.
The inspected SingularityCE v3.10.4 source uses an init shim with PID isolation
unless `no-init` is selected (`internal/pkg/runtime/engine/singularity/process_linux.go`)
and sets a parent-death signal on the namespace process (`cmd/starter/c/starter.c`).
This suggests investigating runtime `--pid` with its init shim as a containment
backstop, combined with bounded termination and positive observation of the
owned launcher boundary. It is not yet an accepted mechanism or proof.

The unresolved composition question is concrete: creating a fresh launcher
session inside legacy whole-run managed execution can escape that adapter's
enclosing process group. Conversely, killing the caller's inherited group is
not safe for direct Python/CLI use. Runtime exit, namespace-init settlement,
interruption, and physical lease retention must be demonstrated together before
selecting the mechanism. Do not solve this by relabelling ordinary workers as
`OUTER_BOUNDARY` without establishing their actual owner, or by adding another
general supervisor protocol. If the existing owners cannot compose with a
bounded change, present the required broader ownership design separately.

### Fresh Design Evidence

The refreshed base adds PR #279 queue-role environment loading and dependency
updates, not container command or process containment changes. Preserve that
merged work and the concurrent optional-agent phase; no deployment edits here.
The new phase worktree is clean apart from this planning work; its locked Python
3.12 environment was created with `uv sync --locked --all-groups`.

An actual `singularity exec --cleanenv --pid` launch over the approved SIF
succeeded and reported `sinit` as PID 1. The runtime supports this namespace on
the current host even though the earlier generic unprivileged namespace probe
failed. CPU/RAM cgroup enforcement remains a separate, deferred capability.

Bounded design probe `build/pid_namespace_lifecycle_probe.py` and receipt
`build/pid-namespace-lifecycle-probe.jsonl` exercise a shell worker and an ordinary
child that starts its own session and ignores TERM. No GPU or resource-limit
flags are used. Readiness precedes signaling; each observed descendant is pinned
with a pidfd for identity-safe liveness checks and fixture cleanup.

| Trigger | Live descendants when launcher exit was observed | After bounded observation |
| --- | --- | --- |
| Worker exits first | none | none |
| TERM to launcher | none | none |
| KILL to launcher | namespace init and the separate-session child | none |

These three probes passed without timeout escalation and settled within about
0.009 seconds, but that observed latency is not a contract. The KILL case proves
that launcher exit is insufficient positive settlement evidence even when the
runtime's namespace backstop eventually works. The launcher and `sinit` retained
the caller's host process group; the child had its own group/session inside the
container. Some setuid runtime `/proc/<pid>/ns/pid` links were unreadable; payload
namespace links, process ancestry, and pinned pidfd observations remained
available. Do not require unrestricted namespace-link access as a hidden premise.

Independent bounded source discovery confirms legacy `LocalProcess.poll()`
currently returns only the built-in `Popen.poll()` root status. `inspect()` then
releases leases and stops renewal, and `cancel()` skips signaling when that root
has exited. The established injected-runner protocol has no separate settlement
method. Resolve A-10 at existing owners without silently adding a required method
or adopting processes by PID. A stronger built-in terminal observation remains a
candidate; it must preserve the root result separately and remain cancellable.

The fresh compatibility baseline at `build/timeout-owner-baseline.xml` passed
161 tests with zero failures, errors, or skips in 21.298 seconds. It covers the
Apptainer unit directory, stage-worker and `StageContext` behavior, legacy local
adapter tests, the worker contract, and import boundaries. This is a clean
starting receipt, not containment acceptance.

Fresh kernel-source evidence narrows the remaining question. Linux v5.15 and
the host's matching v6.8 source show that `zap_pid_ns_processes()` waits until
the namespace has no remaining processes before its init can complete reaping
([v5.15 `kernel/pid_namespace.c`, lines 198-234](https://github.com/torvalds/linux/blob/v5.15/kernel/pid_namespace.c#L198-L234));
task release retains process-group membership until `release_task()` removes the
task. Because the observed `sinit` stays in the inherited host group, confirmed
absence of that group may therefore be a settlement barrier for its namespace,
including a payload in another group/session.

The bounded receipt `build/pid-namespace-group-kill-probe.jsonl` tests that
ordering on kernel `6.8.0-138-generic`. Its fixture alone creates a fresh session
so it can safely signal the whole owned group. On group KILL, `sinit` remained in
that group while the TERM-ignoring `sleep` remained in its own session; the
launcher returned `-9`, the group became absent, and every pinned descendant had
exited after about 0.0035 seconds. This single observation supports the smaller
candidate but is not broad acceptance, a latency contract, or proof for startup,
interruption, and production capacity-release paths. Group absence also must not
be assumed promptly observable while task release or zombie cleanup remains.

### Reviewed Mechanism And Exact Owners

Independent review accepts existing ownership plus the runtime namespace;
a new retained owner is not justified. On direct execution, the built-in
runner remains alive to enforce the deadline, signal only its created launcher,
reap that launcher, and positively observe an identity-safe namespace-init handle
captured from the live launch lineage. On managed cancellation, the runtime
launcher and `sinit` must remain in the inherited outer group. The existing
legacy/agent owners use confirmed group absence as terminal only on the reviewed
kernel/runtime path, with implementation evidence proving that `sinit` remains
a member through teardown. Namespace-init settlement, not
launcher exit, then covers the separate-session payload.

The review also locks safe signaling order. Cache a creation-owned root's exit
status through a non-reaping `waitid(..., WNOWAIT)` observation. Retain that root
as an unreaped PID/PGID anchor through the single TERM/grace/KILL sequence, then
reap exactly once and permanently close group signaling. Post-reap group checks
are observation-only: presence or numeric reuse retains capacity, never grants
permission for another signal. Root-first exit starts containment before reaping.
Failure to retain the anchor fails closed. A bounded host probe confirms this
wait/signal/reap order (`build/process-group-anchor-probe.txt`); it is mechanism
evidence, not the full descendant acceptance matrix.

Direct init capture must verify creation-linked live lineage and identity, not
adopt a process by name or raw PID. If startup or launcher-first exit prevents
positive capture/settlement, return an unresolved-cleanup failed attempt within
the cleanup budget; retain timeout as primary when applicable. Reject worker
outputs before reading/admitting them. Managed callers separately require their
outer settlement barrier. Cover startup, TERM/KILL, interruption, task reaping,
identity reuse and ordinary result compatibility. Do not add a helper
process, process-wide subreaper, new group/session, new public method, or result
schema for convenience. The current `StageContext` producers remain unchanged,
and the executor must reject outputs before reading/admitting a worker result
whenever timeout or unsettled cleanup is reported.

If the group barrier is rejected or cannot be proven on the supported runtime,
the smallest fallback is a retained per-invocation owner acknowledged by the
actual capacity owner before launch and able to survive the killed worker group.
That is a materially broader cross-owner design proposal requiring explicit
maintainer agreement and independent design review before implementation. It may
not be smuggled into this phase as private wiring or expanded into a reusable
supervisor framework, durable supervisor, cgroup requirement, registry, public
owner enum, or required protocol method without that decision.

A-10 remains a bounded correction at its existing owner. The built-in local
process handle caches root status without reaping and starts bounded containment
on root-first exit, while `poll()` stays nonterminal until post-reap group absence.
Cancellation uses the same one-shot signal/reap sequence. This strengthens the existing terminal meaning and
does not add a protocol method. Injected runners remain responsible for the
existing `LocalProcess.poll()` terminal contract; tests need not gain a new fake
method. Process-group existence is conservative evidence only: it need not become
observable promptly after reparenting/zombie cleanup. This correction closes the
confirmed inherited-group root-first-exit defect. It covers a separate-session
namespace child only if the independently reviewed kernel/runtime-init barrier
above is established; `killpg(..., 0)` alone is not that proof.

Manager source verification found the same identity-order defect at the existing
resident supervisor, not a new ownership requirement: `query()` calls
`child.poll()` before `contain()` signals the stored group; `_process_group_alive`
also reaps before later escalation, and service `request_stop` can repeat the
pattern. Apply the same reviewed anchor/signal/reap contract to these existing
owners. Preserve query's root-exit result, separate CONTAINED/UNKNOWN decisions,
launch replay, durable receipt/schema, shutdown, restart non-adoption and physical
release semantics. Do not replace the supervisor or transport. A private helper
shared by these two current queue consumers is justified only if it removes
duplicate identity-order logic; the direct container runner must not import it.

Exact product owners: `pipeline/executors/apptainer/commands.py` and `executor.py`,
their existing command/capability/diagnostic integration where needed, queue
`local.py`, and queue `_agent_process_supervisor.py`. Preserve public runner
methods, command-result schema and `StageContext` producers. Tests/docs belong
with those owners. Linux foreground SingularityCE 3.10.4 `--pid` with its init
shim is the evidenced runtime; do not advertise unproven runtime/mode support or
silently use launcher-only cleanup on unavailable OS identity primitives.

## Scope

### Capability And Attempt Reporting — Repository-Resolved

`ExecutorDescriptor` is import-light metadata for an executor name, not a probe
of a particular runner instance or machine. Existing subprocess metadata already
advertises `ENFORCED` independently of its injectable runner, while
`executors/_reliability.py` and execution reliability writers separately record
each attempt's actual timeout outcome. Reuse that distinction; do not add a
conditional enum, descriptor API, schema, registry or discovery protocol.

- Set the built-in Apptainer/Singularity descriptor to `ENFORCED` as capability
  of its supported, admitted timeout path. Use existing descriptor/diagnostic
  details and user-facing messages to state prerequisites: the built-in Linux
  runner, the evidenced foreground runtime mode, PID namespace and init shim.
  Static validation says this path can enforce policy; it does not certify the
  submission host, execution host, arbitrary injected runner or selected image.
- Keep launch admission authoritative. Known unsupported platform, runner or
  mode selections with an enabled timeout fail actionably before worker launch.
  Runtime/topology failure or inability to prove cleanup after launching is a
  failed attempt with bounded cleanup, not an ignored timeout or success. Do not
  promise that static preflight proves facts observable only during execution.
- Reuse `timeout_policy_from_request`, `timeout_metadata`, and
  `metadata_with_timeout`. Pre-admission refusal records `UNSUPPORTED` with its
  reason and a failed attempt; an admitted policy records `ENFORCED`, or
  `TIMED_OUT` when the deadline fires. Cleanup uncertainty remains separately
  explained in existing failure details and never permits output admission.
  Descriptor capability is not itself an attempt enforcement receipt.
- Absent/disabled policy adds no timeout, PID-namespace requirement, runtime
  version check or new restriction. Existing custom-runner behavior without a
  timeout remains supported. GPU, resource mapping/scheduling-only, SLURM-owned
  limits and unrelated executor descriptors remain unchanged.

This clarifies the already approved fail-on-unavailable-boundary behavior at
existing owners. It does not broaden supported timeout modes or authorize a new
public capability model. Cover the truthful static message, admitted execution
receipt, unsupported no-launch failure, and disabled/no-policy compatibility.

Approved outcome: configured deadlines, bounded graceful termination and
escalation, observation and owned reaping, primary timeout plus cleanup context,
and no success admission or physical release based on an exited launcher alone.
The existing-owner mechanism is independently reviewed. Required implementation
review and runtime acceptance remain gates, not presumed results.

Exclude a general supervisor framework, daemon imports into low-level commands,
arbitrary hostile/daemonizing-process containment, new scheduler or recovery
APIs, rphys changes, and silent expansion into every executor. Any new public
surface or materially broader process-ownership change needs a separate bounded
design decision rather than being hidden as private wiring.

## Fixed Contracts And Private Discretion

- Timeout is failure, never cancellation or successful output. A worker result
  written before the deadline cannot override timeout or cleanup uncertainty.
- Start the deadline before runtime launch. Cleanup has one bounded TERM grace
  and one bounded KILL/observation grace; neither extends or rewrites the primary
  deadline. Reuse the current resident upper budgets: at most two seconds for
  TERM grace and two additional seconds for KILL/settlement observation. Existing
  explicit forced-stop paths may escalate earlier; do not delay an ownership-loss
  stop or turn these caps into new mandatory waits.
- Signal only processes/boundaries owned by this invocation. Observe exit and
  reap owned processes before claiming termination. Creation-linked child/OS
  handles and wait status must establish identity. Managed group signals occur
  only while the unreaped creation-owned root anchors the identity; once reaped,
  never signal that group again. A name, raw PID or namespace-link read alone
  is not ownership evidence. No helper process or subreaper is authorized.
- Stage and enclosing-owner obligations must agree with actual containment.
  Keep the ordinary worker's `STAGE` fact and existing resident/SLURM
  `OUTER_BOUNDARY` facts. Keep the runtime launcher/init in the inherited outer
  group; a label or `killpg` call alone is not proof that supported descendants
  are gone.
- Preserve the primary explanation and secondary cleanup failures without
  leaking environment values. Failed/unknown containment cannot admit outputs.
- Enable this timeout path only for the built-in Linux Apptainer/Singularity exec
  runner with `--pid` and the runtime init shim. Runtime rejection or inability
  to establish the reviewed settlement boundary is an actionable failed attempt,
  never a fallback to launcher-only timeout or a claim of enforcement.
- Managed capacity remains held until its actual owner has positive settlement
  evidence, not just a direct launcher result. Existing agent/scheduler owners
  remain authoritative on their routes.
- Keep ordinary success/failure and absent-timeout behavior compatible. Do not
  globally change worker owner facts to make one container test pass.
- Private helper/fixture names and intermediate data are open only after the
  public, durable, cross-owner, and lifecycle mechanism decisions are locked.

## Proportionality

The built-in command runner remains the direct API owner and existing outer
owners remain cancellation/capacity owners. The runtime init's inherited group
membership plus the Linux namespace teardown ordering may connect those existing
owners without a new process or public contract. A post-exit PID scan, new
launcher group, process-wide subreaper, or launcher-only wait remains insufficient.
The accepted mechanism needs no retained cross-owner supervisor. Any demonstrated
need for one must return for maintainer agreement, not expand this implementation.

## Invariant Ownership

| Invariant | Owner to establish in design | Reachable consequence | Evidence required |
| --- | --- | --- | --- |
| Deadline and cleanup budgets | Built-in exec runner | Hanging supported work or unbounded cleanup | Deterministic runner tests and real timed process fixtures |
| Correct child ownership | Runtime launcher/init plus existing `StageContext` producers and outer owner | Runtime init leaves the inherited group or group absence precedes namespace settlement | Live topology, group-KILL ordering, unchanged owner facts, real separate-session descendant |
| Outcome admission | Executor result gate | Late/stale success accepted despite timeout | Result-before-timeout fixture |
| Capacity settlement | Existing legacy/agent/scheduler owner after reviewed namespace-init barrier | Root-only observation releases capacity while a namespace descendant remains live | Legacy root-first-exit regression plus managed group-KILL/descendant proof |

## Implementation Slices

1. Design review passed with the non-reaping root-anchor correction. Implement
   the same identity-safe ordering in the two existing managed group owners;
   preserve root-exit publication separately from physical settlement.
2. Implement timeout-only PID-namespace selection in the
   built-in runner, bounded cleanup/observation, identity-safe direct settlement,
   and the executor's timeout-before-result admission gate. Preserve public
   runner/result shapes and existing `StageContext` owner values.
3. Preserve the existing managed protocols and durable state. Root-first cleanup,
   cancellation, resident query/contain/request-stop and shutdown must all respect
   the one-shot signal/reap sequence. No post-reap signal or PID adoption.
4. Add deterministic process fixtures, the selected-runtime acceptance cases,
   docs, and redacted failure evidence; then run targeted and full gates and
   independently review the resulting implementation.

## Test And Validation Plan

Required real-process cases: timeout during runtime startup; normal timeout with
a cooperating child; launcher exits before a separate-session child; child
ignores TERM and requires escalation; caller `KeyboardInterrupt`/control-channel
loss; result written immediately before deadline; forced cleanup uncertainty;
and success/failure without timeout. Assert launcher/init group continuity,
namespace descendant exit before group absence is accepted, identity-safe direct
observation/reaping, capacity retention through group-KILL settlement, and no
output admission after timeout. Fixtures must own every process/group they signal
and guarantee their own cleanup.

Both managed owners need a production-path regression proving non-reaping root
status, signals before the sole reap, and no signal after reap even when a numeric
PGID remains present/reappears. Cover resident query-before-contain, request-stop,
repeated contain and clean shutdown; preserve launch replay and restart
non-adoption. Use controlled syscall evidence for reuse, never force host PID reuse
or signal an unrelated process. Real descendant fixtures prove actual cleanup.

Required production evidence: selected container runtime with a suitable image,
actual `--pid`/init topology and cleanup behavior, unchanged worker containment
facts, no success on timeout, and managed capacity retained until the reviewed
group/namespace-init barrier positively settles separate-session descendants.
Reuse the recorded three-case and group-KILL probes/receipts as design evidence;
do not rerun them as acceptance.
Mocks can cover IPC corruption and rare cleanup errors but cannot prove child
liveness or outer-group composition.

Targeted implementation gate (expand only for changed adjacent owners):

    uv run pytest tests/unit/loom/pipeline/executors/apptainer \
      tests/unit/loom/pipeline/execution/test_stage_worker.py \
      tests/unit/loom/pipeline/execution/test_timeout_metadata.py \
      tests/unit/loom/pipeline/execution/test_lifecycle.py \
      tests/unit/loom/pipeline/test_context.py \
      tests/unit/loom/pipeline/test_executor_capabilities.py \
      tests/contracts/test_executor_capabilities_contract.py \
      tests/contracts/test_reliability_contract.py \
      tests/unit/loom/queue/test_local_adapter.py \
      tests/unit/loom/queue/test_process_group.py \
      tests/unit/loom/queue/test_agent_process_supervisor.py \
      tests/unit/loom/queue/test_resident_stage_worker.py \
      tests/integration/queue/test_agent_session_transport.py \
      tests/contracts/test_stage_worker_contract.py \
      tests/container_acceptance/test_real_container_runtimes.py \
      tests/container_acceptance/test_apptainer_timeout_lifecycle.py \
      tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

Exact targeted commands and affected integration cases must be locked during
expanded phase preparation. Missing runtime prerequisites remain visible gaps.

## Risks, Review, And Stops

Stop on a new missing contract or failed mechanism. If runtime-init membership or Linux
teardown/group-release ordering cannot make group absence positive settlement
evidence, do not implement the existing-owner candidate. Present any retained
owner, public/durable handoff, new containment-owner value, supervisor, cgroup,
or outer-manager redesign explicitly for maintainer agreement and a new review.
Do not substitute launcher-only timeout support. Prior phases may remain merged
while this decision is resolved; the overall objective stays open.

## Executor Handoff

One executor is authorized for the owners and reviewed contracts above. Preserve
all other work. Return coherent commits, changed paths, implementation and exact
validation receipts here; no PR/merge, independent review, or delegation. Stop for
an unsupported platform/runtime decision, new public/durable mechanism, or inability
to maintain the creation-linked ownership proof. Do not weaken the accepted gate.

## Workflow State

- Manager preparation: refreshed base and predecessor merge verified; isolated
  phase worktree prepared; locked environment and fresh runtime evidence recorded
- Expanded planning: existing-owner mechanism and exact consumers locked
- Independent design review: accepted at `2441182`; one bounded correction at
  `0786e55` locks group identity through the final signal
- Manager startup: kernel/runtime receipts, 161 baseline passes, exact source
  owners and repeated resident identity-order path verified; ready for one executor
- Implementation: manager-owned implementation complete; targeted gate passed
  273 tests with five unrelated optional-runtime skips. Static supported
  capability, launch prerequisites and actual attempt outcome stay distinct.
- Material handoff anomaly: the executor returned no implementation after its
  capability clarification. The manager implemented the already reviewed scope
  directly; this did not reopen product contracts or introduce another executor.
- Pre-submit: both full gates passed at production/test revision `3fd6f65`;
  only roadmap metadata changed afterward. Manager scope, preserved contracts,
  domain neutrality and current evidence checks passed. PR #280 targets develop.
- Independent implementation review: completed against PR head `ae81bbf` and
  base `71d2452`; not merge-eligible. One product blocker remains: the shared
  managed handle renews its observation wait budget on every `contain()` call.
  No other qualified findings were returned. The identity-order mechanism and
  frozen timeout-fact reader were otherwise accepted.
- Blocker corrections: 3/3 including capability/reporting clarification,
  pre-submit fixture type narrowing, and A-15's frozen timeout-metadata reader
  correction plus completion of real early-result coverage. No public values or
  schemas changed. Any further qualified blocker requires maintainer direction.

### Independent Review Blocker: Non-Renewable Cleanup Budget

The supported resident `request_stop()` path can call `terminate()` before a
later or repeated `contain()` call. `OwnedProcessGroup` preserves TERM and KILL
state, but `contain()` creates a fresh `monotonic() + 4` deadline on each call.
When post-reap group presence remains uncertain, each call can therefore wait
another four seconds instead of consuming the remaining original budget.

The reviewer's deterministic clock/syscall reproduction starts TERM at t=0,
then calls `contain()` at t=3. That call sends KILL and reaps at t=3 but blocks
another 4.02 seconds; a second call blocks another 4.02 seconds without another
signal or reap. The manager verified the fresh-deadline code and the accepted
two-second TERM plus two-second KILL/observation contract. Current reuse coverage
makes the group absent before `contain()`, so it does not cover repeated calls
while conservative group presence persists.

Capacity retention remains safe; the defect is repeated synchronous control
blocking beyond the accepted cleanup bound. The proposed bounded remedy is one
absolute, non-renewable cleanup/observation deadline owned by the existing
handle, including its forced-kill path. Delayed calls consume only remaining
time. After expiry, later calls perform an immediate settlement observation:
return false while presence is uncertain, and true once absence is positively
observed. Preserve one-shot signaling/reaping and prohibit post-reap signals.
Add deterministic delayed-stop/repeated-containment coverage proving that waits,
signals and reaping are not renewed. No new public contract or owner is needed.

This remedy is proposed, not implemented or newly authorized. The exhausted
correction allowance requires maintainer direction before a further bounded
implementation and independent verification. Passing existing gates does not
override the review hold.

## Completion Record

| Item | Result |
| --- | --- |
| Reviewed mechanism and approved boundaries | Independent mechanism review accepted with signal/reap ordering; static-capability versus attempt-outcome reporting is clarified above using existing owners. Approved SIF and SingularityCE 3.10.4 verified; its path is recorded in `build/pid_namespace_lifecycle_probe.py`, checksum `2ee9ccf77bea0f95bfa9274585bf30cea6976e4a5e709ece4243e19eef08f99e`. |
| Implementation and changed paths | Timeout-only private foreground namespace supervision, existing executor outcome/result gate and capability messages; one private group handle shared by the existing legacy/resident owners. Public protocols, durable formats and `StageContext` values unchanged. Source-mirrored tests, opt-in lifecycle acceptance and reliability/test docs updated. |
| Real process/runtime tests and validated revision | `3fd6f65`: `build/container-timeout-final.xml`, all 13 selected-runtime cases passed in 11.08 s; `build/timeout-metadata-correction.xml`, 49 related checks passed. Earlier `build/timeout-targeted.xml`: 273 passed, five unrelated optional skips, 238.04 s. Real ready TERM-resistant resident descendant, query/request-stop/shutdown, controlled PGID reuse and lost-ownership checks covered. Opt-in runtime flags and approved image are described below; no resource flags or host changes. |
| Full local gates | `3fd6f65`: `make validate-pr` passed, including lint, zero type errors, 2,849 default passes, 161 config-extra passes, 18 opt-in skips, sdist/wheel builds (`build/timeout-validate-pr.log`). `make test-summary` passed: 3,010 passes, no failures/errors, 18 opt-in skips in 900.88 s (`build/test-summary.md`, per-suite XML/coverage and `build/timeout-test-summary.log`). All 13 timeout runtime hooks passed separately. Two existing monitor-test unawaited-coroutine warnings remain outside this change. |
| PR, review, and merge | [#280](https://github.com/samcantrill/loom/pull/280) open against develop. Independent review of `ae81bbf` found the non-renewable-cleanup-budget blocker above; merge held pending authorized correction and verification. |
| Residual risk and cleanup | Repeated managed containment can exceed its promised wait bound; capacity remains retained safely. Unsupported prerequisites fail explicitly; static diagnostics never claim observed host enforcement. Worktree retained; final receipts copied and checksum-verified in integration `build/stage-38-p3-3fd6f65`. Transient test-fixture setup errors were corrected before final targeted acceptance; the two delayed fixture roots from an early setup failure exited under their own 30-second deadlines and were confirmed absent. |

Pre-submit continuation: `make validate-pr` passed for production revision
`090385a` (2,848 default passes; 161 config-extra passes, 17 opt-in skips), after
fixture type narrowing. Subsequent end-to-end trace reproduced A-15: frozen
timeout metadata was silently omitted by the existing execution reader. Its
single `dict` to `Mapping` correction restores classification and persistence;
the new constructor-to-record regression and affected lifecycle/executor/inspection
checks pass 49 tests (`build/timeout-metadata-correction.xml`). The real SIF now
also writes a valid success file before expiry through a shell worker-protocol
fixture; the production executor/runner rejects it before reading. This closes
the real early-result acceptance case in addition to the 12 earlier runtime cases.
The final `make validate-pr` and 13-case live-runtime acceptance passed at
`3fd6f65`, including this correction. Suite summary also passed; independent review
subsequently found the cleanup-budget blocker recorded above.
