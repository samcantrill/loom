# Roadmap Stage 32 Planning: Resumable Many-Run SLURM Throughput

Status: approved corrective replan
Roadmap stage: 32
Evidence tree: `/home/can134/work/active/loom` at `135773663d899d6fc28e6251d4f99fb8641cf3b6`; retained blocked Phase 2 candidate at `c9cbd2ccbdff0a55c7b3924ec7afeca45af8bfc6`; relevant dirty paths: none before this replan
Planning route: expanded; admission identity changes durable whole-run queue state, and crash-safe SLURM submission crosses the filesystem and external-scheduler boundary
Current gate: passed; Phase 1 is merged, Phase 2 is review-blocked, and the approved Phase 3 replacement may begin
Blockers: none

Approved: behavior/fingerprints 2026-08-28; packet 2026-08-29; Stage 34
run-to-item reference 2026-08-30; corrective replacement phase 2026-08-30.
No new owner is added.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | The historical whole-run queue, SQLite repository, foreground controller, delegated SLURM adapter, and single-job/`afterok` submitters already provide the nearest end-to-end path. | None. | Reuse and strengthen those owners. |
| Functionality | Project code generates ordinary prepared-run requests; Loom admits them durably and idempotently, then a restartable foreground driver hands them to SLURM. | None. | Preserve per-run and scheduler ownership. |
| Design | Exact replay uses existing `queue_item_id` as the stable submission identity; optional scientific deduplication uses a project-supplied canonical fingerprint; force requires a new queue item ID. | None. | Hard-cut the whole-run queue schema. |
| Validation | Fake scheduler/process tests cover 2,000-run replay and causal crash boundaries; one shared-filesystem HPC journey covers both Slurm modes. | None. | Keep real Slurm opt-in. |
| Detailed plan | Phase 1 is merged; blocked Phase 2 records the rejected candidate; Phase 3 replaces the complete external-scheduler vertical slice from current `develop` and closes only the two review gaps. | None. | Use the linked Phase 3 plan. |
| Approval | Behavior direction, fingerprint choice, run-to-item reference, and the FR-9/FR-10 corrective replacement are accepted. | None. | Begin Phase 3 from current `develop`. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `src/loom/queue/service.py`, `_sqlite.py`, and `models.py` | Existing owners persist ordinary queue items, FIFO order, launch contracts, and audit events. Timestamp-bearing duplicate comparison makes a normal retry conflict. | Admission reuse and idempotency failure. | FR-1..FR-5 |
| `src/loom/queue/controller.py` and queue CLI | The foreground controller can reopen delegated work without a supervisor, but stops at handoff and applies managed-capacity assumptions. | Restartable bounded bulk progress. | FR-6, FR-7 |
| `src/loom/queue/slurm.py` | The adapter records scheduler facts, but handle-commit loss lacks exact discovery and `COMPLETED` can close a queue item without authoritative run success. | Submission recovery and lifecycle join. | FR-7..FR-10 |
| `src/loom/pipeline/executors/slurm/` | Whole-run single-job and static-DAG `afterok` submission, manifests, status, cancellation, scripts, logs, and run-local planning artifacts already exist. Stage 29 separately supplies scheduler-visible operation markers and exact discovery for ambiguous `sbatch`. | Reuse both service-less modes and the proven discovery seam. | FR-7..FR-10 |
| Stage 29 and `docs/features/queue.md`/`slurm.md` | Stage 29 ready-stage SLURM requires a live coordinator bootstrap and remains a different lifecycle owner. Historical whole-run delegated Slurm is explicitly service-less and shared-filesystem-first. | Deployment boundary and non-goals. | FR-6, FR-9, FR-11 |
| Stage 31 and Stage 33 | Discord event/reporting paths are downstream and best effort. Stage 33 is independently approved for a same-host coordinator reporter and does not consume or alter Stage 32. | Reporting placement and sequencing. | FR-11 |

- User-visible outcome: project code can submit thousands of ordinary runs,
  replay after process loss, and let SLURM schedule accepted work without a
  long-running login-node service.
- Existing end-to-end path: project code prepares a normal Loom run and Slurm
  planning artifacts; the whole-run queue durably records an item; a foreground
  controller delegates one script to SLURM; compute nodes write run state, logs,
  results, and artifacts to project-selected shared storage.
- Included scope: streaming enqueue, optional scientific deduplication, forced
  repeats, bounded delegated driving, both service-less Slurm modes,
  ambiguous-submit discovery, outcome joins, and HPC guidance.
