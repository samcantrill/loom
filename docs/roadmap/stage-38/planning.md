# Roadmap Stage 38 Planning: Selective Container Port And Correctness Review

Status: first phase merged; Phase 2 implementation, full gates, and independent review passed
Roadmap stage: 38
Evidence revision: `f4b1ae76f63d33f2d481916bf36147f372e6225d`
Planning route: expanded for container process ownership; independent baseline
and implementation correctness reviews explicitly required by the maintainer.
Current gate: manager PR checks and merge; all Phase 2 product gates passed at `04443ed`.
Blockers: none for Phase 2; Phase 3 retains its design gate.
The maintainer approved the warning correction and one fresh bounded verification
after the prior reviewer reuse was consumed. Positive runtime-limit acceptance is deferred
to a compatible host; the later timeout design gate remains.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Authority | Maintainer requested execution of the selective-port draft, including review and merges to develop | No authority to retire the original dirty checkout | Preserve it throughout |
| Evidence | Published develop verified; initial audit accepted; `04443ed` independently accepted with 80 focused passes, both full gates, 2,994 summary passes / five optional skips, and one selected-policy SIF smoke pass | A-10 remains design-gated | Preserve exact-tree receipts and verify PR |
| Functionality | Stage-owned validation, explicit direct CPU/memory enforcement policy, lifecycle-safe timeouts; retain corrected upstream behavior | Scheduling-only execution explicitly accepts no OS CPU/RAM limit; no scientific or remote submission changes | Trace each requirement to an owner |
| Design | Scheduling-only policy and combined passive-wait amendment startup independently accepted without findings | Timeout ownership unresolved | Review the implemented amendment |
| Implementation | Phase 1 merged; queue correction and `04443ed` warning correction independently accepted; fresh full gates passed | No Phase 2 product blocker | Verify PR and merge |

## Evidence And Scope

The source checkout is `/nas/home/can134/work/loom`, originally on dirty `develop` at
`a6bd1ef54523ac394b6a875c7486f9d8d7f68b95`. It contains 36 modified tracked
files (15 source, 18 tests, three feature docs), plus the untracked historical
concurrency brief and GPU visibility helper. None is an implementation base.
Another session has moved it to `agent/preserved-loom-control-before-stage-85`
without changing the preserved content hashes, and owns a separate develop
worktree. Do not update or retire either checkout as part of this phase.
The selected worktree root is `/nas/home/can134/work/loom-worktrees`; the active
resource-phase tree is `stage-38-p2-direct-container-resources`, branch
`agent/stage-38-p2-direct-container-resources`. The older Stage 81 worktree remains
untouched and is not repurposed.

Phase 1 merged at `133505b12d3e0bea53a42533ec240ff4f1b3562b`; its temporary
worktree and local/remote branch are removed. The clean, detached
`stage-38-integration` worktree owns post-merge metadata and retains generated
Phase 1 test reports/packages. It avoids advancing the dirty control checkout
by discarding, stashing, or moving any original work. Original preservation
hashes were rechecked unchanged before merge.

Preservation receipts, SHA-256 at intake:

- Tracked `git diff --binary`: `99d00f0ee2f74a204e76ad80c070a25c7abe2693b7a4f9c3b2269121301c9861`.
- `docs/briefs/managed-local-concurrency-and-resource-assignment.md`:
  `621f48ea97e753dd37d3d7d545ef4df8ab6bb94780bf2ecfb85e109918e4a297`.
- `src/loom/pipeline/executors/gpu_visibility.py`:
  `f59cbe323cc492982a590244ca8950b366ab2007952f286bcdad9274b0bcb819`.

The changed tracked areas are CLI run/plan/validate, preflight, runtime options/
profiles/capabilities and exports, direct Apptainer, SLURM composition/rendering,
and plain serialization, with corresponding tests and feature documentation.
There is no dirty queue implementation. Do not apply the complete historical
diff: upstream has 145 intervening commits and intentional semantic differences.

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Stage 35 plan; runtime options/profiles, CLI run/plan | Run-store selection and GPU admission already merged; CPU/memory flags and timeouts were explicitly deferred | Selective disposition, compatibility | FR-2, FR-4 |
| CLI validate; pipeline stage factory; locked Weave target checker | Stage checker constructs only the outer factory, but generic traversal still enters stage-owned mappings | Validation defect | FR-1 |
| Apptainer commands/executor and runtime capabilities | Resource intent is already projected into the container record, but direct CPU/memory flags are absent | Extend current command owner | FR-2 |
| Stage 37 plan, stage context, ordinary and resident worker reconstruction | Ordinary workers are STAGE-owned; resident agent and SLURM entries are OUTER_BOUNDARY-owned | Timeout design constraint | FR-3 |
| Queue assignments, local daemon execution, agent process supervisor | Capacity/ownership mechanisms exist; root exit is distinguished from containment | Retain current ownership, reconcile historical brief | FR-4 |
| Plain serialization helpers and round-trip tests | Mapping-based conversion and refreezing already implemented | Avoid duplicate port | FR-4 |

