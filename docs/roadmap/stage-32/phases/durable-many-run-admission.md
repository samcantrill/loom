# Phase 1 Execution Plan: Durable Many-Run Admission

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 32, Phase 1
- Manifest: docs/roadmap/stage-32/implementation-plan.md
- Branch: agent/stage-32-p1-durable-many-run-admission
- Worktree root and path: use the manifest-recorded root;
  `<root>/stage-32-p1-durable-many-run-admission`
- Base revision: `8da9536d351dba46c6737465839a40802f547f5b`
- PR target: develop
- PR title: `Stage 32 phase 1: add durable many-run admission`
- Dependencies: completed Stage 29 production correction and existing whole-run queue service/repository
- Requirements and decisions: FR-1 through FR-5; FQ-1, FQ-2; DQ-1 through DQ-3
- Workflow path: expanded; public request/receipt and hard-cut durable queue identity are fixed by the stage plan
- Blockers: none

## Objective And Context

- Vertical outcome: project code streams thousands of ordinary prepared-run
  requests into the queue, receives one classified receipt per request, and can
  replay the complete deterministic stream after interruption without creating
  duplicate queue items.
- Earlier dependency: the existing `QueueService`, `QueueEnqueueRequest`,
  `QueueItem`, and SQLite repository already own ordinary whole-run admission.
- Later work explicitly out of scope: Slurm submission/driving, scheduler
  recovery, remote queries, collection status, and project-specific generators.

## Current Source And Harness

- Relevant files and symbols: `QueueEnqueueRequest`, `QueueService.enqueue`,
  `QueueItem`/`RunIntent`, `SQLiteQueueRepository.enqueue`, schema creation,
  bounded selection reads, `QueueClient`, package exports, and queue CLI JSON
  formatting.
- Existing tests and seams: model serialization, SQLite exact updates/FIFO,
  service lifecycle, concurrent selection, queue status, and deterministic sweep
  helpers that remain downstream consumers rather than admission owners.
- Import, dependency, or harness constraints: use stable plain-data hashing and
  canonical digest validation; do not import pipeline runner, CLI, Slurm, sweep,
  or project code into repository/model modules.

## Scope

In scope:

- Hard-cut the queue record/database schema and add canonical immutable
  `admission_digest`, indexed nullable `scientific_fingerprint`, and whether
  scientific deduplication was bypassed by force.
- Keep existing `queue_item_id` as the sole stable submission identity; do not
  add a parallel public identifier.
- Extend `QueueEnqueueRequest` with the nullable fingerprint and force behavior.
  Normalize and validate a non-null value as a canonical supported digest.
- Compute the admission digest from all immutable normalized enqueue content,
  including run URI, queue/pool resolution, run intent, launch contract, tags,
  metadata, scientific fingerprint, and force choice, but excluding timestamps,
  status, claims, dispatch handles, cancellation, and audit sequence.
- Atomically classify a request as newly enqueued, exact submission replay, or
  scientific duplicate. Exact replay compares the admission digest. Scientific
  duplicate lookup applies only to non-forced rows with non-null fingerprints
  and returns the original canonical queue item without inserting an alias.
- Keep a forced first admission out of the canonical scientific uniqueness set;
  replay its exact queue item ID normally. A later ordinary submission may
  become the canonical row for that fingerprint.
- Add one typed enqueue receipt carrying disposition, requested queue item ID,
  canonical queue item ID, queue item, and accepted time without copying
  arbitrary request content into diagnostics.
- Preserve `enqueue` as the single-item operation and add a streaming
  `enqueue_many` application/client operation that consumes requests in order,
  commits each independently, and yields/returns receipts incrementally with a
  documented consumption boundary.
- Add bounded repository listing needed by clients/tests to prove counts without
  loading every item through status. Do not add general filtering/query grammar.
- Update intentional public imports, queue docs, schema diagnostics, and one
  project-code generator example that uses Loom hashing over a normalized
  scientific mapping.

Out of scope:

- Persisting a batch/sweep/collection row, generator source, raw normalized
  scientific config, or all-request transaction.
- Automatically deciding which config fields are scientific, deriving identity
  from absolute paths, mutating an existing run URI, or reopening terminal work.
