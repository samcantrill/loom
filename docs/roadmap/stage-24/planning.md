# Roadmap v24 Planning: Operational Lifecycle And Recovery Validation

Status: confirmed; ready for implementation
Roadmap stage: v24
Evidence tree: `/home/can134/work/active/loom` on `develop` at
`f709731ef9ce023a3a403eb7ca257bd059f416d7`; relevant dirty paths are the
requested Stage 24/25 roadmap artifacts, `docs/roadmap.md`, and numbering-only
references in adjacent feature, Stage 23, Stage 23-post, and example docs
Planning route: expanded during Phase 2 after implementation proved that the
accepted corruption-recovery behavior conflicts with the one-commit-per-stage
schema; the maintainer approved append-only output-commit supersession on
2026-08-20
Current gate: Phase 1 merged; Phase 2 refinement approved and in progress
Blockers: none

Stage 24 adds real boundary-level proof where fake processes, injected
exceptions, and happy-path examples cannot show that process liveness, durable
state, ownership, artifacts, and recovery agree.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Runner, CLI, subprocess timeout, managed-local shutdown, authority, resume, artifact, test harness, and external acceptance paths were inspected after Stage 23-post. | None. | Preserve existing owners and test only real boundaries. |
| Functionality | Graceful user stops cancel; ordinary failures/timeouts fail; unclean loss is classified during authoritative recovery; no incomplete output is reusable. | None. | Implement Phase 1 lifecycle alignment. |
| Design | Reuse runner lifecycle writers, executor cleanup, queue process handling, authority recovery transitions, planner invalidation, and current test support. | None. | Keep new helpers test-private. |
| Validation | Serial, subprocess, parallel, managed-local, hard-loss, authority-loss, and artifact-corruption boundaries need proportionate combined proof; external runtimes remain Stage 26 work. | None. | Execute the recorded obligations by phase. |
| Detailed plan / approval | The user accepted the operational-testing recommendation and requested a new Stage 24 on 2026-08-18. During Phase 2, both authority backends demonstrated that the one-commit-per-stage contract prevents the locked corruption-recovery behavior. The maintainer approved append-only, attempt-specific superseding commits on 2026-08-20. | None. | Complete the bounded Phase 2 refinement and expanded-path review. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `execution/runner.py`, CLI error mapping, execution/state specs | The runner catches `KeyboardInterrupt` with ordinary exceptions and records failure, while the documented behavior is cancellation plus exit 130. Parallel local stages run in non-preemptible threads, so already-running work must settle truthfully. | Demonstrated lifecycle mismatch and parallel boundary. | FR-1 through FR-3 |
| `SubprocessExecutor` and its tests | Production timeout handling exists, but the focused timeout test injects `TimeoutExpired`; successful and ordinary failure subprocess integration is already strong. | Real timeout and cleanup boundary. | FR-4, FR-11 |
| Stage 23-post runtime and tests | Recovery, shutdown deadlines, cancellation ordering, ownership, and lease retention are well covered with fake process handles; the downstream example proves real-process success but not cancellation. | One complementary real managed-local cancel test. | FR-5, FR-11 |
| Authority stores, transition policy, state/resume specs | Recovery transitions exist and SQLite rejects a second live controller, but the local service allows a conflict and the runner never renews its 24-hour controller lease despite an existing renew API. No e2e connects loss to safe resume. | Ownership continuity, parity, and recovery. | FR-6, FR-7, FR-9 |
| Artifact and resume implementation/tests | Checksums, index consistency, and downstream invalidation have focused coverage; public CLI/e2e resume currently proves the valid reuse path rather than corrupted payload recovery. | Artifact-trust workflow. | FR-8 |
| Test support and harness | `SleepStage`, `CoordinatedStage`, `EarlyStopStage`, and existing CLI/project helpers are reusable. Default suites exclude slow/external markers and have stable PR summary targets. | Hermetic test construction. | FR-2 through FR-12 |
| Container and SLURM acceptance suites | Real container tests primarily check command availability/build; live SLURM cancellation accepts a completion race. These require site/runtime gates and are not needed to close local lifecycle correctness. | Stage boundary and deferral. | FR-12 |