User-visible outcome: trusted configuration keeps its stage-owned data intact;
direct containers explicitly request supported limits or retain resource intent
without direct CPU/RAM enforcement; timeout results tell the truth
about supported-process cleanup. Existing managed execution remains compatible.

Non-goals: rphys stages or scientific operations, PURE products, determinism,
network submission APIs, Stage 81 domain-failure transport, new schedulers,
physical GPU selection, general process-supervisor frameworks, or cleanup of
the original checkout. Test data is synthetic. Do not inspect or publish private
environment files, credentials, real experiment logs, or dataset contents.

## Upstream Correctness Audit

The audit traces public inputs through source, persistence, tests, and docs.
Passing old-checkout tests are not an upstream receipt. The isolated environment
was created with `uv sync --locked --all-groups`, using Python 3.12.3 and locked
Weave revision `6a99a4d7e6f008748c0761e6ab1c359d62aacbbd`.

| ID / classification | Evidence and supported path | Consequence / disposition |
| --- | --- | --- |
| A-1 confirmed defect | `cli/validate.py:handle` sends the complete composed config to generic target checking after checking stage factories; the skipped factory path does not stop recursive traversal into its children | Nested stage config, factory init, and pipeline metadata targets can be constructed independently. Port the ownership guard and add a real public CLI regression. |
| A-2 intentional compatibility difference | `RunStoreOptions` normalizes lexically with `normpath`; profiles support sparse merging and explicit null clearing; CLI bootstraps and checks the selected root before/after runtime validation | Retain upstream. The older filesystem-resolving, non-null-only implementation would regress supported behavior. |
| A-3 intentional compatibility difference | GPU helper preserves explicit `nv`, ignores visibility for zero requested GPUs, validates positive allocations, and keeps raw tokens out of persisted executor evidence | Retain upstream. Old local code clears explicit passthrough and exposes allocation tokens. |
| A-4 intentional compatibility difference | AFTEROK rendering rejects empty/trailing/comma-separated invalid tokens and initial punctuation; whole-run mode is a distinct owner | Retain those corrections and executable Bash tests, while correcting the separate A-9 newline gap. Do not restore raw visibility printing or apply per-stage rules indiscriminately. |
| A-5 already implemented | Plain conversion accepts Mapping recursively; refreeze/thaw returns detached mutable values and rejects unsupported nested values | Retain upstream; no second serialization mechanism or schema change. |
| A-6 existing capability to retain | Static-slot provider distinguishes deferred capacity from failure; current resident daemon has independent ownership/terminal/physical-release paths; its supervisor requires group containment | Retain current daemon behavior. This does not certify legacy LocalQueueDispatchAdapter; see A-10. |
| A-7 missing capability / design risk | Apptainer executor does not pass reliability timeout; its runner uses `subprocess.run(timeout=...)`; ordinary subprocess timeout kills the immediate worker only | Neither runner is evidence of complete descendant cleanup. Resolve ownership and prove cleanup before enabling container timeouts. The ordinary subprocess executor redesign is not automatically included. |
| A-8 missing capability | `_with_runtime_resources` provides typed container intent, but `build_apptainer_exec_command` emits no CPU/memory flags | Add mappings at the existing command boundary with truthful host-dependent enforcement claims. |
| A-9 confirmed defect | AFTEROK `_gpu_allocation_lines` parses the environment with line-oriented Bash `read`; a valid first line followed by a newline is accepted, although Python rejects the complete value | A malformed allocation environment reaches the stage and is forwarded to container variables. Reject the invalid complete value before `read`, retain redaction, and extend the executable grammar test during the resource phase. |
| A-10 confirmed defect / missing coverage | Legacy `local.py` starts a process group but `inspect` releases assignment/scalar leases after immediate-root `poll`; an inherited-group child can still be alive | Conflicts with Stage 23 descendant ownership. Requires a bounded legacy process-group settlement observation and real root-first-exit regression, separate from the validation guard. Resolve its composition within the timeout design gate before changing lifecycle behavior. |
| A-11 confirmed validation defect, corrected | The unchanged upstream `test_slurm_ready_stage.py:_exercise_mixed_route_run` compared entire submission records around rejected registration while live `reconcile_once` could refresh `scheduler_observed_at` through `slurm_submissions.observe` | Initial full gate: 2,793 passed, one failure solely from a one-second timestamp refresh. A bounded test-only correction holds the existing daemon `_cycle_lock` across the before/request/after no-mutation assertion. Complete record comparisons and concurrent-registration coverage remain; no production queue change. All 15 affected integration tests and both fresh gates passed. Independent phase review includes this correction. |
| A-12 confirmed validation defect | The unchanged upstream `test_retirement_secret_rejects_before_mutation_and_is_redacted` compares whole database snapshots while background `reconcile_once` samples clock health and commits `accepted_time_high_water` under `_cycle_lock`. The invalid-secret retirement path verifies the secret before mutation and does not sample the clock. | The corrected-resource summary gate had 2,967 passes and one failure solely from a one-second high-water change. Hold the existing cycle lock across the test's before/rejection/after assertion; retain complete snapshot equality and successful-retirement/redaction assertions. No production queue change. This bounded gate correction is included in Phase 2 validation and independent review. |
| A-13 unresolved upstream validation failure, not a confirmed resource regression | At `9ebd227`, unchanged `test_outbound_service_renews_idle_offer_then_assigns_and_stops_cleanly` timed out waiting 30 seconds for submitted work; 2,810 other default tests passed. Retained coordinator state is `BOUND`, agent journal `request_durable`, no transfer authorization or supervisor launch, and no worker process ID. A fresh isolated exact-test run passed in 15.40 seconds. | Root cause is not established; the isolated pass does not clear the failed full gate. Both fixture supervisors were confirmed stopped. Resource code and production queue/transport code have no overlapping changes. Hold the phase and present a separate bounded transport/pre-launch investigation rather than weakening deadlines or changing recovery policy inside the resource port. |

