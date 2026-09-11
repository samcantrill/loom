# Roadmap Stage 41 Planning: Unified Run Lifecycle And Agent Execution

Status: approved; nine-phase implementation baseline
Roadmap stage: 41
Evidence base: published develop `25d97f50d66f44273bf979a5488a312e7f1a15d2`.
Authoring tree: `/nas/home/can134/work/loom-worktrees/stage-41-startup-plan`,
branch `agent/stage-41-startup-plan`; clean on entry. Preserve unrelated worktrees.
Planning route: published-source refinement and requested startup-readiness review.
Current gate: reviewed amended packet published; startup verified in the stage worktree
Blockers: none; see the manifest readiness receipt and Phase 1 startup record.
Maintainer approval: behavior and nine-phase structure approved on 2026-09-10;
the maintainer requested the reviewed refinements and startup review on 2026-09-12.

This is the authoritative behavior/design plan for this stage. The discussion
brief is an explanatory entrypoint. Source/test evidence describes the baseline;
new APIs and behavior below are planned, not available runtime functionality.

## Current State

| Gate | Result | Remaining action |
| --- | --- | --- |
| Functionality/design | Agreed behavior; independent design pass | None |
| Validation/phases | Nine bounded cards; contracts and validation owners retained | None |
| Plan quality | Original review retained; current amendment review owned by the manifest | [Quality Gate](implementation-plan.md#quality-gate) |
| Approval/execution | Maintainer requested whole-stage implementation on 2026-09-12 | Execution state and evidence at the [implementation manifest](implementation-plan.md) |

## Evidence And Scope

Source paths may omit `src/loom/`; other paths are repository-relative.
Directly inspected source outranks historical docs.

| Source / area | Current finding | Related requirements |
| --- | --- | --- |
| `src/loom/cli/run.py::_run_pipeline`, `pipeline/execution/runner.py` | Ordinary execution invokes a separate `PipelineRunner`; offline adapter is another runtime path | FR-41-01/13 |
| `queue/local_daemon.py`, `local_daemon_execution.py` | Durable managed admission, reconciliation, local-agent composition and supervisor exist; local retained-work shutdown is not a global idle predicate | FR-41-02..05/09 |
| `queue/deployment.py`, `agent_session_transport.py` | Explicit protected coordinator/local/outbound-agent config; independent remote service and client role boundaries | FR-41-02/03/06 |
| `queue/managed_local_preparation.py`, `pipeline/stores/coordinator_authority.py` | Exact composed publication exists but excludes Slurm profiles/non-embedded authority; embedded initializer starts run at RUNNING | FR-41-07/08 |
| `_remote_stage_execution.py`, `_agent_process_supervisor.py` | Resident requests, process containment, durable reports and outbox are reusable | FR-41-06/09 |
| `pipeline/executors/slurm/ready_stage.py`, `queue/slurm_ready_stage.py`, `slurm_bootstrap.py` | Coordinator-side exact submission owner, marker reconciliation, restricted grant/start bootstrap and result relay exist | FR-41-10..12 |
| `diagnostics/run_inspection.py`, native inspection contracts | Owner-labelled state, freshness, bounded diagnostics and terminal settlement | FR-41-09/12 |
| `queue/{client,service,controller,local,slurm}.py`, `pipeline/execution/{continuation,slurm_controller,offline_adapter}.py`, `pipeline/sweep/dispatch.py` | Separate historical whole-run/Slurm/offline/sweep dispatch consumers need conversion/removal | FR-41-01/13/14 |
| [Stage 40](../stage-40/implementation-plan.md) | Delivered native client, shared/staged preparation, thirteen MCP tools and four operational skills; closeout published at `39a48b0` | FR-41-01/07/14 dependency |
| [Test harness](../../../tests/README.md), package, daemon, agent, authority, Slurm and sweep tests | Existing invariant owners and real-process/fake-scheduler seams | All validation |

Outcome: one configured `run` starts/reuses the required services, prepares and
admits work, executes stages through agents, answers queries, survives observer
loss, reconciles restart, then stops only services whose lifetime it owns.
Cold local, persistent local, fleet and connected Slurm share those meanings.

Stage 40 is delivered. Its compatibility and limited preparation family describe
its delivery boundary. Stage 41 extends that publisher, updates its MCP/skill
consumers and removes old execution APIs. Preserve existing transport, capture,
report and finalization owners where their contracts fit.

### Published baseline and amendment ownership

The source base includes Stage 40 plus ready-stage containers (#299), safe
execution observations (#301), serialized publication and explicit failed-admission
retry (#305), and verified native worker completion/output replay (#306). These
are source assumptions for the requested readiness review, not new runtime test
receipts. Stage 40's live Codex and physical NAS limitations remain unqualified.

| Published contract / evidence owner | Observed baseline | Amendment owner |
| --- | --- | --- |
| `queue/preparation.py`, `src/loom/preparation.py` | Five-field request, version 1 child input/report, shared and staged capture; one qualified preparation installation | P1 extends invocation controls through child/check/report/publication |
| `queue/_preparation_operations.py`, `managed_local_preparation.py` | Dedicated preparation table; recovery forces embedded authority and clears Slurm profiles; same-URI publication is process-serialized | P1 retains selected publication bindings; P2 adds continuation and separate cancellation facts |
| `queue/local_daemon.py`, `queue/coordinator_authority.py`, `pipeline/stores/sqlite_authority.py` | Explicit `retry_failed_revision` is distinct from submit replay; retry authority capability is currently embedded-only | P1 keeps truthful pre-start state on explicit retry; P2/P7/P8/P9 preserve explicit retry and its capability boundary |
| `queue/local_daemon.py`, `_coordinator_control.py`, `_coordinator_transport.py` | Coordinator root 13; agent root 12; `daemon-control-v1`; 64 KiB preparation projection, 1 MiB control response, 30-second request budget and 25-second observation bound | P1/P2/P3 own changed formats and bounded native composition; P8 consumes them |
| `_remote_stage_execution.py`, `queue/slurm_ready_stage.py`, `pipeline/executors/slurm/ready_stage.py` | Resident bundle 4; Slurm delivery 4; ready-stage request 4 (retained native 3); remote report 3 preserves execution metadata; aggregate artifact transfer bound 64 MiB | P4/P5/P6 retain execution evidence and existing transport bounds |
| `_agent_process_supervisor.py`, `_managed_local.py`, `local_daemon_execution.py` | Supervisor schema 3 qualifies successful completion; native parent owns `managed_successful_exit` and exact `managed_output_predecessor` | P4 preserves native success proof; P6 preserves normal fenced commit/replay and separate scheduler containment |
| `mcp/__init__.py`, `mcp/_server.py`, `skills/loom-*`, `tests/README.md` | One selected client, thirteen tools, submit-only run skill; isolated `test-mcp-extra` lane is delivered | P8 binds one protected deployment per server and adds native run/cancel delegation |

Phase cards own the detailed amended contracts and discriminating checks. Their
existing FR/DQ/VAL allocations and nine merge boundaries remain unchanged. The
format numbers above are observed source facts, not proposed new version numbers.
Each phase changing a public/durable shape records its version decision with the
producer and reader. Incompatible interpretations fail before mutation; preserve
unchanged compatible shapes. No stage-wide migration, new job database, larger
artifact transport or authenticated-authority retry capability is added by this
refinement. Operators settle old-version work before incompatible replacement.
Non-goals: compatibility adapters or old-root migration, offline queued starts,
automatic remote provisioning/SSH, environment installation, scientific choices,
multi-agent distributed stages, automatic allocation acquisition, standalone
allocation-only orchestration, transparent Slurm requeue, HA or lost-state repair.

## Minimum Useful Change

One managed owner replaces production execution bypasses. Preserve pure graph,
planning, artifact, execution-only and numerical behavior at existing owners.
One high-level facade over Stage 40 client operations is needed because the
current CLI/Python caller otherwise must operate services and admissions itself.
Agent backend handles are justified by two current consumers: supervised local
processes and externally scheduled Slurm jobs. No generic scheduler/plugin
framework, new job index or second lifecycle database is justified.

## Functional Requirements

| ID | Required behavior | Boundaries / exclusions | Validation | State |
| --- | --- | --- | --- | --- |
| FR-41-01 | One CLI/Python run orchestration composes ensure, prepare, submit and observe; all production execution uses it or its native coordinator operations | No direct/offline/full-run Slurm bypass | VAL-41-01/12 | agreed |
| FR-41-02 | Automatically initialize a configured fresh local deployment or reopen the same stopped owner; attach to compatible live owners | Known lost/conflicting roots fail; no remote/local fallback | VAL-41-02 | agreed |
| FR-41-03 | Agent service spans attempts, advertises authorized capacity/backend capabilities and starts/reuses configured local roles | Client need not be a worker; existing remote agents connect outbound | VAL-41-03 | agreed |
| FR-41-04 | Track service lifetime individually; preserve borrowed persistent roles; shared run-owned services outlive all accepted work | Persistent state is retained after process shutdown | VAL-41-04 | agreed |
| FR-41-05 | Default run waits through terminal settlement and owned-service cleanup; detach/Ctrl-C/EOF leave work owned; cancel is explicit | Wait timeout is not cancellation; cleanup errors do not rewrite committed results | VAL-41-04/05 | agreed |
| FR-41-06 | Every stage assignment runs through an agent backend: supervised native/container or asynchronous Slurm | One allowed submit profile is not local compute capacity | VAL-41-03/06/08 | agreed |
| FR-41-07 | Use assigned preparation and one exact publication owner for supported embedded/authenticated authority and Slurm profiles | Existing environments only; no silent recomposition/source deployment | VAL-41-07 | agreed |
| FR-41-08 | Prepared/admitted work does not claim a running worker; retain explicit run/attempt/admission and result identities | Reuse/skip paths need not launch a process | VAL-41-01/07 | agreed |
| FR-41-09 | Restart same retained owners, reconcile capacity/work/results, and preserve current-fence publication/cancellation rules | No blind resubmission, newest-timestamp overwrite or inferred filesystem success | VAL-41-05/09/10 | agreed |
| FR-41-10 | Agent owns one exact Slurm submission operation, bounded scheduler observation and cancellation | Coordinator owns assignment/lifecycle; no second submitter | VAL-41-08/09 | agreed |
| FR-41-11 | Retain an attempt-bound Slurm result/manifest on qualified durable shared storage before notification; ingest after compute/coordinator exit | No arbitrary directory scan, unacknowledged deletion or duplicate finalizer | VAL-41-10 | agreed |
| FR-41-12 | Query preserves coordinator, agent, scheduler, result and cleanup evidence with freshness | Missing squeue/accounting is unknown; scheduler completion is not Loom success | VAL-41-09/10/11 | agreed |
| FR-41-13 | Hard-remove obsolete execution APIs, configuration, command paths and unused owners; no deprecation aliases | Preserve output bytes; settle old-version work before operator cutover | VAL-41-12 | agreed |
| FR-41-14 | Sweeps, examples, docs and MCP/skills consume the unified native contract; base imports stay cheap | Scientific expansion and optional dependencies retain their owners | VAL-41-01/12 | agreed |
| FR-41-15 | Connected, permitted-site Slurm is first HPC scope; new stage starts require coordinator grant | Already-granted work continues; no automatic allocation/requeue/failover | VAL-41-09/11 | agreed |

## Functionality Agreement

| ID | Requirements | Decision and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- |
| FQ-41-01 | 01/13/14 | User explicitly selected one run and hard swap without compatibility | Old execution inputs/APIs cease working | locked |
| FQ-41-02 | 02..06 | User distinguished persistent agent service from per-attempt workers; cold start and borrowed-service lifetime are explicit | Bootstrap/reconciliation becomes required infrastructure | locked |
| FQ-41-03 | 07..12 | Agent owns backend execution and retained evidence; coordinator commits through authority | Additional agent Slurm protocol, less duplicated orchestration | locked |
| FQ-41-04 | 15 | User narrowed HPC to reachable coordinator and accepted recommended grant rule in the affirmed behavior | Queued jobs cannot obtain a new grant during outage | locked |

## Behavior Baseline

### Roles, startup and service lifetime

A coordinator service decides readiness/placement and owns assignments. An
agent service advertises resources, starts and observes backend handles. Stage
workers execute one attempt. A submission helper's exit reports command outcome,
not stage completion. Native/container workers remain under an owned supervisor.
Authority owns accepted transitions/fences/output commits; it can be embedded.
Daemon means a background hosting process, not another scheduling role. Worker
agent means agent service; co-hosting does not erase the ownership boundaries.

`run` resolves an explicit deployment selection. Its launcher can create a
configured fresh local bundle, reopen its existing root, attach to a live owner,
or start a configured absent local agent. It never scans the network, launches
remote infrastructure or silently runs locally after remote connection failure.
First creation uses the existing atomic initialization owner; restarting an
expected identity is open-only. Protected bindings and expected coordinator ID
guard reconnect before any mutation. Configuration selects existing installed
profiles and authorized agent/site capabilities.

Concurrent starters converge through role locks. Startup retains a bounded
handoff until the first prepare/submit request is accepted or abandoned. Global
quiescence and acceptance serialize: work is accepted with a live owner or
receives a retryable reconnect result. Pending preparation, no-capacity waiting,
Slurm jobs, unacknowledged results and unresolved assignments prevent shutdown.
Completed history and idle connected agents alone do not.

Lifetime is per service: borrowed persistent roles remain; created run-owned
roles stop after all attached runs settle; a configured persistent role stays
even if this command started it. Mixed lifetimes require independently operated
roles; co-host only roles whose lifetime matches. Use existing outbound-agent
transport for a separately operated local agent when needed, with explicit
credentials, rather than dynamically replacing a live embedded-agent binding.

Detached services retain lifetime ownership when the client exits. Waiting run
returns only after its terminal work and cleanup responsibility settle. Cleanup
refusal is a separate result axis. Explicit cancel records intent and observes
containment; it is not implied by Ctrl-C, EOF, timeout, or closing the client.
If another run still needs a shared service, a durable retained-for-other-work
decision completes this caller's cleanup responsibility without stopping it.

### Preparation and execution

Assigned preparation returns checked composition; the coordinator publishes it
without recomposition. P1 carries sparse invocation controls through the same
child/check/report boundary and retains the selected authority/profile bindings
for restart. Preparation still uses a qualified resident worker independently of
the target's resident or Slurm route. Extend creation/publication through the selected
authority and route; preserve snapshots, requirements, resource semantics,
selectors, reuse, retry, logs/events and provenance. Run starts CREATED and is
PLANNED after publication; the first confirmed executing stage moves it RUNNING.
A run resolved entirely by reuse/skip may terminalize without RUNNING. Update
readiness/transition consumers at their owner, not just CLI labels.
Accept the requested prepare-to-admission continuation durably before returning
from public run acceptance. A client lost during preparation must not strand a
requested run as preparation-only. Reuse the preparation operation machinery and native
admission replay; the client is an observer after this handoff. Early detachment
returns that operation reference even before a target admission exists.
Kind `prepare_run` applies at publication. Kind `run` applies only when its exact
admission is accepted, then run waiting follows execution. The named native
`cancel_run_operation` serializes suppression against admission, or delegates to
the exact already-accepted admission. Its own control operation exposes settlement;
retries cannot acknowledge cancellation and later admit the suppressed work.

Each assignment selects an agent plus authorized backend/profile. Native or
container starts a supervised execution-only worker. Slurm returns an external
handle that remains active after the helper exits. No worker recursively invokes
public run. Arbitrary live Python closures are not a supported persisted input;
project code is importable and parameters serializable.

### Slurm, restart and publication

Persist exact operation intent and SUBMITTING before at most one automatic
sbatch invocation. Agent alone owns that external-call record/outbox;
coordinator stores assignment intent and acknowledged evidence. Agent publishes
authorized submission capacity, not unallocated GPUs. Preserve one run stage
slot and site-profile outstanding quota without duplicate accounting across
agents. Slurm chooses/enforces the compute allocation.

Reopen exact handles after restart. Unknown submit discovers the stable operation
marker: one match repairs, zero remains unknown, multiple conflict. Poll squeue
and sacct with bounded calls/backoff; agent observations have accepted time and
freshness. Restarted coordinator reconciles acknowledgements through authority;
absence or newer timestamps never authorize replacement execution.

Bootstrap requires a current assignment/start grant before authored effects.
Granted work can continue during coordinator loss; ungranted work reconnects
with bounded waits and a site-configured bootstrap deadline. No transparent
requeue or offline-start permission is introduced. Cancellation first records
authority intent, suppresses an unstarted call or reconciles an uncertain call,
then cancels the exact discovered/running job and waits for containment.

Compute publishes a typed report plus manifest into a protected attempt-owned
shared result directory before notification. Submit agent reads only the bound
location, verifies assignment/fence, contained regular-file paths and content,
and forwards them to the coordinator/authority's ordinary finalizer. Publication is atomic with
manifest last; bounded declared files remain until final acknowledgement.
Scheduler COMPLETED without this result cannot become success. Result validity
does not by itself prove job/descendant containment or release; retain separate
evidence. Role SQLite storage remains subject to its local durability/locking
contract; shared artifacts are not an HA database mechanism.

Inside an already-granted allocation, eventual usage is the same command with
qualified allocated-resource/native/container profile and required srun binding.
It must not create nested sbatch work by accident. New allocation hosting,
multi-node identity and allocation acquisition are deferred; site qualification
is required before claiming this deployment works.

## Minimum Design

Reuse Stage 40's high-level `loom.coordinator` client. Add native deployment/run
composition above queue and diagnostics, exposed by `loom run CONFIG --deployment
PATH` and a lazy `loom.run` Python facade. Detailed request/receipt fields live
in the durable-run-operation phase card. MCP delegates to the same composition with one protected deployment selected at
server startup; run/query/cancel share its coordinator binding. Constructors remain inert. Client/run facade -> native application/transports -> coordinator
and agent owners -> authority/execution. Low-level owners never import CLI,
MCP, diagnostics or project code for orchestration.

Protected deployment selection references existing coordinator/agent configs,
connection identity and startup/lifetime policy. Add only creation binding and
bounded startup/lifetime ownership needed to prevent cold-start loss/races;
no ambient registry or per-client job database. Agent backend operations reuse
supervisor and ready-stage primitives. Moving Slurm submission ownership requires
an explicit agent-bound assignment and durable receipt protocol, not JSON
dispatch of arbitrary commands. Keep chosen schemas versioned and reject old
incompatible roots before mutation. Public request/receipt semantics, trust,
durability and cross-phase handoffs are fixed; private helper/file names and
local scheduling data structures remain implementation choices.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Native ensure/run composition | One caller path including cold start | Existing client alone cannot manage role lifetime | keep small facade |
| Per-service lifetime/start handoff | Concurrent runs and detached clients otherwise orphan/stop accepted work | Process-local client counting cannot cover accepted waiting work or observer loss | retain the attachment/handoff and quiescence decision in existing role/application owners; no second lifecycle store |
| Agent backend handle and Slurm journal ownership | Uniform local/Slurm execution and restart after helper exit | A blocking sbatch worker loses durable outcome | move the existing exact-operation mechanics to the assigned agent; coordinator keeps only assignment intent and acknowledged projection |
| Shared typed result ingestion | Compute can exit during coordinator outage | A callback/scratch directory may disappear | reuse current report/artifact shapes and coordinator finalizer behind one bounded manifest transport; no second finalizer |
| Parallel whole-run compatibility owners | User explicitly rejects compatibility | Reuse pure helpers and delete orchestrators | remove |
| Offline start, allocation provisioning, HA, generic plugins | No accepted present consumer | Explicit capabilities/deferred scope | defer |

## Design Agreement

| ID | Requirements | Decision / evidence | Tradeoff | State |
| --- | --- | --- | --- | --- |
| DQ-41-01 | 01/02/14 | Stage 40 native client below shared run/availability composition | Predecessor must be published first | locked |
| DQ-41-02 | 02..05 | Each role/application owner durably retains its startup attachment until admission and uses coordinator-serialized quiescence, including accepted waiting work, to stop only run-owned services; borrowed/persistent roles do not acquire run-owned cleanup | Independent mixed-lifetime roles need an explicit lifetime projection | review-resolved |
| DQ-41-03 | 06/10 | The assigned agent alone retains the exact Slurm operation and invokes/observes/cancels scheduler calls; coordinator retains assignment intent and acknowledged evidence but cannot submit | Extend agent offers/assignment protocol and relocate the existing journal owner | review-resolved |
| DQ-41-04 | 07/08 | One publisher, selected authority creation, truthful pre-start state | Update transition consumers atomically | locked |
| DQ-41-05 | 09/11/12 | Agent verifies and forwards only its bound manifest/report/artifacts; the coordinator/authority path remains the sole result finalizer and acknowledges durable commit before transport cleanup; identity and containment stay separate | Initial Slurm requires qualified shared storage | review-resolved |
| DQ-41-06 | 13 | Hard cutover completes only after consumers and dynamic targets move and the direct/offline/whole-run Slurm owners and exports are removed; no aliases or migrations | Operator must settle old work first | review-confirmed |
| DQ-41-07 | 15 | Reachable coordinator with grant-gated bootstrap; same-root restart | Offline start/allocation-only not delivered | locked |

## Expanded Design Review

Result: **pass; no unresolved design blocker**. One independent pass resolved
ownership at the existing seams; DQ rows carry the fixed decisions.

| Boundary | Evidence and accepted resolution | Result |
| --- | --- | --- |
| Service lifetime | Local retained-work checks omit an independent agent's accepted waiting work; existing role/application owners retain handoff and coordinator quiescence | resolved, DQ-41-02 |
| Slurm submission | Existing ready-stage journal is coordinator-owned; move it to the assigned agent, leaving only acknowledged projection | resolved, DQ-41-03 |
| Result delivery | Bootstrap already feeds authority publication; shared transport must use that same finalizer and await acknowledgement | resolved, DQ-41-05 |
| Removal/proportionality | Actual direct/offline/whole-run consumers justify incremental deletion and the Phase 9 audit; reuse operation, report, artifact and role stores | pass, DQ-41-06 |

## Examples And Validation

| ID / example | Behavior/risk | Authoritative owner and minimal coverage |
| --- | --- | --- |
| VAL-41-01 / EX-41-01 cold native run | prepare -> execute -> outputs -> clean shutdown; client lost during preparation; all-reuse case | Public run/authority transition tests; existing synthetic two-stage fixture |
| VAL-41-02 | Fresh/reopen/live/concurrent startup, wrong ID and lost expected root | Deployment/role locks, local subprocess integration; no replaced state |
| VAL-41-03 / EX-41-02 persistent fleet | Agent reuse, authorized capabilities, mixed lifetime | Agent registration/provider + run composition; local/HTTPS receipt parity |
| VAL-41-04 | Two runs, startup-to-admission and submit-to-shutdown races; borrowed roles | Lifetime owner; deterministic barriers and real owned-process exit |
| VAL-41-05 | Detach, publish/cancel/admit race, stale fence and cleanup refusal | Native client, supervisor and authority existing tests; no implicit kill/retry |
| VAL-41-06 | Native/container launch, resource controls and imported stage identity | Resident worker/executor; fake CLI plus qualified optional runtime hook |
| VAL-41-07 | Slurm/authenticated-authority preparation and state transitions | Managed publisher + coordinator authority contracts; replay and partial failure |
| VAL-41-08 / EX-41-03 train on Slurm | Agent submits, helper exits, stage stays pending until bootstrap/result | Existing ready-stage command fake moved behind agent; quota/accounting assertions |
| VAL-41-09 | Agent/coordinator restart, uncertain submit, grant wait, cancellation | Submission/agent journals/authority; exact handle preserved and no second sbatch |
| VAL-41-10 / EX-41-04 finish during outage | Durable result ingested after batch exit; malformed/stale/partial manifest | Shared result transport + existing finalizer; one commit, no unsafe release |
| VAL-41-11 | Site permission, reachability, shared result durability and limits | Real opt-in HPC run; separately qualified from fake scheduler evidence |
| VAL-41-12 / EX-41-05 sweep and MCP | Unified consumers, removed public commands/imports, cheap base imports | Package/CLI/sweep/MCP tests + exact dynamic reference/removal audit |

Causal combinations: startup and first admission; two runs and quiescence;
submission crash and scheduler discovery; cancellation and delayed bootstrap;
coordinator outage and compute exit/result ingestion. Do not duplicate entire
local/fleet/container/Slurm fault matrices. Existing numerical/stage invariants
remain with their source owners. Default local gates and optional live claims
are distinct; no runtime evidence is claimed during planning.

## Phase Shaping

The maintainer approved nine phases on 2026-09-10. Their boundaries separate
substantial publication, operation, service,
execution, scheduler and transport boundaries plus independently owned consumers.
Each phase includes code, tests, current docs and removal of replaced code.

| Phase | Outcome / authoritative owner | Validation |
| --- | --- | --- |
| 1 | Exact preparation, selected-authority publication and truthful state | VAL-41-01/07 |
| 2 | Durable run/admission/cancel on existing services | VAL-41-01/05 |
| 3 | Configured startup, per-service lifetime and ordinary run facade | VAL-41-01..05 |
| 4 | Agent-owned native/container workers and resource containment | VAL-41-03/05/06 |
| 5 | Sole agent Slurm submitter, observation, cancellation and job recovery | VAL-41-08/09 |
| 6 | Durable completed-job result ingestion and site qualification | VAL-41-10/11 |
| 7 | Sweep conversion with unchanged trial intent and identity | VAL-41-12 |
| 8 | MCP/skills over native run and cancellation | VAL-41-12 |
| 9 | Remaining shared removals and final deployment integration | VAL-41-01/12 |

Use one PR per phase, sequentially after its published predecessor; Phase 1
requires published Stage 40. Acceptance/continuation/cancel stay together in P2;
startup/handoff/quiescence in P3; submission/uncertainty/cancel/recovery in P5;
result ingestion/acknowledgement/retirement in P6. This protects the reviewed
invariants while narrowing implementation scope.

P2 proves persistent-service runs before P3 autostart. P5 uses current typed
result relay for connected job control; P6 completes finish-during-outage result
durability. Remove obsolete consumers as they move; P9 handles only remaining
shared owners and final audit. Development coexistence is not a final supported
compatibility mode. Stage completion requires all nine outcomes.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Agreement/design | FQ/DQ rows and completed independent design review | pass |
| Original plan review/correction | Run versus prepare terminal point and serialized cancellation retained in P2; MCP delegates in P8 | resolved |
| Nine-phase decomposition | Manager checked contract preservation, dependencies, invariant/validation/removal owners and all linked cards | pass |
| Documentation | Links/anchors, phase mapping, stale references and diff checks | pass |
| Maintainer approval | Agreed behavior and smaller-unit proposal approved on 2026-09-10 | approved |

Planning complete. Original design/plan review passes and their one correction
remain the review evidence; no additional independent review of the nine-card
layout is claimed. The manager verified this approved decomposition locally.
Stage 40 is published. The current amendment/readiness receipt and landing
status are owned by the [manifest Quality Gate](implementation-plan.md#quality-gate).
No runtime tests are claimed by this planning refinement.
Accepted risks remain breaking interfaces, accounting delays, qualified shared
storage and unresolved work retaining services. Revisit only for changed
predecessor contracts, demonstrated supported-path blockers or explicitly requested
offline/allocation/failover capabilities; keep live qualification distinct from
local validation.