- Non-goals: a sweep/batch lifecycle, cross-run dependency DAG, dynamic
  intermittent ready-stage controller, Stage 29 protocol changes, SLURM arrays,
  allocation-fed agents, remote artifact stores, copied logs, webhook outbox,
  coordinator HA, SSH client, or remote query gateway.
- Public or durable surfaces affected: queue enqueue request/receipt and bulk
  method, queue schema, delegated foreground operation, Slurm markers/manifests
  where required, and documentation.

## Minimum Useful Change

- Treat existing `queue_item_id` as the stable submission identity and add a
  canonical immutable request digest, nullable scientific fingerprint, and
  force bit to the existing queue row.
- Add one streaming `enqueue_many` operation that repeatedly invokes the same
  single-item transaction and returns one receipt per consumed request.
- Make a delegated foreground cycle reconcile a bounded active window, submit a
  bounded queued window, and exit when no immediate local action remains. It
  never waits for the experiment to finish merely to keep submitting other
  items.
- Adapt queue dispatch to existing prepared-run single-job or `afterok`
  submission records rather than inventing another scheduler-job model.
- Defer the singular local/Unix/HTTP run-query model to a later stage. Stage 33
  is already assigned to Discord coordinator reporting, so that follow-up is a
  Stage 34 candidate after its transport and authentication behavior is
  approved.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Accept an iterable of ordinary prepared-run enqueue requests and durably process each independently, returning an ordered per-request receipt. | No sweep manifest, batch status, collection transaction, or eager materialization of the complete iterable. | Existing `QueueService.enqueue`. | Generator and bounded-memory tests. | locked |
| FR-2 | Use the existing stable non-empty `queue_item_id` as submission identity and compute one canonical admission digest over immutable normalized request content, excluding enqueue/update times and mutable lifecycle facts. | The ID is opaque; Loom does not derive scientific meaning from paths or configuration. | Stable plain-data hashing. | Exact replay and changed-content conflict. | locked |
| FR-3 | Accept `scientific_fingerprint: str | None`. A canonical non-null digest enables repository-scoped semantic deduplication for ordinary submissions; `None` disables cross-ID scientific deduplication while retaining submission-ID replay. | Project code decides the normalized scientific content and may exclude absolute paths and operational details. Loom stores the digest, not another config snapshot. | Existing fingerprint helpers. | Same/different ID, null, path-change, and collision behavior. | locked |
| FR-4 | Support an explicit forced repeat only with a new stable queue item ID. Force bypasses scientific deduplication on first admission but exact replay remains idempotent. | Force never mutates, reopens, or duplicates an existing ID. | FR-2, FR-3. | Lost-response force replay and changed-force conflict. | locked |
| FR-5 | Commit each new admission before acknowledging it. Replaying 2,000 deterministic requests after a crash at any prefix returns existing receipts for the prefix and inserts only missing requests. | No promise for requests the service never received or whose iterable was never consumed. | SQLite transaction owner. | Causal 1,000/2,000 interruption and restart test. | locked |
| FR-6 | Run the ordinary delegated controller as a foreground, restartable driver with bounded active reconciliation and bounded submission work per cycle. A quiescent exit means no immediate local action, not that Slurm work is terminal. | No daemonization framework or scheduler-capacity ownership. | Existing controller/repository bounds. | Many pending/active rows and restart tests. | locked |
| FR-7 | For a project-prepared run, select existing single-job or static `afterok` Slurm mode and persist the run-local submission identity/manifest as scheduler-job inventory. Retain its canonical `queue_item_id` for exact later lookup. | No new job-group abstraction or dynamic stage decisions. | Existing Slurm planners/submitters. | Both modes and run-to-item agreement. | locked |
| FR-8 | Before every scheduler call, persist exact operation identity and launch digest. On ambiguous response or handle-commit loss, discover the exact scheduler-visible marker; one match repairs, none stays unknown, and multiple matches conflict. | Never blindly resubmit an uncertain call. | Stage 29 operation-marker/discovery seam. | Before/after-`sbatch` crash cuts and exact discovery matrix. | locked |
| FR-9 | Reconcile lifecycle in owner order: authoritative run/stage terminal state, retained submission manifest/handle, `sacct`, `squeue`, then persisted last-known evidence. Scheduler `COMPLETED` alone is not scientific success. | Missing both terminal run evidence and retained scheduler evidence remains `UNKNOWN`. | Authority-backed run state and Slurm status. | Completed/failed/missing-result/accounting-expired cases. | locked |
| FR-10 | Keep run state, logs, results, and artifacts in project-configured filesystem stores and require compute-visible paths for this route. Queries return local references; Stage 32 does not stream or copy bytes. | No default remote store or log aggregation. | Existing local/shared-filesystem Slurm contract. | Preflight rejection plus fake shared-root journey. | locked |
| FR-11 | Document deployment and reporting placement: persistent Stage 29 coordinator/agents only where services are allowed; service-less whole-run Slurm otherwise; managed webhooks/reporters run beside the coordinator, while compute jobs and agents do not independently report the same lifecycle. | No durable reporting replay or external credentials on compute nodes. | Stage 29/31/33 docs. | Documentation and secret-absence review. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-5 | Many experiments are ordinary queue items generated by project code. | Reuses the existing current consumer and keeps project-specific sweep logic downstream. | Loom provides no batch-level lifecycle or generator persistence. | locked |
| FQ-2 | FR-2..FR-4 | Reuse queue item identity for exact replay and add optional scientific identity. | The maintainer approved nullable scientific deduplication; this separates retry identity from deliberate repetition without another ID. | Projects own correctness of their semantic normalization. | locked |
| FQ-3 | FR-6..FR-9 | Service-less HPC uses the historical whole-run queue/Slurm owners, not Stage 29 ready-stage bootstrap. | Compute can progress without a coordinator endpoint and Slurm can own static dependencies. | Dynamic output-dependent scheduling requires a whole-run job or persistent coordinator. | locked |
| FQ-4 | FR-7 | Preserve both single-job and `afterok` as per-run choices. | They already exist and address allocation efficiency versus stage-specific resources. | `afterok` may create many scheduler jobs. | locked |
| FQ-5 | FR-10, FR-11 | Keep artifacts/logs local or shared and reporting centralized by lifecycle owner. | Avoids duplicate truth, remote-store operations, secret distribution, and log relay. | Remote users initially receive status/references through existing local/SSH workflows only. | locked |