### Approved A-13 Follow-up Scope

Instrument only the existing synthetic loopback fixture's delivery-to-grant
path: RPC operation names, timings and outcomes, coordinator lock waits, and
durable pre-launch transitions. Do not record request payloads or secrets.
Reproduce the stall before selecting a fix, distinguishing a stalled request
from the intentional conservative retention of indeterminate pre-launch work.
Any required transport/recovery behavior change needs its own bounded design
and regression review. No timeout increase, automatic restart, lease release,
or production queue change is assumed. The maintainer approved this bounded
investigation and a cause-backed, independently reviewed correction. Request
help for missing runtime prerequisites or a materially broader recovery design;
the resource phase has not expanded into an unrestricted transport rewrite.

#### A-13 Reproduction And Bounded Correction

Eight temporary instrumented repeats passed; the original intermittent trigger
is not established. A real loopback test that fails one server response after
the first `assignment_control` dispatch reproduces the failure deterministically:
the client raises `_IndeterminateAgentProtocolError` from the pre-grant control
poll and exits `execute_one`; the original 30-second completion assertion fails.
The retained state matches the initial failure: coordinator `BOUND`, agent
`request_durable`, no transfer authorization, no supervisor launch. Evidence:
`build/transport-diagnostic-control-loss.xml` and temporary synthetic-only
`build/transport_diagnostic.py`. This proves a supported failure mode, not the
initiating cause of the earlier uninstrumented full-suite timeout.

Smallest correction: the existing `_cancel_pregrant_if_requested` owner should
use `_assignment_call` for its control poll, as adjacent pre-launch operations
already do. Preserve the existing retry bound, coordinator-epoch reconciliation,
durable control/ack replay, non-retryable conflicts, and fail-closed retention
after exhaustion. Do not add restart adoption, release claims, change deadlines,
or widen retries globally. Add a real loopback regression for transient pre-grant
response failure and proportionate rejection/exhaustion safety evidence. This
consumes the third scoped correction; independent correctness review and
fresh full gates remain mandatory. Live resource acceptance is still separate.

#### Remaining Coordinator Responsiveness Blocker

The retry candidate is not a complete resolution. In
`build/transport-diagnostic-retry-repeats.xml`, five instrumented cases passed
before one failed its 30-second completion wait. That failing trace shows renewal
and session-control calls each taking their 10-second HTTP timeout, before the
assignment was saved at approximately 34.94 seconds from fixture start. At the
20-second snapshot both server handlers were waiting for `_cycle_lock` in the
session/offer serialization decorators; the reconciliation thread held that lock
while reading the per-run SQLite authority.

The injected pre-grant control failure then retried successfully: authorization,
grant, launch, and result/release completed at approximately 37.97 seconds,
after the test deadline. This separates a working retry path from a coordinator
responsiveness failure; server TLS EOF/BAD_LENGTH messages followed already
timed-out clients and are not established as the initiating cause. One later
six-case run with additional cycle timing passed
(`build/transport-diagnostic-cycle-contention.xml`), but that run alone did not
identify the precise lock-delay mechanism. The approved amendment below now adds
cause-backed measurements; do not infer resolution from the earlier passes.

The candidate changes only the existing pre-grant retry call, its two loopback
outcomes (eventual success and durable cancellation without launch), and queue
documentation. Focused Ruff and whole-tree Pyright pass. Rejection/exhaustion
coverage and full gates subsequently passed at `8702e06`; final independent
acceptance remains outstanding.
Both supervisors from the failed instrumented fixture were verified stopped;
temporary diagnostics now use the repository's supervisor-cleanup fixture.

The three historical correction passes remain consumed. The additional bounded
amendment below is now explicitly approved and supplies new cause-backed evidence.
It does not remove serialization, extend deadlines, or weaken regression tests.
The retained retry candidate now has safety coverage and passing full gates with
the implemented passive-wait amendment; independent acceptance remains required.

#### Approved Coordinator-Responsiveness Amendment