- Outcome: stopping, timeout, crash, resume, or corrupt output cannot create
  false success, orphaned work, or leaked ownership across the existing CLI/API
  -> runner/executor/queue -> authority/commit -> inspection/resume path.
- Included gaps: keyboard interrupt becomes failure; timeout and managed cancel
  lack real-child proof; controller ownership expires without renewal and
  differs by backend; crash recovery and corrupt-artifact resume lack e2e proof.
- Excluded: reattachment, repair command, daemon, retry/status changes, schema
  changes beyond the versioned output-commit migration, cross-platform signal
  parity, external scheduling, containers, and clusters.

## Minimum Useful Change

- At serial and prepared-worker boundaries, persist an uncommitted active stage
  and run as cancelled, clean up, and re-raise. Parallel execution stops new
  scheduling, cancels an identifiable triggering stage, and settles other
  already-running stages truthfully before re-raising. `stop_early()` still
  returns a cancelled result; the CLI already owns exit 130.
- Use existing local/subprocess and managed-local process paths. Add only test-
  private markers, PID capture, bounded polling, and cleanup, plus the smallest
  production fix a real test demonstrates.
- During explicit resume, acquire an exclusive controller lease, require
  authority recovery facts for the old controller and incomplete attempts,
  then record `INTERRUPTED`/`STALE` transitions and audit events before planning
  attempt 2. Bring the local service authority up to the existing SQLite lease-
  exclusion contract and renew live controller leases privately; live or
  ambiguous ownership remains a conflict.
- Prove checksum invalidation through one public branch-shaped workflow. When
  that explicit repair rerun succeeds, append a fenced attempt-specific commit
  which names the previously current commit, retain the old immutable commit,
  and project only the new commit and facts as current.
