# Phase 3 Execution Plan: Service Startup And Lifetime

## Metadata

- Status: in_progress
- Roadmap stage and phase: 41 / 3
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p3-service-startup-lifetime
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `4e3635b706f6406cca4861f97f846914ad3dcae1` (published Phase 2 completion metadata after PR 309)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 3: Service Startup And Lifetime
- Dependencies: Phase 2 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; Phase 2 merged, metadata published and stage/control/live develop synchronized

## Objective And Context

The ordinary run command connects or safely starts configured services, then cleans only the roles whose lifetime permits it.

Phase 2 already owns accepted run/cancel behavior. This phase makes cold local and mixed persistent/fleet journeys available through the same operation and existing native workers. Phase 4 completes additional native/container backend unification.

Requirements: FR-41-01/02/03/04/05/09/12; supporting FR-41-13/14. Design: DQ-41-01/02.
Validation ownership: VAL-41-01 (cold run), VAL-41-02/03/04, VAL-41-05 (cleanup).

## Current Source And Harness

- `src/loom/queue/deployment.py`, `local_daemon.py`: protected role configs, atomic initializer, durable binding, locks and reconciliation.
- `src/loom/queue/local_daemon_execution.py`: retained work and clean shutdown; `agent_session_transport.py`: independent outbound-agent lifecycle.
- Phase 2 native start_run/cancel_run_operation and observation; `src/loom/cli/run.py`, root exports and existing CLI native client wiring.
- Daemon production, agent lifecycle/transport, deployment, import-boundary and CLI E2E tests; use deterministic barriers and real service processes.

## Scope

Own protected deployment selection, creation/open binding, configured local startup, mixed lifetime, handoff/quiescence and lazy root CLI/Python run wiring. No remote provisioning, ambient discovery or environment installation.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

Phase 2 makes a run durable once accepted by an existing coordinator. This phase
adds the ordinary CLI/Python entrypoint that establishes service availability
before calling that operation, then reports its execution and cleanup outcome.
The public names below are planned; the current checkout does not implement them.

```python
import loom

outcome = loom.run(
    request,
    deployment="deployments/local.yaml",
    wait=True,
)
```

```bash
loom run configs/experiment.yaml --deployment deployments/local.yaml
```

The request comes from Phase 2; repeat use of its accepted IDs reconciles that
same request. A new experiment requires a new request identity. Constructors and
base imports remain inert; explicit run/availability operations perform startup.

### Configured startup and stable binding

Deployment selection identifies connections, authorized local role configs,
preparation settings and each role's lifetime. This is a conceptual fragment of
that information, not a complete schema or a fixed choice of YAML key layout:

```yaml
coordinator:
  service_config: ./coordinator.yaml
  lifetime: persistent

agent:
  service_config: ./agent.yaml
  lifetime: run

binding_path: ./state/service-binding.json
```

This mixed-lifetime example requires separately operated roles and the existing
authorized outbound-agent connection. Services can share a process when their
lifetimes match. Credential/profile details remain in protected role configs.

| Observed situation | Availability action |
| --- | --- |
| Compatible live service | Connect and verify the expected identity |
| Existing stopped service | Reopen the same state and reconcile before accepting work |
| Explicitly configured fresh local service | Initialize and bind through the existing locked owner |
| Unavailable remote service | Report/wait for that selected service; no local replacement |
| Missing previously bound root | Report recovery/conflict rather than create another identity |

The binding outside role roots distinguishes first creation from lost expected
state. Concurrent starters converge under role locks. A bounded startup handoff
keeps a new run-owned service alive until acceptance or abandonment; accepted
work then owns continued service lifetime independently of the client.

### Shared service lifetime and cleanup

```text
Run A starts a run-owned coordinator.
Run B submits work to the same coordinator.
Run A finishes.

Run A returns: coordinator retained for other work.
Run B continues.
Coordinator stops after all its retained work settles.
```

The safe-to-stop decision includes pending preparation/continuation, waiting
admissions, live assignments, scheduler jobs, unacknowledged results and unresolved
execution. Local PID absence cannot answer that question. Persistent services stay
up even when this invocation started them. Service shutdown retains durable state.