The maintainer now explicitly approves the bounded investigation and cause-backed
correction described above, followed by resuming the already approved scheduling-only
policy work. This supersedes the prior missing-authority stop, not the technical
validation/review gates. The three historical corrections remain consumed; this
is one additional expressly authorized amendment, not a reset to three more
general-purpose corrections. No host settings, deadlines, session-replacement
fences, assignment atomicity, retry/release semantics, or durable schemas may be
weakened to obtain passing tests.

Measure outer `_cycle_lock` acquisition wait and hold times, reconciliation-cycle
overlap with waiting session calls, and authority connection/open/close time in
the existing synthetic loopback fixture. Keep only operation names/timings in
temporary ignored diagnostics, never payloads or credentials. Compare a passive
completion-wait experiment only after baseline measurement. A concrete reproduced
mechanism must precede selection of the smallest production correction and its
independent design review; no broad lock replacement is preapproved. Retain
periodic reconciliation and mutation-driven wakeups. Add a deterministic regression
for the confirmed trigger and existing real loopback safety coverage. Run fresh
full gates and independent implementation review before any PR/merge. Stop on
a materially broader mechanism or a new unrelated correction need.

Measured comparison at `c4b6297`, using ignored
`build/coordinator_lock_diagnostic.py` over the existing real loopback retry
fixture, with the repository supervisor-cleanup fixture and JUnit stdout capture:

| Variant | Per-case largest lock wait (seconds) | Per-case largest lock hold (seconds) | Reconciliation cycles | Result |
| --- | --- | --- | --- | --- |
| Unchanged baseline | 2.991, 9.153, 15.575 | 0.161, 0.205, 0.145 | 166, 399, 368 | 3 passed; one wait exceeded the HTTP timeout |
| Ignore wakes from passive admission waits only | 0.112, 0.105, 0.085 | 0.124, 0.157, 0.176 | 73, 73, 75 | 3 passed |

Receipts: `build/coordinator-lock-timing-baseline.xml` and
`build/coordinator-lock-timing-passive-wait.xml`. The 15.575-second wait overlaps
271 completed reconciliation cycles, with no cycle longer than 0.145 seconds.
The baseline completion waiter set the wake event 314 times in that case; the
longest measured authority connection scope was approximately 0.011 seconds.
This demonstrates repeated lock reacquisition under reader-driven wakeups, not
one 15-second authority read. It does not identify every possible source of
future coordinator latency or prove the original uninstrumented timeout's entire
causal history.

Selected minimum correction: remove `_wake.set()` from `LocalDaemon._wait` and
`LocalDaemon.wait_admission`, leaving their reads, revision/terminal decisions,
timeouts, and polling interval intact. `wait_operation` is already passive.
Keep `_serve`, its periodic wait, all mutation-driven wakeups, `_cycle_lock`,
replacement/reload guards, authority transactions, scheduling, and release logic
unchanged. No new lock, queue, condition variable, sleep/backoff policy, public
option, or schema is required. Background reconciliation is started independently
by `LocalDaemon.start`; waiting is observation, not the scheduling driver.

The deterministic regression must exercise a nonterminal poll in each affected
wait API and prove that observation does not set the reconciliation event, then
still returns the appropriate changed/terminal/timeout result. Exercise the actual
service loop's periodic progress and existing mutation wakeups without lengthening
production/test deadlines. Retain the real loopback lost-response success and
cancel-before-grant cases and run adjacent session/replacement, daemon production,
and final full gates. Complete the retained retry candidate's rejection/exhaustion
coverage using existing retry/retention owners. Independent plan/startup review
precedes one executor for this approved amendment and the already reviewed resource
policy; independent implementation review covers both plus the retained candidate.

### Approved Scheduling-Only Policy Amendment

The maintainer supplied an approved Alpine SIF, verified to contain `sh`, `awk`,
and `cat`, then confirmed that host settings cannot be changed. Its SHA-256 is
`2ee9ccf77bea0f95bfa9274585bf30cea6976e4a5e709ece4243e19eef08f99e`.
Ordinary container execution succeeds. The existing resource acceptance hook
fails before payload execution because rootless cgroups require a user D-Bus
session. The receipt is `build/container-resource-acceptance-local-sif.xml`.
This is a real failed enforcement attempt, not an absent-image skip. Neither
environment-variable workarounds nor host administration are an accepted remedy.

On 2026-09-07 the maintainer approved separating scheduling requests from direct
CPU/RAM enforcement, retaining managed coordinator/agent execution and GPU
behavior. Evidence tree: the active Phase 2 worktree at `ecbb497`; clean before
this docs amendment; published develop remains `43b911f`. Original checkout
preservation hashes remain unchanged. This is an explicit behavior amendment,
not silent fallback or a fault-correction budget reset. Coordinator authority
comes from its separately approved bounded amendment above.

Reuse `ApptainerExecOptions` with one string field, `cpu_memory_enforcement`:

- `runtime` (default): retain the existing CPU/memory CLI mapping, exact runtime
  representability checks, host-dependent capability caveat, and failure on a
  rejected launch. The name describes a request to the runtime, not proof of
  observed enforcement. Never retry automatically without the requested flags.