- Leave environment-dependent acceptance to Stage 26.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Apply one lifecycle outcome contract: authored/explicit stop and caught keyboard interrupt are cancellation; ordinary exceptions and enforced timeout are failure; unclean loss is interruption only when later recovery proves the prior active owner is abandoned. | Do not add statuses or reinterpret scheduler-specific cancellation. | Existing status/transition contracts. | Outcome-table unit/integration checks. | locked |
| FR-2 | Serial/prepared interruption cancels the uncommitted active stage and run. Parallel interruption stops new starts, cancels the triggering stage when identifiable, settles already-running stages truthfully, blocks unresolved work, then re-raises; committed success is never relabelled. | `stop_early()` remains returned cancellation; in-process threads are not forcibly stopped. | Runner/lifecycle and authority adapter. | Focused serial/parallel tests. | locked |
| FR-3 | Real serial local and subprocess CLI runs receiving `SIGINT` exit 130 after cancellation/cleanup, with no active-stage output or dependent start and no worker alive. A parallel local signal also exits 130 after in-flight stages settle and starts no later work. | POSIX/Linux PR gate; no Windows or preemptive thread-cancellation promise. | CLI, executors, test stages. | Three bounded signal scenarios. | locked |
| FR-4 | A real subprocess worker that exceeds configured timeout is terminated and observed exited; stage/run are failed with timeout facts and logs, no output is indexed, and a later attempt is clean. | No in-process timeout or new timeout policy. | Existing reliability policy and subprocess executor. | Production-runner integration test. | locked |
| FR-5 | Managed-local cancel against a real blocking child observes process exit before item cancellation and scalar/member lease release; pending and foreign-owner work are unchanged. | No crash-time reattachment or foreign PID action. | Stage 23-post runtime/controller. | One real-process integration/e2e scenario. | locked |
| FR-6 | Killing a test-owned coordinator/worker tree after a start marker cannot produce success, committed outputs, downstream starts, or immediately stealable live ownership. | External supervisor performs containment; Loom does not promise to kill after its own death. | Run lock, authority lease, process fixture. | Hard-loss subprocess scenario. | locked |
| FR-7 | A live runner renews its controller lease. Explicit resume obtains a new exclusive lease only after abandonment, verifies recovery facts for the old controller and incomplete attempt, then records interrupted/stale transitions/events before attempt 2. Live or ambiguous ownership blocks both authority backends. | No silent repair, public repair command, or new run-lock protocol. | Lease renewal/exclusion, recovery scan, transitions, planner, attempts. | Renewal unit, cross-backend contract, recovery e2e. | locked |
| FR-8 | Corrupting a checksummed successful artifact through the local store causes public resume to rerun its producer and consumers, reuse an independent branch, expose checksum mismatch, and restore payload/index agreement. Each successful repair attempt appends an immutable output commit linked to the prior current commit; the new attempt/commit becomes current without deleting history. | Invalid serialized state may continue to fail clearly; this requirement is byte corruption with valid metadata. Ordinary changed-config replacement remains fail-closed unless separately authorized. | Artifact store, planner, authority commit, CLI resume. | Cross-backend commit/migration contracts and branch-shaped public e2e. | locked; supersession approved 2026-08-20 |
| FR-9 | Loss of the real local authority service while a stage is active fails closed before output commit, exposes diagnostics, starts no dependent work, and never steals a valid lease. | No automatic service restart or network partition matrix. | Service authority and commit boundary. | One bounded service-loss integration test. | locked |
| FR-10 | Real-process tests use condition markers, monotonic deadlines, fixture-owned process groups/PIDs, and `finally` cleanup; no arbitrary sleep is the success oracle and no unvalidated PID is signalled. | Test-only support; no runtime dependency. | Existing test support. | Helper unit/use review and flake-free targeted runs. | locked |
| FR-11 | Existing success, exception, early-stop, fake-process, fake-authority, commit-failure, delegated, and resume behavior remains compatible; add combined tests only for causal interactions. | No comprehensive executor-by-failure matrix. | Current suite. | Targeted regressions plus PR gate. | locked |
| FR-12 | Default validation remains hermetic. Real Docker, Apptainer, SLURM, GPU, scheduler-accounting, queue-dispatch, notification, and remote-service profiles remain Stage 26 opt-in work. | No external service in `make validate-pr`. | Test markers/harness and roadmap. | Command/marker/docs audit. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1 through FR-3 | Graceful interrupt | Caught Ctrl-C is explicit cancellation; typed reason distinguishes it. | Status alone does not distinguish cancellation sources. | locked |
| FQ-2 | FR-2, FR-3 | Python/CLI propagation | Persist cancellation/cleanup, re-raise, and let CLI map 130; parallel in-flight work settles truthfully because local threads are not safely preemptible. | Python callers receive the interrupt; parallel exit may wait for bounded in-flight work. | locked |
| FQ-3 | FR-6, FR-7 | Unclean loss | Retain active evidence until authoritative recovery records `INTERRUPTED`/`STALE`. | Pre-recovery inspection may still show `RUNNING`. | locked |
| FQ-4 | FR-4 | Timeout | Keep typed timeout as failure, distinct from user cancellation. | No unified stopped status. | locked |
| FQ-5 | FR-8 | Artifact corruption | Rerun the affected branch on byte/checksum mismatch; append a fenced superseding commit for each repaired stage and retain the earlier commit; malformed state still fails. | Requires one versioned durable migration and current-versus-history projection. | locked; maintainer approved 2026-08-20 |
| FQ-6 | FR-5, FR-10 | Process truth | Terminal state/release follows observed exit; fakes retain exhaustive ordering. | One slower POSIX proof. | locked |
| FQ-7 | FR-9, FR-12 | Environment tiers | Local authority is hermetic; external sites remain Stage 26 profiles. | External failures are not all PR-gated. | locked |

## Behavior Baseline

- Early/explicit stop is `CANCELLED`; Ctrl-C cleans up, cancels, re-raises, and
  exits 130. Parallel interruption stops new work but preserves truthful results
  and valid commits from stages already running.