## Behavior Baseline

- A project generator prepares normal Loom runs and yields requests in any
  deterministic order. The queue transaction, not the generator, owns whether
  an admission exists.
- `queue_item_id` is the repository-scoped submission identity. Same ID/digest
  returns the current item; changed immutable content conflicts.
- A non-null fingerprint has one canonical ordinary admission. Another
  non-forced request returns that item and original run URI; it never relocates
  the run. Forced rows are not canonical deduplication rows.
- With a null fingerprint, different queue item IDs are independent even when
  their configs happen to be scientifically equivalent.
- The queue schema hard-cuts with no migration or dual reader.
- Delegated cycles may submit while earlier jobs remain active because Slurm
  owns capacity; site configuration bounds calls and inspected work.
- A stopped driver makes no progress, while accepted Slurm work continues.
  Restart reconciles durable state before new submission.
- Direct local and Stage 29 managed behavior remain unchanged.

## Minimum Design

- `QueueEnqueueRequest` gains nullable `scientific_fingerprint` and `force`;
  existing `queue_item_id` remains the sole exact submission identity. One typed
  receipt identifies `enqueued`, `submission_replay`, or
  `scientific_duplicate` and returns the canonical queue item.
- `SQLiteQueueRepository` owns admission digest, scientific-deduplication index,
  transaction, and enqueue order. `QueueService` exposes single and
  streaming-many operations; clients do not inspect SQLite.
- Existing run-local Slurm manifests own jobs, scripts, handles, partial state,
  logs, snapshots, and the canonical queue-item reference. Queue stores only a
  typed manifest reference/summary.
- The foreground driver reconciles bounded windows before selection, continues
  after durable handoff, returns safe counts/diagnostics, and need not remain
  alive.
- Scheduler-visible markers and discovery helpers are reused from ready-stage
  Slurm, but Stage 29 assignment/bootstrap records and authority protocol are
  not imported into the historical whole-run lifecycle.
- Per-run authority remains the scientific lifecycle owner. Queue state reports
  admission/dispatch outcome and Slurm reports external state; no axis overwrites
  another.
- Queue modules may import generic fingerprint/serialization and existing Slurm
  execution APIs. Pipeline/core/store modules do not import queue or CLI.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Nullable scientific fingerprint plus admission digest | Required for replay and optional path-independent semantic deduplication. | Use path/run URI as identity. | keep |