- `scheduling_only`: explicitly omit only direct `--cpus` and `--memory` flags.
  Preserve the complete effective `ResourceRequest` and container intent for
  planning, reservations, provenance, and existing release behavior. Validate
  canonical CPU/memory semantics in both modes; runtime-parser representability
  is relevant only when generating limits. This policy neither reserves capacity
  for unmanaged direct calls nor introduces a scheduler.

The field belongs under the existing `adapter_options.apptainer` or
`adapter_options.singularity` surface, composed through existing runtime profiles.
Keep current alias precedence and stage overrides. Reject unknown policy values;
do not add a new namespace, environment variable, hostname detector, registry,
resource kind, worker schema, or automatic compatibility fallback. Existing
GPU projection must retain the field while leaving visibility and redaction
semantics unchanged. SLURM still owns CPU/memory enforcement on its actual route;
this direct policy never disables scheduler requests or enforcement.

All configuration-aware preflight/capability diagnostics and executor provenance
must reflect the effective policy: scheduling-only CPU/RAM is `not_enforced`,
with a visible warning explaining that requests remain scheduling/accounting
intent. Static executor descriptors may describe available mapping support but
must not masquerade as evidence for the selected policy. Reuse existing adapter
merge/resource resolution and keep runtime imports lightweight. Preflight must
use the production command mapping with the effective options, including authored
container-intent fallback. Missing-worker-result remedies must depend on emitted
limit flags, not merely on retained resource entries. Preserve full nested error
context and existing runtime diagnostics.

Example of the approved future profile (not executable on the current tree):

```yaml
runtime_profiles:
  scheduling-only-singularity:
    executor: singularity
    adapter_options:
      singularity:
        cpu_memory_enforcement: scheduling_only
```

Compose the image and project-specific settings separately. The checked-in
example must remain generic, with no host identity, private paths, credentials,
datasets, CUDA device tokens, or modifications to root/project `.env` files.

Acceptance is split by actual behavior. Scheduling-only execution requires a
real, bounded shell payload through the production command builder using the
approved SIF, nonempty CPU/memory intent, absent limit flags, and truthful
metadata. It does not assert unlimited inherited cgroups or prove a scientific
experiment completed. Retain the separate, fail-closed runtime-limit hook
unchanged in purpose. Its failed local receipt remains visible; positive
enforcement acceptance is deferred to a compatible approved host. The maintainer
accepted this separation, so unavailable hard-limit proof alone no longer gates
the scheduling-only deployment, but cannot be recorded as an enforcement pass.

Offline coverage must cross profile composition, effective stage options,
command generation, retained intent, preflight/capability diagnostics, executor
failure remedies, GPU projection, and SLURM ownership. Use a composed-profile
integration regression and a focused existing managed-placement/reservation
fixture to prove that disabling direct limits does not erase resource demand or
change release conditions. No production queue change is part of this amendment.
Whole-tree local gates and independent implementation review remain mandatory.

Independent review accepted the policy design and its source/validation ownership.
The manager corrected the stale FQ/DQ range and clarified the earlier pre-grant
retry scope. The separately approved coordinator amendment now addresses the
startup stop without resetting the consumed 3/3 correction budget. An in-memory public `merge_run_options` probe
confirmed that the existing profile surface retains the proposed adapter payload
and CPU/memory demand without modifying its input; this is reuse evidence, not
implementation or live acceptance of the policy.

### Historical Brief Reconciliation

The original brief describes whole-run controller cycles and static assignment,
not the newer per-stage scheduler contract. Relevant outcomes are concurrent
progress, temporary-capacity deferral, exclusive bindings, fenced ownership,
cleanup/release, and restart conservatism. Current `assignments.py`, queue
controller/adapters, and daemon/agent execution own those outcomes. Preserve
the newer distinction between logical terminal state and physical settlement:
the brief's shorthand "process exits -> release everything" is not a sufficient
release rule for a descendant-owning managed route. Its proposed type names,
default concurrency choices, and implementation slices are historical evidence,
not new acceptance criteria.

### Baseline Validation And Independent Disposition

Fresh targeted baseline run covers runtime options/profiles, CLI run/plan/
validate, plain serialization, direct Apptainer, executable SLURM rendering,
runtime-profile and SLURM planning integration, CLI dry-run E2E, assignments,
agent supervisor, daemon production, and queue lifecycle. Result: **236 passed
in 344.84 seconds** at the unchanged source revision above, using the worktree's
locked `.venv/bin/python -m pytest -q`. This is targeted baseline evidence, not
the final implementation gate or a live-container receipt.

Independent reviewer: **pass for baseline dispositions and Phase 1 port**, with
A-1, A-9, and A-10 confirmed and assigned to bounded owners. The reviewer
independently checked source, tests, and docs, and reproduced legacy root-exit
with a live inherited-group child. It distinguished the current resident daemon
from the legacy adapter rather than certifying all managed routes together.
The manager accepted these findings and verified the referenced owner paths.
Each finding must name a supported producer,
violated accepted contract, consequence, and smallest correction. Optional
hardening and unrelated upstream defects remain explicitly separate.