Cleanup reports stopped, persistent/borrowed, retained-for-other-work or
cleanup-blocked evidence per role. A blocked stop does not change a committed
scientific result. Another run's retained work does not force this caller to wait
for all other experiments. Timeout and client exit detach; explicit cancellation
uses Phase 2's owner. The VAL-41-02..05 checks cover these races and actual process
lifetimes, alongside the cold-run example in VAL-41-01.

## Fixed Contracts And Private Discretion

Add a lazy `loom.run(request, *, deployment, wait=True, timeout_seconds=None)`
facade and `loom run CONFIG --deployment PATH` using the same native integration
owner as Stage 40. `deployment` selects a protected file, resolved relative to the
caller's working directory. No implicit global/LAN discovery. CLI uses the
deployment's preparation source/profile and explicit run controls; configs and
overlays must fit its permitted source closure. Client constructors remain inert.

### Deployment selection, creation and restart

Use one versioned protected deployment selection referencing existing coordinator
client/service and agent-service configurations. Its fixed information is:
connection plus expected coordinator identity; locally startable role config
references; lifetime `persistent` or `run` for each such role; preparation
source/profile selection; bounded startup/wait policy; and a local binding path
when automatic creation is enabled. Paths inside it are relative to that file.
At least a client connection or local coordinator config is required. Remote-only
selection uses the expected identity from protected client configuration.

Keep the local creation binding outside the role roots, at the explicitly
configured protected path. It records schema, role/config identity, resolved root
and expected service IDs, plus only the creation/handoff facts needed for crash
replay. It is not a job/discovery index. Under existing locks, retain initialization
intent before creating roots, atomically publish through the existing initializer,
then bind IDs before admitting work. Crash after root publication may complete
the matching binding; partial/conflicting roots fail without replacement. Once
bound, a missing expected root is an error, never a fresh initialization. Loss of
both binding and roots is outside same-root recovery; no inferred lost-state repair.

Concurrent starters converge on matching identities. Startup checks protocol,
authority and agent reconciliation before accepting work; advertised free capacity
cannot precede retained-work reconciliation. Local auto-start applies only to
configured local roles. An unavailable remote endpoint never creates a substitute.
Protected credentials/policy authorize agent registration and profiles independently
of its self-reported offer. Reuse existing initialization/role locks and stores.

### Configuration paths and bounded startup

CLI CONFIG and overlay arguments name contained relative paths within the
deployment's selected preparation project (`source.root` plus `source.path`),
not arbitrary paths on the client host. The source closure must include them.
Paths selecting the deployment file resolve from caller cwd; role/client config
references and the creation binding resolve from the deployment file, preserving
each role's explicit env-file behavior. Absolute/out-of-closure experiment paths
fail before acceptance. Remote staged preparation still requires source files
visible to the coordinator; no implicit upload or path rewriting is introduced.

Startup policy bounds creation/connection separately from post-acceptance run
observation. Availability composes bounded native calls and preserves their
expected-coordinator guard and uncertain-mutation references. A passed caller
deadline bounds startup/dispatch, including MCP's request budget; expiry before
dispatch cannot cause a delayed new submission. Once dispatch may have happened,
retain original IDs and reconcile uncertainty. Detached wait does not wait for
compute capacity, preparation completion or target admission after durable run
acceptance. Missing eligible workers is accepted waiting work, not an instruction
to create unconfigured agents or installations.

### Lifetime and shutdown

Each role persists its configured lifetime and startup attachment. Coordinator
serializes work acceptance and quiescence; an independent run-owned agent consumes
that accepted-work projection rather than deciding from its local PIDs. Include
pending preparation/continuation, no-capacity admissions, assignments, result
delivery and unresolved containment. Startup handoffs have bounded expiry before
acceptance; accepted work never expires because its client disappears.

For mixed lifetimes, use independent existing service compositions and explicit
outbound-agent credentials. Co-host roles only when their lifetimes match; do not
replace a running embedded-agent binding. Persistent services stay even if this
call started them. Shared run-owned services stay while other accepted work needs
them. Idle agent connections and completed history do not keep a coordinator alive.

After this run settles, report each role as stopped, persistent/borrowed,
retained-for-other-work, or cleanup-blocked with native evidence. The retained
decision transfers remaining cleanup to the service and permits this caller to
return. A blocked stop never rewrites the scientific result or escalates to an
unrequested kill. Pre-acceptance failure releases startup holds and stops only
otherwise idle run-owned roles. Restart preserves lifetime and same state; shutdown
does not delete binding, role stores, authority, results or receipts.