| Queue schema/index hard cut | Required for bounded lookup and atomic uniqueness across thousands of requests. | Scan JSON rows or add migration machinery. | keep |
| Streaming many-enqueue operation | Required to avoid client-side bespoke retry loops and full-batch memory/transactions. | Repeated public single calls only. | keep minimal |
| Prepared-run delegated Slurm adapter/driver behavior | Required to reuse single-job/`afterok` manifests and survive process exit. | New batch scheduler or nested `sbatch` scripts. | keep |
| Exact operation-marker discovery | Required by the unavoidable SQLite/`sbatch` atomicity gap. | Blind retry or permanently unknown every response loss. | keep |
| Sweep/batch lifecycle, dynamic controller, remote store/log relay/query gateway | No current requirement for Stage 32's throughput outcome. | Add several new owners and protocols. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-2..FR-5 | Queue repository is the sole admission/deduplication owner. | One indexed transaction can atomically choose new, exact replay, or semantic duplicate. | Queue schema hard-cuts. | locked |
| DQ-2 | FR-3 | Scientific fingerprints are canonical digests produced by trusted project code, and null is meaningful. | Loom cannot infer scientific equivalence from paths or complete operational config. | Incorrect project normalization can over- or under-deduplicate. | locked |
| DQ-3 | FR-4 | Force bypasses only semantic deduplication; it never bypasses submission-ID replay/conflict. | Prevents response loss from turning one forced request into repeated executions. | A deliberate additional repeat needs another stable ID. | locked |
| DQ-4 | FR-7, FR-8 | Run-local Slurm manifests own scheduler jobs and retain the canonical queue item ID; queue rows reference the same manifest. | Avoids duplicate inventories and lets Stage 34 resolve `run_uri` to an exact primary-key read without scanning. | The cross-owner IDs must agree. | locked; reference approved 2026-08-30 |
| DQ-5 | FR-8 | Persist before call and discover by exact bounded marker. | This is the existing conservative Stage 29 solution to the external-call atomicity gap. | No match remains unknown rather than favoring liveness. | locked |
| DQ-6 | FR-9 | Run authority decides scientific terminal success; scheduler facts remain a separate axis. | Prevents `COMPLETED` wrappers with missing results from becoming false success. | Some jobs settle as unknown and require explicit operator action. | locked |
| DQ-7 | FR-10, FR-11 | No byte relay or compute-originated external reporting. | Shared filesystem and centralized reporting meet the accepted current deployment. | Disconnected service-less runs provide no real-time remote notifications. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Prior deployment factories/remote-agent applications duplicate Stage 29 Phase 12. | FQ-3, FR-11 | Competing production composition. | Remove from Stage 32. | resolved |
| Sweep authority and remote byte/log stores add owners not needed for replay. | FQ-1, FR-1, FR-10 | Item idempotency and shared storage already meet the outcome. | Keep streaming enqueue and references only. | resolved |
| Intermittent ready-stage coordination requires the endpoint while absent. | FQ-3, FR-7 | Violates the deployment constraint. | Use single-job/`afterok`. | resolved |
| The Phase 2 driver reads manually injected retained snapshots only when every current fact is missing and does not persist its own observations. | FR-9, DQ-6 | Partial accounting loss can hide a retained failed job, while complete accounting loss can regress a previously observed terminal scheduler fact to unknown. | Persist current per-job observations in the existing run-local snapshot owner and fill only each missing job from its newest retained fact. | locked for Phase 3 |
| Phase 2 checks prepared files on the submit host but does not require evidence that compute sees the same workspace. | FR-10, DQ-7 | `sbatch` can accept a job that cannot read run state or write results. | Require positive existing `delegated_verification.shared_workspace` evidence before any prepared scheduler call. | locked for Phase 3 |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Deterministic 2,000-run generator | Prefix replay creates duplicates | queue transaction/index | stop after 1,000; replay all; exactly 2,000 rows and classified receipts | planned |
| Null/semantic/forced identities | Dedupe/repeat drift | admission index | canonical duplicate, null independence, force replay/new force | planned |
| Foreground service-less driver | Process exit stalls or loses accepted work | queue controller plus Slurm manifests | submit, exit, scheduler progress, reopen/reconcile/continue | planned |
| Ambiguous scheduler submission | Duplicate scheduler jobs | persisted operation and marker discovery | before call, after acceptance, after handle return, one/zero/multiple matches | planned |
| Old completed job | Accounting expires after result or one job disappears before authority terminal | authority/run store, current scheduler facts, then run-local per-job snapshots | persist observations through the driver; current facts win per handle; retained facts fill only missing handles; authority terminal still wins | planned for Phase 3 |
| Shared-filesystem journey | Submit-host paths exist but compute visibility is unproven | launch-contract verification before scheduler boundary | absent/false/unsupported proof rejects before `sbatch`; explicit proven shared workspace permits both fake modes | planned for Phase 3 |