A synthetic in-memory composed-config probe through public `main(["validate",
..., "--check-targets", "--format", "json"])` reproduced A-1 with the locked
dependency: the outer stage plus generic service, pipeline metadata, factory-init
target, and stage-config target were all constructed; exit 0, target count 5.
Only the outer stage and generic service should be independently constructed
(count 2). The outer factory receives frozen mapping data under the existing
stage-spec contract, not necessarily a mutable `dict`; regression fixtures must
check mapping contents and construction events, not change that contract.
Composition was replaced with an in-memory fixture in this diagnostic only;
the implemented regression must also exercise authored config composition.

A separate real-Bash probe of `render_slurm_script` at the baseline revision
confirmed A-9 without submitting a job: request two GPUs; `0,1` passes both
validators; `0,1\n` and `0,1\ninvalid` fail Python validation but the generated
script exits 0 and reaches a harmless `/usr/bin/true` launcher. `0,1\r` already
fails both. The reachable producer is an inherited or prelude-authored
allocation environment. Add a bounded complete-value rejection rather than a
new GPU parser/registry or new allocation semantics.

A fresh real-process probe of `SubprocessApptainerExecRunner` reproduced A-7:
an owned Python parent launched a non-detached child, then exceeded a 0.2-second
deadline. The runner returned `timed_out=True` while the child remained alive.
The fixture used a process-local Linux subreaper and reaped that child after its
bounded 0.8-second lifetime; no fixture process remained. This proves a runner
gap, not that every actual Apptainer invocation leaks children.

## Minimum Useful Change

The first independent increment is a validation-only projection that omits
stage-owned subtrees from generic target construction. The second extends
existing container resource intent into explicitly selected runtime mapping or
scheduling-only execution. One option in the existing adapter is needed because
removing resource declarations also removes scheduler information. Neither
increment needs a public registry, durable record, extra config namespace, new
dependency, or queue change. Timeout support is the third increment and cannot inherit an unproven
process-cleanup guarantee from either existing command runner.

## Functional Requirements

| ID | Required behavior | Scope / dependencies | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | Check outer factories and unrelated generic targets, keeping stage config, factory init data, and pipeline metadata inert for generic traversal | Preserve opt-in warning, counts, static default, and input immutability | Public CLI constructor markers; invalid factories and generic targets | merged, PR #277 |
| FR-2 | Explicitly select runtime CPU/memory limits or scheduling-only execution without losing resource intent or changing GPU/SLURM ownership | Current resource contracts; runtime mapping stays default; no implicit allocation or fallback | Policy composition, retained intent, conversion/rejection, truthful diagnostics, separate live receipts | implemented; smoke, independent review, and full gates passed |
| FR-3 | Deadline, bounded termination/escalation, observation/reaping, primary and cleanup context; no success after timeout or unresolved containment | Resolve stage versus outer cleanup owner; no capacity release solely on launcher exit | Real child-process fixtures and suitable container check | design investigation |
| FR-4 | Preserve run roots, GPU redaction/grammar, serialization, managed deferral/exclusivity/release/restart | Current published behavior, not old patch parity | Baseline audit and regression suites | baseline audit accepted; bounded corrections assigned |
| FR-5 | Independent baseline and implementation reviews; local validation; ordered PRs and merges to develop; final integrated review | Preserve original checkout, refresh base between phases | Exact revision receipts and remote merge evidence | required |

## Functionality Agreement

| ID | Requirement IDs | Decision | Evidence / tradeoff | State |
| --- | --- | --- | --- | --- |
| FQ-1 | FR-1 | Stage factory checking owns factory construction; generic checking cannot interpret stage-owned data | Trusted targets outside those areas still run on explicit consent | locked |
| FQ-2 | FR-2 | Preserve current positive integer CPU/count and positive memory binary-unit contracts | Runtime support for fractional CPUs does not broaden Loom's resource contract | repo-resolved |
| FQ-3 | FR-3 | Supported children obey containment ownership; arbitrary detaching/malicious processes are not a sandbox guarantee | Stop for a materially broader ownership redesign; earlier increments may land | locked |
| FQ-4 | FR-4, FR-5 | Retain corrected upstream behavior and independently review new changes | More evidence than a patch copy, no upstream overwrite | locked |
| FQ-5 | FR-2, FR-4, FR-5 | Explicit scheduling-only CPU/RAM policy; no host changes; retain requests and managed scheduling; defer unavailable positive hard-limit proof separately | Running work can exceed declared resources; no silent downgrade or claim of OS isolation | maintainer approved |
| FQ-6 | FR-4, FR-5 | One additional cause-backed coordinator-responsiveness amendment, with unchanged safety contracts and independent review | New measured wakeup/lock evidence; no general correction-budget reset | maintainer approved |

## Behavior Baseline

Default validation remains static. `--check-targets` remains permission to import
and construct trusted outer factories and other applicable generic targets; it
is not globally side-effect-free. Stage constructors themselves can execute
project code. Filtering must not mutate the composed config or alter the
factory check's argument semantics.