### Coordinator-authorized retirement

`local_daemon_owner_work_is_retained` only proves local execution retention and
returns false when no local agent exists; `LocalDaemon.stop()` is not an atomic
global-idle check. Keep those low-level owners and add the accepted-work decision
at coordinator/application scope. Before starting a clean stop, serialize new
acceptance, startup holds and the quiescence decision under the coordinator owner.
A racing request either transfers its hold into accepted work or receives the
retryable reconnect outcome before acceptance; never acknowledge work into a
retiring owner. Pending explicit admission-retry journals also retain services.

Independent run-owned agents consume a coordinator-authorized retirement decision
bound to the service identity and current process/session generation. Stale,
unavailable or restarted-coordinator evidence cannot authorize retirement. The
decision closes that agent's assignment eligibility before agent shutdown and
still requires its local containment/result-delivery checks. For shared run-owned
roles, unresolved accepted work keeps the deployment available even while no
worker is assigned; idle connections and retained historical pins do not.
Use existing role/application stores and transport to retain/reconcile these
facts. No new client job store or PID-count proxy owns this lifecycle.

### Delivery boundary

This phase uses Phase 2 operation and timeout/cancel semantics unchanged. Service readiness includes retained-work reconciliation, while missing new compute capacity remains visible waiting. Cold-run coverage uses already supported native workers; container-specific changes belong to Phase 4.

### Cross-phase handoff

Phase 4 uses the lifetime/containment contract; Phases 5–6 add their outstanding scheduler/result work to the existing retained-work predicate. No phase may infer idle state from helper/PID absence. Phase 8 invokes the same availability composition.

### Removal owned here

Switch ordinary run to the shared managed composition and remove its replaced direct dispatch branch. Remove obsolete CLI flags that would select a bypass. Shared PipelineRunner helpers still used elsewhere stay only until their mapped consumer phases remove them; do not add compatibility wrappers.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Creation binding outside role roots proves expected identity after root loss. Existing role/application owners retain the startup handoff and quiescence decision. No global registry, PID-count lifetime proxy or per-client job index.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One matching creator/reopener | Initializer/binding under role locks | Two starters, crash after root publication, missing bound root | Wrong service or replacement identity | VAL-41-02 exact binding/no reset |
| Accepted work retains needed services | Coordinator quiescence and per-role owner | Startup/admit/stop races, detached caller, waiting remote work | Lost owner for accepted work | VAL-41-03/04 barriers and real process exit |
| Persistent/borrowed roles survive | Per-service lifetime owner | Mixed roles and concurrent runs | Unrequested service shutdown | VAL-41-03/04 correct role retention |
| Cleanup truth is separate | Public run composition and native evidence | Stop refuses or other work remains | Scientific result overwritten or caller stuck unnecessarily | VAL-41-05 retained/blocked cleanup outcome |

## Implementation Slices

1. Add protected deployment selection and locked creation/open binding with exact recovery from interrupted initialization.
2. Implement startup handoff and per-service lifetime/quiescence together, covering acceptance versus shutdown and mixed roles.
3. Wire lazy root Python/ordinary CLI run to ensure then Phase 2 start/observe/cancel; verify cold run, detach and cleanup.
4. Remove the replaced direct CLI dispatch, update deployment/lifetime examples and prove persistent/fleet parity.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Lazy root facade, no constructor startup, explicit deployment/identity and cleanup shapes. |
| Unit | Required | Binding intent/open-only checks, bounded unaccepted handoff, service retention predicates. |
| Integration/E2E | Required | Cold/reopen/concurrent start; mixed roles; two runs; waiting fleet; preacceptance failure; actual owned process exit. |
| Live fleet | Environment-dependent qualification | Qualified transport/site evidence is separate from local process fixtures; preserve missing-evidence status. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_service_lifecycle.py tests/integration/queue/test_agent_session_transport.py tests/e2e/test_cli_runs_e2e.py tests/package/test_import_boundaries.py