Causal interactions requiring combined coverage:

- Admission prefix crash and semantic deduplication interact because a replay may
  use new queue item IDs for already-seen scientific fingerprints.
- Scheduler-call uncertainty, process restart, and run terminal evidence
  interact because exact discovery must not replace authority success.
- `afterok` partial submission and driver restart interact because only proven
  missing logical jobs may be submitted.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Durable many-run admission | Project code streams ordinary requests and safely replays any admitted prefix with optional scientific deduplication and explicit forced repeats. | Queue request/receipt, service, SQLite schema/index, bounded reads and tests; no Slurm behavior. | Stage 29 Phase 12 merged to avoid queue CLI/schema conflicts. | Identity matrix and 2,000-run prefix restart pass. | merged |
| 2. Service-less Slurm driving | Historical rejected candidate for the foreground-driver outcome. | Same intended ownership as Phase 3; retained only to record the exhausted correction/review result. | Phase 1 remotely merged. | Fully validated candidate failed independent review on FR-9 and FR-10; no PR opened. | blocked |
| 3. Service-less Slurm completion | A foreground driver submits prepared single-job or `afterok` runs, exits, and later reconciles exact scheduler/run state without duplicate submission, false success, lost per-job evidence, or unproven compute paths. | One replacement PR carries the Phase 2 implementation from current `develop`, persists/merges per-job snapshots, enforces existing shared-workspace proof, and retains all prior docs/tests; no managed bootstrap, remote query/store, or reporting protocol. | Phase 1 remotely merged; Phase 2 explicitly blocked; maintainer approved replacement. | All Phase 2 behavior plus partial/pruned accounting and pre-`sbatch` proof matrix, full gates, and independent review pass. | pending |

Three recorded phases preserve the blocked Phase 2 result while keeping the
implementation architecture at two vertical outcomes. Phase 3 is a complete
replacement PR based on current `develop`, not a stacked continuation of the
unmerged Phase 2 branch.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1..FR-11 and FQ-1..FQ-5 record the maintainer discussion, including nullable fingerprint. | pass |
| Minimum design justified | Existing queue and Slurm owners supply every major seam. | pass |
| Complexity delta proportionate | Sweep, dynamic controller, remote data, query gateway, and reporting durability are removed. | pass |
| Contracts and private discretion clear | Identity, force, manifests, owner order, hard cut, and deferrals are fixed; helper layout remains private. | pass |
| Invariant ownership and validation proportionate | Admission, run lifecycle, scheduler state, and bytes each have one owner with causal boundary tests. | pass |
| Phases vertical and reviewable | Phase 1 owns admission; Phase 3 replaces the blocked external-scheduler slice in one current-`develop` PR. | pass |
| No unresolved blocker | Phase 1 and its Stage 29 dependency are merged; Phase 2 is explicitly blocked; the approved replacement has no unresolved planning decision. | pass |

Gate result: originally approved on 2026-08-29 and corrective replacement
approved by the maintainer on 2026-08-30; no product or design blocker remains.
Phase 3 begins from current `develop` after the explicitly blocked Phase 2.

Accepted risks: fingerprints trusted; accounting-free work remains
unknown; queue databases hard-cut; shared filesystem required;
scheduler validation manual. Revisit for dynamic-DAG, non-shared-storage,
remote-query, delivery-SLA, or migration needs.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Scientific idempotency | Optional nullable canonical digest. | Projects may want only exact request replay. | Need for namespaced/cross-repository dedupe. |
| Force | New stable ID; bypass semantic dedupe only. | Keeps forced response-loss replay safe. | None without a new repeat model. |
| HPC coordinator | No persistent Stage 29 service required for whole-run Slurm. | Meets login-node restrictions. | Site permits/needs dynamic managed stages. |
| Artifacts and logs | Stay in project-selected local/shared stores. | No current remote-store/relay need. | Compute cannot share required paths. |
| Hooks/reporting | Coordinator-side for managed deployments; direct owner only for standalone; no compute/agent duplicates. | Prevents multiple reports and secrets. | Durable deferred notification SLA. |
| Singular run query | Defer to Stage 34 because Stage 33 is Discord reporting. Reuse one typed model across local, owner-only Unix, and authenticated read-only HTTP adapters; remote responses expose run/admission status, freshness, and artifact/log locations, never bytes. Service-less SSH invokes stable JSON CLI. | Separate public/authenticated read boundary and no remote store. | Approve transport/authentication and projection. |