- Exceptions/timeouts are `FAILED`; timeout observes worker exit. Managed cancel
  releases only after exit and does not mutate pending/foreign work.
- Hard loss writes no fictional terminal state. Exclusive authority and matching
  recovery facts precede `INTERRUPTED`/`STALE` evidence and attempt 2; authority
  loss fails closed, while checksum mismatch reruns only the affected branch.
- A successful corruption repair never rewrites attempt 1. Attempt 2 atomically
  appends commit C2 with C1 as its expected predecessor; C2 and its artifact
  facts become current while C1 remains immutable history.

## Minimum Design

- Modules and ownership: runner/lifecycle owns cancellation and recovery
  decisions; executors and managed-local process handles own termination and
  exit observation; authority owns active truth, transitions, attempts, and
  leases; planner owns stale/reuse decisions; artifact store owns bytes and
  checksum verification; CLI owns exit presentation; tests/support owns marker
  and process-fixture mechanics.
- Graceful serial/prepared flow: signal -> executor cleanup -> uncommitted active
  stage and run cancellation -> downstream block -> owned release -> re-raised
  `KeyboardInterrupt` -> CLI exit 130. Parallel flow stops submission, settles
  in-flight stages without relabelling valid success, blocks unresolved work,
  cancels the run, then re-raises.
- Unclean-loss flow: a live runner renews its controller; after a supervised kill
  no commit occurs and the last lease blocks resume until deterministic expiry.
  A new exclusive controller scans matching abandonment facts, persists recovery
  transitions/events, then may plan attempt 2.
- Fixed contracts: lifecycle outcome table, CLI exit 130, success-after-output-
  commit ordering, exit-before-resource-release ordering, no reuse of old
  `RUNNING`/corrupt work, explicit recovery rather than silent rewrite, and
  hermetic default validation.
- Corruption-repair commit flow: planner-owned checksum mismatch authorizes the
  runner to name the current commit; authority verifies the latest active
  attempt, fencing token, and expected current commit in one transaction,
  appends the new commit/facts, succeeds the attempt/stage, and releases the
  lease. A competing or stale repair fails without changing the current head.
- Inspection flow: the existing stage snapshot remains a current-state
  projection, while one backend-neutral `list_output_commits` read returns the
  retained commit/fact composites in authority revision order for audit and
  contract proof. No second history abstraction is added.
- Private discretion: helper names, exception nesting, process mechanics,
  markers, polling, PID shape, fixtures, and test placement.
- No new command, config, status, marker, plugin, or dependency. The sole
  durable expansion is a versioned append-only commit-supersession field and
  migration, plus the minimum protocol input/read behavior needed to preserve
  current projection and immutable history. Preserve source import direction;
  tests consume public surfaces.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Interrupt lifecycle branch | Runner contradicts accepted cancellation semantics. | Retain failure. | keep smallest fix |