Add deterministic acceptance/retirement barriers to the existing service tests:
coordinator-only deployment with accepted preparation but no eligible worker;
publication completed but continuation still pending; pending explicit retry;
independent agent receiving stale or unavailable retirement evidence; and a new
request racing the final stop decision. Confirm real role-process outcomes and
that completed history/preparation pins alone do not retain idle services. Cover
the same configured source path through local and remote client invocation.

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Startup and shutdown ownership must land together. Stop for a supported role combination that requires replacement of live identity or cannot retain pending accepted work. Never use process exit alone as global quiescence or an unrequested kill to force cleanup.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: passed on 2026-09-12 in the manifest's persistent stage
  worktree and this phase branch. Phase 2 PR 309 merged as
  `5a624d11ca5c777765fb35583a628bc57562f419`; completion metadata was published
  as the Base revision above. Synchronization verified matching stage, local
  develop, fetched origin/develop and advertised develop revisions. Exact local
  and remote Phase 2 branch refs were retired; the stage worktree was retained.
  All predecessor agents/validation processes are terminal. Successor `start`
  and `preflight` passed on the clean prepared branch.
- Source reconciliation: published Phase 2 supplies native RunRequest,
  start_run/cancel_run_operation, durable publication/admission linkage and
  bounded observation. Coordinator schema is 15; worker schema remains 12.
  Existing protected role loaders and outbound agent service remain in
  queue/deployment.py; coordinator foreground composition remains in
  cli/queue.py. Ordinary cli/run.py still dispatches the old execution paths.
  Local retained-work checks and low-level stop remain insufficient for the
  global quiescence decision, as this card already specifies. Reuse those owners
  and the predecessor's unchanged run/cancel contract.
- Named refinement: none needed. The reviewed behavior, phase boundary, trust
  and identity contracts, and required validation remain unchanged. Protected
  deployment key layout and private composition/helper choices remain execution
  discretion; no new discovery, provisioning or compatibility path is approved.
- Coverage selection: protected relative paths and creation/open binding;
  concurrent startup and interrupted initialization; cumulative startup/dispatch
  budgets; acceptance/retirement barriers including waiting preparation,
  continuation and explicit retry; mixed-role lifetime and stale retirement
  evidence; cold run, detach and actual process exit; ordinary CLI cutover and
  cheap root imports. Use the listed native service/transport and CLI fixtures.
  Physical fleet qualification remains separate. Expand only for changed shared
  contracts, relevant failures or unresolved accepted concerns. Both required
  full commands remain binding.
- Execution delegation: one executor is justified by the coupled durable
  creation/startup/quiescence, independent role lifetime and public CLI/Python
  cutover. The manager retains manifest, pre-submit, PR/review and delivery
  ownership; no child delegation or overlapping source writes.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: implemented; final validation is in progress. Protected selection
  and external binding now retain every role creation intent before initializing
  roots. Native role locks preserve identity and immutable lifetime on foreground
  or automatic restart. Coordinator cycle serialization owns startup attachments,
  accepted-work retention and final retirement; independent agents require current
  coordinator/session/process-generation authorization and clean native retirement.
  The lazy root facade and ordinary CLI share startup, exact native acceptance,
  bounded observation and separate cleanup evidence.
- Development coverage: added cold/replay and actual process exit; concurrent
  starters; missing-bound-root and interrupted multi-role creation; all independent
  mixed lifetime combinations; foreground restart; abandoned startup expiry and
  losing acceptance; waiting preparation/detach; shared-run and cancellation
  retention; history-only idle; unavailable/stale agent retirement; borrowed
  Unix/HTTPS source parity; configured observation handshake timeout; and clean
  shutdown refusal preserving committed success. Existing publication/continuation
  and retry-recovery fixtures now assert retention at their native barriers.
  Existing Phase 2 zero-timeout detach assertions remain unchanged.
- Removal reconciliation: ordinary direct CLI dispatch/builders and executor,
  run-uri, dry-run, authority and plugin bypass controls were removed. Obsolete
  CLI dispatch tests were replaced by managed-path tests; authority/diagnostic
  setup now uses bounded test-local existing-library fixtures. The manager
  explicitly authorized bounded example-local primitive wiring to preserve the
  existing executable backend/container assertions. No production compatibility
  adapter or old ordinary CLI branch remains.
- Retained consumers and successor owners: Phase 4 owns native/container journeys
  in execution/subprocess, execution/containers/docker,
  execution/containers/slurm-apptainer, execution/runtime-profile,
  operations/failing-run and operations/local-diagnostics. Phase 6 owns the
  execution/slurm/dry-run-basics and execution/slurm/afterok-diamond planning
  scripts and physical Slurm acceptance hook. Phase 9 owns final remaining-owner
  cutover, including execution/offline-first-import,
  operations/offline-import-rejections, operations/authority-backend-diagnostics,
  diagnostic/authority test-state helpers and other retained PipelineRunner
  consumers. Existing generic runtime, sweep, prepared-run, stage-worker, Slurm,
  artifact and authority primitives remain for these owners. The physical Slurm
  acceptance hook was preserved unchanged; default fixtures do not qualify it.