Resource requests are logical requirements, not resource allocation. Direct
CPU/memory options request host-runtime enforcement; generation alone proves no
cgroup enforcement. Runtime mode rejects unsupported mappings; explicit
scheduling-only mode retains intent without mapping CPU/RAM limits. SLURM-owned
limits stay separate. A successful process exit cannot override timeout or
unresolved cleanup evidence.

## Minimum Design

- Validation: build a detached generic-check view in the CLI adapter, omitting
  the pipeline-owned mapping (including metadata, stage config, and factory init);
  retain the existing stage checker and unrelated generic checking. The Phase 1
  card records the source-backed ownership rationale. No Weave change or
  alternate instantiation mechanism.
- Resources: extend direct Apptainer command construction over existing
  `ContainerResourceIntent`. Reuse `ResourceRequest` semantic validation;
  conversion owns exact representability in runtime units. Preserve independent
  GPU projection and metadata redaction. Update current capability/preflight
  owners and docs, not a new registry. Preserve the executor's existing effective
  intent precedence: nonempty runtime resource entries replace authored
  container intent; otherwise authored `ContainerOptions.resources` survives.
  Preflight must check the same effective CPU/memory intent as command generation,
  including that supported fallback, rather than inspecting runtime entries only.
  Scheduler routes retain their own resource validation and enforcement facts;
  a container runtime name does not imply direct execution. Runtime byte
  representability includes the supported external parser: SingularityCE 3.10.4
  uses [go-units 0.5.0](https://github.com/docker/go-units/blob/v0.5.0/size.go),
  which parses bare byte strings through float64 before int64. Reject values
  that would change through that conversion. Live acceptance must inspect the
  payload's actual cgroup for runtime-limit acceptance, and explicit opt-in
  without prerequisites must fail actionably rather than count as passing
  evidence. Apply the approved scheduling-only amendment above at these same
  owners, with separate live acceptance and no claim of enforced limits.
- Timeouts: investigation must identify the launch containment mechanism, worker
  owner propagation, supported child obligations, and positive-cleanup proof.
  Agent/SLURM supervision is evidence of needed ordering, not permission to
  import queue internals into the low-level container runner.
- The direct worker command currently enters `cli/stage.py`, then
  `run_stage_worker`, `execute_stage_worker_request`, and
  `reconstruct_stage_execution_request`, which explicitly constructs a
  stage-owned context. A process-group-only redesign must not leave that fact
  unchanged while assuming stages no longer establish their own groups.
  Conversely, merely labelling the worker outer-owned creates no containment.
  Investigate runtime PID-namespace supervision and/or a narrowly propagated
  launcher-owned context together with the actual runtime's process topology.
- Check composition with historical `LocalQueueDispatchAdapter` as well as the
  newer resident supervisor: introducing a new session beneath an existing
  enclosing group can escape its cancellation boundary. A material cross-owner
  redesign must pause the timeout phase for a separate maintainer decision.
- No changes to scientific fingerprints, run-root defaults, serialized worker
  schemas, remote submission, or public ownership enum are assumed.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Detached validation projection | Generic traversal constructs stage-owned nested targets | Skip only outer path, which does not stop traversal | keep |
| CPU/memory argv mapping plus explicit policy | Default mapping is implemented, but the available host rejects rootless limit setup | Erasing requests loses scheduler demand; implicit fallback violates intent | keep existing default; one adapter policy for approved scheduling-only execution |
| Container lifecycle boundary | Launcher-only timeout does not prove descendant cleanup | Reuse existing immediate-child kill, which is insufficient | design required |
| New registry, daemon supervisor import, durable cleanup ledger | No demonstrated need for these particular mechanisms | Extend existing owner at its boundary | defer |

## Design Agreement

| ID | Requirement IDs | Decision | State |
| --- | --- | --- | --- |
| DQ-1 | FR-1 | CLI owns validation projection; source config and stage constructor semantics stay unchanged | locked |
| DQ-2 | FR-2 | Positive integer CPUs; memory converts exactly to integer bytes; no silent rounding, zero-as-unlimited, or attribute reinterpretation | repo-resolved |
| DQ-3 | FR-3 | Close ownership and mechanism investigation before enabling timeouts or advertising enforcement | open investigation |
| DQ-4 | FR-5 | One phase worktree/PR each; independent correctness review and exact-tree local gates; final integrated review | locked |
| DQ-5 | FR-2, FR-4 | One existing adapter field; reuse merge/validation/provenance; no queue, host, or durable-schema change; independent amendment review | policy implemented; namespace and implicit-stage warning findings independently closed |
| DQ-6 | FR-4 | Make the two admission waits passive; retain locks, periodic reconciliation and mutation wakeups | approved; independent combined startup review passed without findings |

## Expanded Design Review

The independent scheduling-only plan/startup review found no policy-design blocker.
The separately approved coordinator amendment and combined Phase 2 startup passed
independent review without findings, including measured evidence, the passive-wait
correction, retained safety contracts, and proportional validation.
Historical correction counts remain intact. Timeout review remains pending until its minimum design is
supported by source and runtime evidence. A new ownership framework or materially broader public contract must
be presented to the maintainer separately, as required by the approved draft.

## Examples And Validation

| Invariant | Authoritative owner / boundary | Minimal coverage |
| --- | --- | --- |
| Outer checked, nested data inert | CLI adapter / trusted constructor boundary | Harmless marker constructors through public CLI, invalid outer and unrelated targets, exact counts/warnings, no mutation |
| Runtime mode: two CPUs and 512 MiB become `--cpus 2 --memory 536870912` | Resource validator and direct argv conversion | Units, positive/integer constraints, unrepresentable bytes, flags before image, no-request/default path |
| Scheduling-only mode preserves requests, omits CPU/RAM flags, reports no enforcement | Existing option/merge, mapping, metadata and diagnostic owners | Composed profile, stage override, unchanged intent/reservation, invalid policy, GPU/SLURM preservation, real shell smoke |
| Flags do not prove host enforcement | Runtime CLI/cgroups and preflight docs | Runtime rejection remains a failed receipt; scheduling-only live pass is separate; positive hard-limit proof deferred to a compatible host |
| No successful admission following timeout | Executor's outcome and cleanup boundary | Result written before deadline, root-first exit, children, TERM resistance, interruption, cleanup uncertainty, normal success |
| No upstream regression | Existing serialization/runtime/GPU/managed owners | Targeted baseline plus phase-relevant and final integrated suites |

Combined tests are required where outcomes interact: timeout and early result,
parent exit and surviving child, cleanup failure and original timeout, or GPU
projection and protected metadata. No speculative Cartesian matrix is required.
Final commands for each implementation phase are `make validate-pr` and
`make test-summary`, with evidence invalidated by relevant tree changes.

## Phase Shaping

Approved ordering is audit, validation guard, CPU/memory mapping (including
A-9), lifecycle-safe timeouts, then integrated review. The compact manifest
links three phase cards. Phase 1 is merged after independent review and both
required gates. Phase 2 has committed and independently reviewed its offline
implementation and both localized test corrections. Its latest full gate fails
on A-13; earlier passing receipts cannot replace fresh corrected-tree validation.
The newly approved scheduling-only policy requires its own implementation and
live acceptance; unavailable hard-limit proof remains explicit deferred evidence.
Phase 3's card explicitly forbids execution until its lifecycle design is
reviewed, including the separately identified legacy A-10 correction. This
staged readiness follows the maintainer's explicit instruction that earlier
increments may land while a broader timeout design is presented separately.
The full objective remains incomplete until all accepted outcomes are achieved.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and scope authorized | Maintainer-supplied selective-port objective | pass |
| Dirty checkout preserved and fresh locked baseline | Revision and preservation receipts above | pass |
| Upstream audit independently accepted | Independent source/contract review; 236 passing baseline tests; A-1/A-9/A-10 dispositions recorded | pass |
| Minimum timeout design justified | Ownership investigation in progress | pending |
| Detailed phase traceability and startup readiness | Phase 1 merged; FR-2 maps to the prepared resource packet and offline implementation; live acceptance and timeout design remain explicit gates | pass for Phase 2 offline scope only |
| Required reviews and final checks defined | FR-5 and validation table | pass |
| Scheduling-only policy design | Independent review accepted existing owners, explicit modes, retained demand and separate live receipts; minor wording corrected | pass |
| Phase 2 product startup | Separate bounded amendment approved; measured passive-wait correction and combined startup independently accepted without findings | pass |
| Phase 2 implementation validation | `04443ed`: 80 focused tests, one scheduling-only SIF smoke, both full gates; summary 2,994 passed / five optional skips; independent warning closure accepted without findings | pass |

Gate result: Phase 1 merged; scheduling-only policy design approved and independently
reviewed. Coordinator amendment is independently accepted. Phase 2 policy review
identified diagnostic gaps; `6b831e7` fixes namespace selection and explicit/global
fallback warnings. The separately approved `04443ed` correction closes the mixed
explicit/implicit-stage path at the existing mapping owner without inventing
runtime limits. The phase card records focused evidence and the newly approved
bounded verification. Independent closure and both fresh full gates passed;
Phase 2 is ready for PR/merge checks.
Historical correction counts are not reset. Phase 3 remains
unapproved for product execution pending its expanded design review.

## Decisions And Deferrals

The host has SingularityCE 3.10.4; availability/version alone is not a real
container acceptance receipt. The official
[SingularityCE 3.10 resource guide](https://docs.sylabs.io/guides/3.10/user-guide/cgroups.html)
and [Apptainer resource guide](https://apptainer.org/docs/user/latest/cgroups.html)
document CPU/memory flags and host cgroup requirements. Non-root enforcement
depends on delegated unified cgroups v2 with compatible systemd/runtime setup.
Do not change host administration or claim runtime enforcement from help output.
Unavailable runtime checks remain visible limitations, not passing results.

Superseded dirty source retirement, the old rphys Stage 81 goal, and unrelated
roadmap work remain outside this stage. Refresh published develop and reassess
overlapping source owners before every implementation phase.