| Parallel interrupt settlement | In-process workers cannot be safely preempted. | Pretend all active stages cancelled. | preserve truthful results; stop new starts |
| Marker/PID fixture | Real signal and exit need safe synchronization/cleanup. | Sleeps/process search. | keep test-private |
| Real timeout and managed cancel | Injected/fake paths cannot prove child exit ordering. | More mock assertions. | keep one proof each |
| Controller continuity/recovery | Fixed TTL is not renewed and transitions lack workflow proof. | Treat TTL as lifetime. | private renewal plus existing recovery surfaces |
| Corruption and service-loss workflows | Connect planner/commit owners across real boundaries. | More isolated units. | keep one each |
| Append-only commit supersession | The locked corrupt-artifact rerun reaches attempt 2 but both backends reject its output because each stage can own only one commit. | Reuse attempt 1's commit or overwrite it. | retain immutable history; add explicit fenced current-head replacement and one versioned migration |
| Supervisor, reattachment, full matrix | Not required by current ownership contracts. | Add future machinery now. | defer/remove |
| External-runtime gate | Infrastructure is not reliably present. | Require Docker/cluster. | defer to Stage 26 |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 through FR-3 | Interruption owner | Runner persists lifecycle; executor cleans its child; the parallel scheduler settles in-flight work; CLI only maps the propagated interrupt. | Parallel exit may wait for bounded in-flight stages. | locked |
| DQ-2 | FR-3 through FR-6, FR-10 | Synchronization | Marker files and monotonic bounded polling establish readiness and exit. Never use a fixed sleep as the assertion. | Small test-support helper required. | locked |
| DQ-3 | FR-4, FR-5 | Cleanup proof | Assert exact child/group non-liveness before terminal state and release, while deterministic fakes retain branch-level timing proof. | POSIX-specific process check in default Linux CI. | locked |
| DQ-4 | FR-6, FR-7 | Recovery truth | Privately renew live controller ownership; after loss, exclusive acquisition plus recovery facts decide abandonment. Use deterministic authority time, never PID or wall-clock waiting. | Renewal errors must fail closed; recovery waits for all relevant leases. | locked |
| DQ-5 | FR-8 | Artifact and commit oracle | The runner may request supersession only for the checksum-mismatch rerun path and must name the expected current commit. Authority atomically appends an attempt-specific successor after fence/current-head validation; snapshots expose only successor facts as current while durable history retains the predecessor. Assert planner reason, commit lineage, attempt counts, payload content, outputs, and run index together. | Requires a versioned SQLite migration, service parity, and an expanded-path review. | locked; maintainer approved 2026-08-20 |
| DQ-6 | FR-9 | Authority failure point | Stop the local authority after stage start and before commit; no new production failpoint. | Fixture orchestration is more involved than a fake. | locked |
| DQ-7 | FR-11, FR-12 | Validation shape | PR-gate hermetic local behavior; retain environment-specific acceptance and receipts in Stage 26. | External-runtime regressions depend on scheduled/manual evidence. | locked |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Local/subprocess CLI Ctrl-C | Signal, cancellation, cleanup, artifact/downstream absence, and exit 130 agree; subprocess leaves no worker. | Runner, executor, CLI. | One real-signal e2e per causal process owner. | planned |
| Parallel local Ctrl-C | New scheduling stops while already-running stages settle without fictional cancellation or lost valid commits. | Parallel runner/CLI. | One bounded coordinator-signal case plus focused stage-raised interrupt. | planned |
| Enforced timeout | Production timeout kills/observes worker and persists timeout failure. | Subprocess executor/reliability boundary. | One integration test; injected unit retained. | planned |
| Managed-local cancel | Exit precedes item cancellation/lease release. | Runtime/adapter/authority. | One real child; deterministic fakes retained. | planned |
| Hard coordinator loss | Controller renewal preserves live ownership; after loss, active leases block and exclusive recovery records interruption/stale evidence before attempt 2. | Authority, lock, planner, runner. | Renewal unit plus isolated loss/resume and lease-parity contract. | planned |
| Authority service loss | Commit fails closed; dependants do not start. | Service authority mutation. | One bounded integration test. | planned |
| Corrupt artifact resume | Mismatch invalidates one branch; fenced append-only supersession repairs bytes/current index without erasing the prior commit. | Artifact store, planner, authority commit. | Cross-backend supersession/migration contracts plus one public branch e2e. | planned |

Causal interactions requiring combined coverage:

- real `SIGINT` + executor cleanup + durable cancellation + CLI exit;
- parallel coordinator interruption + in-flight settlement + scheduling stop;
- real managed-local child exit + queue terminal state + scalar/member lease
  release;
- unclean process loss + authority liveness/expiry + recovery transition + new
  attempt;
- checksum mismatch + DAG invalidation + fenced commit supersession + current
  artifact/index replacement;
- authority process loss + output-commit authorization + downstream blocking.