- Queue database migration, old-record compatibility, cross-repository or
  namespaced deduplication, and deletion/forget semantics.
- Slurm, controller-cycle, artifact/log, event-sink, or remote transport changes.

Assumptions:

- One queue database is one deduplication scope. Projects sharing it include
  project identity in their normalized scientific content when required.
- Complete admission requires consuming `enqueue_many` receipts; unconsumed
  suffixes were never accepted.
- Project fingerprint normalization is trusted.

## Fixed Contracts And Private Discretion

- Observable behavior: same ID/same digest replays any current state; same ID/
  changed digest conflicts; same non-null fingerprint under another ordinary ID
  returns the canonical item; null fingerprints do not cross-deduplicate; force
  requires a new ID and exact force replay remains idempotent.
- Public or durable shapes: request additions, receipt/disposition, queue record
  fields, database columns/indexes/schema version, and bulk operation ordering.
- Trust and failure boundaries: only repository transaction chooses the
  classification; callers cannot assert an existing disposition or accepted
  time; diagnostics do not echo arbitrary config/metadata.
- Cross-phase contracts: Phase 2 consumes canonical queue items and admission
  digests without adding another identity.
- Reproducibility and compatibility: canonical stable hashing; durable FIFO of
  newly admitted items only; semantic duplicates retain the original accepted
  position and run URI; old databases fail explicitly.
- Private choices the executor may simplify: exact receipt enum/module, partial
  index expression, transaction SQL structure, iterable protocol helper, and
  page/cursor representation below the fixed bounds.

## Proportionality

- Existing seam reused: queue request/item, one SQLite transaction, stable JSON
  hashing, repository primary key, and public service/client composition.
- Material additions and current justification: indexed semantic identity and a
  receipt are required to distinguish replay from new work; streaming-many is
  required for large deterministic generators without a collection owner.
- Optional hardening and future capability deferred: migrations, namespace
  registry, batch receipts, distributed admission, server push, and generator
  manifests.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One queue item ID has one immutable intent | queue repository | retry with changed request | one ID executes different science/work | exact replay/conflict matrix |
| Optional scientific identity has one canonical ordinary row | queue repository indexed transaction | concurrent different IDs with same digest | duplicate scientific run | concurrent semantic-admission test |
| Force never defeats exact replay | queue repository | lost force response | repeated forced executions | same/new force-ID tests |
| Accepted prefix survives interruption | per-item SQLite transaction | process loss during large iterator | duplicated or missing acknowledged work | 1,000/2,000 causal restart test |
| Bulk operation owns no collection lifecycle | application operation shape | iterable failure/suffix | false all-batch claim | mid-generator exception and receipt-prefix assertion |

## Implementation Slices

1. Add hard-cut request/item/receipt serialization and canonical admission
   digest construction with focused identity tests.
2. Add SQLite schema columns/indexes and atomic new/replay/semantic-duplicate
   classification, including concurrent admission tests.
3. Route single enqueue through the new classification and add streaming-many
   direct/client behavior with ordered receipt and interruption tests.
4. Add bounded item listing, public imports, documentation, and normalized
   project fingerprint example.
5. Run targeted model/repository/service/client checks and the full gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional request/receipt imports stay cheap | Queue public import and build tests. |
| Unit | required | Validation, canonical digest, receipt serialization | Null/non-null/force and changed content. |
| Contract | required | Direct/client parity and hard-cut records | Same classified outcomes and exact wire/plain data. |
| Integration | required | SQLite atomicity, concurrent semantic dedupe, large replay | 2,000 items with prefix restart; exactly one canonical row. |
| E2E / opt-in | required local | Project generator uses actual public application path | Deterministic temporary-root example; no scheduler/network. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_queue_models.py tests/unit/loom/queue/test_service_client.py
    uv run pytest tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_service_lifecycle.py
    uv run pytest tests/e2e/test_queue_cli.py -k enqueue
    uv run ruff check src/loom/queue tests/unit/loom/queue tests/integration/queue
    uv run pyright src/loom/queue tests/unit/loom/queue tests/integration/queue

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: timestamp-bearing digests, two rows winning one scientific
  fingerprint, force bypassing exact replay, unbounded JSON scans, or an API that
  implies an unconsumed iterable suffix was admitted.