- Validation preparation correction: the initial `make validate-pr` at
  `1aa60f9f599d8bdd8328284f9b526b01bda0f903` passed Ruff/Pyright but was
  intentionally interrupted during the baseline lane (exit 130) after the cleanup
  audit found retained fixture supervisors. The mixed-role fixture now uses the
  existing authenticated `shutdown_for_test` owner and verifies process exit.
  Its three role combinations passed (79.46 s). Three earlier orphaned fixture
  supervisors whose temporary state had already been removed were identified by
  exact command/root and absence of children, interrupted, and observed exited;
  unrelated supervisors were untouched.
- Final retirement race correction: already-issued agent retirement authorization
  remains replayable after a new startup hold. The selected run-agent readiness
  check observes its exact native session's retained retirement record before
  dispatch, so a closing incarnation cannot stand in for the next eligible one.
  The deterministic authorization/replay/new-hold test passed (4.78 s).
- Acceptance handoff completion: a new cancel-run control for an already
  completed run is rejected before commitment when retirement wins; completed
  existing controls remain replayable. Accepted preparation/run transactions
  remove their matching startup attachment atomically, leaving native accepted
  work as the lifetime owner. The complete lifetime file passed: 18 passed in
  184.16 s, including cold fast replay, mixed roles, source/observation budgets,
  cleanup refusal and this cancellation race.
- Gate restart qualification: the second `make validate-pr` at
  `76084c1bb16a92226f33f139450b111d898fb417` passed Ruff/Pyright and was
  intentionally interrupted during baseline execution (exit 130) for the final
  cancellation/handoff correction. Neither interrupted baseline is full-suite
  evidence. Three native fixture supervisors left by interrupted baseline cases
  were shut down through their authenticated private test-shutdown protocol and
  observed exited; no fixture workloads or processes remain from those attempts.
- Completed baseline feedback: `make validate-pr` at
  `f96de461888d95f24f96b73f22d74d91eb016094` exited 2: Ruff/Pyright passed;
  baseline 3292 passed, 2 skipped, 286 deselected, 4 failed in 1194.87 s.
  The failures were stale public-export and mocked-dispatch expectations, now
  corrected to include root `run` and the required deployment argument. Their
  package/CLI selection passed (18 passed in 0.96 s). No runtime changes followed
  that completed baseline. Config-extra feedback is being collected before the
  final complete rerun; documentation-only edits did not restart that healthy
  selection.
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for durable startup/lifetime and public cutover
- Manager correction 1/3: corrected stale current ordinary-run guidance in
  docs/features/cli.md, slurm.md, container-example-coverage.md and testing.md,
  the Docker/Apptainer entrypoint descriptions, active resume examples and the
  retained live-Slurm template. Ordinary command guidance now requires deployment
  selection; retained examples describe library execution/planning and explicitly
  separate physical/native-backend qualification. Restored accurate workflow,
  variants, preflight and offline-import explanations for current catalog checks.
  Exact removed-flag searches over current README/features/operations/example
  guidance, including normalized multiline commands, returned zero matches.
  Affected documentation/catalog checks: 12 passed, 17 deselected in 2.62 s.
  Historical roadmap artifacts and P4/P6/P9 delivery remain untouched.
- Blocker corrections: 1/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Shared deployment/facade/runtime; coordinator acceptance/lifetime and agent retirement owners; ordinary CLI; corresponding tests and current docs/examples. |
| Tests added, updated or intentionally removed | Coverage and removal rationale recorded in Workflow State; replaced ordinary bypass tests removed, underlying backend/authority assertions retained through local fixtures. |
| Validated revision/tree and evidence | Pending implementation |
| Validation-relevant changes after evidence | None |
| Replaced-code removal / retained primitive consumers | Ordinary CLI hard cut complete; exact retained consumer groups and Phase 4/6/9 successor ownership recorded above. |
| PR, review and merge | Pending |
| Residual risk and cleanup | Live fleet qualification and mixed-role process evidence pending |