All other categories remain focused tests rather than an executor/store matrix;
Stage 26 owns external profiles.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Real interruption and cancellation | A user can stop serial, subprocess, bounded-parallel, or managed-local work and Loom's exit, state, process liveness, artifacts, downstream work, and leases agree; actual subprocess timeout is proven. | Runner/CLI/executor/managed runtime and test support; no unclean recovery, corruption, external runtime, new status, or daemon. | Completed Stage 23-post. | Focused runner regression, three real Ctrl-C cases, real timeout, real managed cancel, full PR gate. | pending |
| 2. Crash recovery and artifact trust | Unclean process/authority loss cannot create false success, explicit recovery/resume is conservative and inspectable, and corrupt checksummed output repairs only its affected branch through append-only commit supersession. | Authority/recovery/planner/artifact/runner, the versioned output-commit migration, and public workflow tests; no repair command, reattachment, cluster/container acceptance, or retry redesign. | Phase 1 merged. | Hard-loss recovery, live-owner refusal, real authority loss, commit migration/backend parity, corrupt-artifact resume, docs, full PR gate. | in progress |

Two phases separate graceful cleanup—where Loom is alive and must complete
termination—from unclean recovery—where Loom cannot assume cleanup ran and must
rely on authority and durable evidence. Each phase delivers a complete user-
observable safety outcome.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR/FQ rows distinguish cooperative stop, caught signal, failure/timeout, unclean loss, authority loss, and corruption. | pass |
| Minimum design justified | Existing lifecycle, transition, authority, planner, artifact, executor, and queue owners are reused. | pass |
| Complexity delta proportionate | The previously excluded schema change is now limited to the demonstrated current consumer: append-only attempt-specific commit supersession. No repair command, supervisor, reattachment, dependency, status, or broad matrix is added. | pass after maintainer approval |
| Contracts and private discretion clear | Observable ordering and outcomes are fixed; helper names, process mechanics, and file placement remain private. | pass |
| Invariant ownership and validation proportionate | Each real process, parallel scheduling, authority recovery, and artifact interaction is covered once; focused tests remain authoritative elsewhere. | pass |
| Phases vertical and reviewable | Graceful lifecycle proof and unclean recovery/artifact trust are independently useful two-phase outcomes. | pass |
| No unresolved blocker | The user accepted the recommendation and requested this stage; repository evidence resolves placement and semantics. | pass |

Gate result: original planning and Phase 1 are complete. Phase 2 moved to the
expanded route after its executor demonstrated the durable conflict; the
maintainer approved the bounded supersession design on 2026-08-20. One qualified
refinement and one independent expanded-path review are required before merge.

Accepted risks: POSIX-only signals, settled rather than preempted parallel work,
no reattachment/machine-loss cleanup, and Stage 26 external evidence.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Ctrl-C | Serial/prepared work cancels; parallel stops new starts and settles in-flight truthfully; then re-raise for exit 130. | Matches explicit stop without claiming unsafe thread preemption. | Cooperative parallel cancellation is accepted. |
| Unclean loss | Renew live controller leases; after loss require exclusive acquisition and recovery facts, then record `INTERRUPTED`/`STALE` evidence. | TTL alone must not misclassify a live runner; dead PID is not authority. | Reattachment owner is accepted. |
| Timeout/corruption | Timeout fails; valid checksum mismatch reruns its branch and may atomically append a commit that explicitly supersedes the expected current commit; malformed state errors. | Keeps the new successful attempt and current output aligned without rewriting history. | Broader replacement policy is accepted. |
| Output-commit history | Multiple immutable commits per stage are durable; the highest valid authority revision is current, each successor names its predecessor, snapshots/materialized indexes expose only current facts, and one `list_output_commits` read exposes retained composites in revision order. | This is the smallest truthful model for the current corruption-repair and inspection consumers. | A consumer requires filtering, pagination, or a broader history read model. |
| Deferrals | No supervisor, repair API, schema work beyond output-commit supersession, new status, broad matrix, or external-runtime PR gate. | Current private seams and Stage 26 own these concerns. | A current consumer requires one. |