- Review focus: canonical digest field set, transaction/index causality, null
  semantics, force response loss, bounded memory/queries, redacted errors, and
  absence of sweep/collection state.
- Stop if: correctness needs cross-database coordination, automatic scientific
  field selection, migration/dual-read, batch authority, or changing terminal
  run state. Return to planning rather than widen the phase.
- Accepted debt and revisit trigger: fresh-only schema and repository-scoped
  scientific identity; revisit for a concrete migration or multi-project shared
  catalog consumer.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above, confined to ordinary queue
  admission/models/repository/client/docs/tests and phase metadata.
- Decisions not to revisit: one queue item/submission identity; nullable canonical
  scientific digest; force only bypasses semantic dedupe; per-item commits; no
  collection/generator persistence; hard-cut schema.
- Conditions requiring manager action: incompatible existing public return
  behavior, inability to create atomic indexed classification, need for
  migration, or any pipeline/Slurm/runtime mutation.

## Workflow State

- Manager preparation: passed; Stage 29 Phase 12 is remotely merged, the branch
  and dedicated worktree are rebased on current `origin/develop` at `8da9536`,
  and the executor packet is current.
- Expanded planning: not needed; the approved stage-level design fixes the
  schema/transaction contract. Reconsider only for a concrete ambiguity.
- Implementation: complete; immutable admission records, atomic SQLite
  classification, streaming receipts, bounded listing, public imports, and the
  normalized project example are committed on the phase branch.
- Refiner: complete; correction 2/3 aligned stale queue-record contract
  expectations and local/Slurm/scheduler reconstruction helpers with the
  approved v2 hard cut.
- Pre-submit gate: passed; manager review found no scope drift, second identity
  owner, migration, unbounded admission, or future-phase work. Fresh
  `make validate-pr` and `make test-summary` evidence is recorded below.
- Independent review: not needed; the final repository/index diff retains the
  approved single-transaction design and manager review found no material
  residual risk requiring a spawned pass.
- Blocker corrections: 3/3 — correction 1/3 corrected the approved public
  `submission_replay` disposition and completed the admission identity matrix;
  correction 2/3 updated stale v1 queue-record test fixtures and reconstruction
  helpers to v2, including regenerated admission digests after fixture mutation,
  without adding a migration or dual read; correction 3/3 rejects null persisted
  admission digests instead of silently repairing corrupt v2 records.
- PR and merge: [#257](https://github.com/samcantrill/loom/pull/257) was verified
  against `develop` and squash-merged as `b93d4ac` on 2026-08-30. The dedicated
  worktree and local/remote phase branches were removed after the remote merge.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Queue record/schema v2 admission identity, SQLite classification/indexes, service/client streaming and pages, intentional exports, queue docs/example, and phase-scoped tests. |
| Tests added or updated | Queue model/receipt and null-digest validation; SQLite exact replay, concurrent scientific dedupe, null identity, canonical run-URI retention, force conflict, pages; request digest/force validation; streaming interruption/restart across 2,000 requests; public example E2E. |
| Validated revision/tree state and evidence | `make validate-pr` passed at `ec31668`: ruff, pyright, 2,615 default tests, 155 config-extra tests with 3 skips, and sdist/wheel build. `make test-summary` passed: package 118, unit 1,855, contract 297, integration 286, E2E 59, config-extra 155; overall 2,770 passed and 3 skipped. The rebase to `8da9536` added only upstream Stage 35 roadmap documents. |
| Validation-relevant changes after evidence | None. The post-validation rebase added only upstream roadmap documents; this evidence/phase metadata update changes no source, test, dependency, build, or validation configuration. |
| PR, review, and merge | [#257](https://github.com/samcantrill/loom/pull/257) targets `develop`; manager review passed with no blocker; squash-merged as `b93d4ac`. |
| Residual risk and cleanup | Trusted project fingerprints can still over/under-deduplicate and old queue databases are intentionally rejected. Dedicated worktree and local/remote phase branches were removed. |
