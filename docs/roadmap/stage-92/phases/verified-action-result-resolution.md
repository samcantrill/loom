# Phase 2: Verified Action Result Resolution And Fresh Execution

## Metadata And Scope

- Status: pr_open; draft PR #332, full local validation and required independent review pending.
- Base: `32f8d90d4af6ea8f0e4ccb78a024b5dc7de67ed2`.
- U1: PR #331 merged at `a0d29b3fedac7495bbb994e630b07aa41f7cf579`; metadata published and shared synchronization passed at the base above.
- Coordination branch: `agent/stage-92`; use the manifest's clean control and stage worktree paths.
- Branch: `agent/stage-92-p2-verified-action-result-resolution`.
- PR title: `Stage 92 Native Project Contracts And Result Resolution - Phase 2: Verified Action Result Resolution And Fresh Execution`.
- PR: https://github.com/samcantrill/loom/pull/332 (draft until all gates pass).
- Target: develop; execution context and approved protocol are in the [manifest](../implementation-plan.md).
- Fixed contract owner: native contract sections Native Execution Identity And
  Selection, Delivery Packages And Source Ownership (U2), and Example And
  Validation Contract (U2 rows and Genericity Fixture And Acceptance).

Deliver one native selectable-result lifecycle: a versioned causal execution key
distinct from legacy fingerprints; actual committed input identities; qualified
code/assets/installation separated from captured graph authorship; fenced claims;
candidate verification and original-result bindings; demand-aware cancellation,
restart and retention; installed verify_result with opaque namespaced reason
codes and artifact-identifying errors; idempotent fresh_stages generation that
does not change scientific keys or replace default results. Preserve whole-target
reconciliation and legacy resume. Successful actions in failed source graphs
remain eligible; failures/corruption never become a cache miss or silent retrain.

Reuse existing authority/coordination/read-model and immutable shared-closure
owners. Keep hashing and installed callbacks outside short database transactions.
Preserve control prerequisites and recheck mutable authority/retention when
binding. No copied producer commits, rphys cache/scheduler, scientific reason-code
enum, result-selection plugin registry or new Weave mechanism.

## Validation And Startup

At startup trace current U1 source and bind exact selectors. Required cases are
owned by the approved contract: changed alias/unrelated branch hit; science,
actual producer, implementation/output contract differences miss; one concurrent
producer; cancellation of original versus final demand; restart; successful
action from failed graph; native integrity and project-semantic rejection;
malformed verdict/code/port handling; default/fresh/replay/conflicting replay;
default result retained after fresh. Reuse the U1 installed text fixture and
existing native lifecycle/retention/publication tests.

Add `tests/integration/queue/test_action_result_resolution.py` and extend affected
fingerprint/resume, reconciled-run, submission/CLI and shared-publication owners.
Use locked Python 3.12 lanes. Final gate: `make validate-pr` and
`git diff --check`, then required independent actual-head review. Native tests do
not replace rphys's changed-installation physical gate.

## Source Binding And Named Startup Question

U1's committed report/context protocol is landed and independently reviewed.
Existing source owners at the selected base:

- `queue/local_daemon_execution.py` reconciles native admissions through
  `RunOrchestrator` into the global ready window and dispatches all placements.
  Its `_cancel` currently installs a run-wide cancellation epoch and fans out
  local, remote and SLURM containment. That path cannot simply run unchanged
  against an action retained by another graph's demand.
- `pipeline/stores/sqlite_authority.py` and the coordinator authority adapters
  own fenced attempt/commit/status mutations. Existing coordination, read models,
  stage-work records and cleanup references own the relevant durable projections.
- `queue/_preparation_operations.py` accepts idempotent intent under a short
  transaction, persists selected installation/capture state, and reconciles
  whole-target preparation/verification. `queue/preparation.py` owns immutable
  preparation codecs. Fresh selection/generation must extend these owners and
  the native RunRequest/CLI projections coherently.
- `queue/resident_readiness.py` already qualifies declared source roots,
  imports, distributions, Python and executor/container identity. Its separate
  project/environment/executor fingerprints are distinct from the captured
  composition. Reuse explicit installed source/asset qualification; never strip
  files heuristically from whole-source evidence.
- `pipeline/planning/fingerprints.py` retains legacy alias/config/source-edge
  audit identity. Add causal action identity alongside it; use existing output
  specs, actual original commit/ref/closure identities and native reuse bindings.
- `queue/_shared_publication.py` owns immutable shared closure retention,
  publication and receipt validation. Preserve original facts and bytes.

### Resolved Native Demand And Producer Ownership

The startup question is resolved against source `207b065`: extend native
coordination ownership and make cancellation applicability depend on the exact
retained action claim. Keep the original run/node/attempt/assignment/fence and
commit; a consumer demand never becomes the producer. No missing accepted
product decision was found. This is implementation direction under the approved
logical records, not a new wire contract or a requirement for private helper names.

Concrete owners and constraints:

- `pipeline/stores/sqlite_authority.py` stores authority **per run**, including
  when `state_root` is external (`_authority_database_path`). Its singleton
  `cancellation_epochs` row is not stage-scoped: passing fewer `stage_names` to
  `install_cancellation_epoch` does not exempt other attempts. Prepare, bind,
  grant and start call `_require_no_cancellation_epoch`. Existing receipts have
  immutable replay/scope checks. Extend the authority's applicability checks for
  an explicitly retained claim/attempt; do not weaken the legacy singleton
  barrier or infer permission from a caller-supplied list of exceptions.
- `queue/local_daemon.py` owns durable admissions/cancellation operations in
  `control.sqlite`; `queue/_managed_local.py:SQLiteCoordinatorAssignments` owns
  durable assignment/resource occupancy; `pipeline/orchestration.py` owns
  `RunOrchestrator`, preparation intents and rebuildable `StageWorkRecord`s.
  Put the new store/principal/installation-scoped claim, demand and result facts
  with native durable coordination ownership, with atomic key selection and
  demand attachment/detachment. A per-run authority scan or a stage-work index
  cannot supply cross-run mutual exclusion. The new lifecycle facts are
  authoritative; the lookup and ready-work projections remain rebuildable.
- `queue/coordinator_authority.py`,
  `pipeline/stores/{authority,coordinator_authority}.py`,
  `authority/{mutation_service,routes/coordinator}.py` own the capability and
  authenticated transport boundary. Extend their narrow mutations/read models
  together with the SQLite authority implementation. Preserve embedded,
  coordinator-only and authenticated service deployments; do not access a remote
  authority's files from queue code. Native coordination and per-run authority
  have separate transactions today: use replayable fenced handoffs/reconciliation
  for their effects, never assume one transaction spans them or hold a database
  transaction across an authority RPC.
- `local_daemon_execution.py:_cancel`, `_install_run_cancellation_if_requested`,
  `_fan_out_{local,remote,slurm}_cancellation`, `remote_start_permit`, SLURM
  grant/start/publication paths and retained-local cancellation callbacks all
  consume the barrier. `queue/agent_sessions.py:next_control` and
  `queue/agent_session_transport.py` also propagate process control. Apply the
  durable demand decision before these run-based paths can stop a retained
  producer; changing `_cancel` alone is insufficient. Keep administrative
  agent/process containment distinct from a graph-demand detach.
- `sqlite_authority.py:record_output_commit` already atomically records original
  output facts, stage/attempt success and terminal managed binding under its
  current fence. It deliberately admits the ordinary terminal winner during
  cancellation settlement; cancellation is not proof of physical containment.
  Publish a selectable result only from this successful commit, preserving
  replay and `close_managed_attempt_fence` stale-result rejection. A crash after
  commit but before result publication reconstructs the same result from the
  original fact, never another producer or copied commit.
- `local_daemon_execution.py:resume_retained_local_work`,
  `_reconcile_retained_local_assignment`, remote retained delivery, SLURM
  reconciliation and recovery-close paths own restart/unknown-work recovery.
  Reconstruct live demand and claim disposition before replaying cancellation
  callbacks, granting work or rebuilding ready projections. Keep a retained
  producer in these paths even when its creating graph has detached. Unknown
  physical ownership continues to hold capacity under existing recovery policy.
- `pipeline/stores/read_models.py` owns original `OutputCommitRecord` and
  `ArtifactFactRecord` and authoritative stage/run snapshots. Extend the binding
  projection and its orchestration/read consumers to satisfy a consumer node
  from the original outputs without a worker or consumer commit. Graph demand
  status and the retained physical producer status must remain distinguishable.
  `_terminal_outcome`, `_failure_policy_allows_new_work` and
  `queue/_preparation_operations.py:_reconcile_cancellations` must not mistake a
  detached graph for permission to discard or stop shared work.
- `queue/_shared_publication.py` owns immutable closure inventory, publication
  identity and receipt validation. `pipeline/cleanup/preparation_pins.py` already
  provides durable retention references, checked by `cleanup/safety.py` at
  deletion (including ancestor deletion); it has no expiration/unpin policy.
  Extend those cleanup references to retain the original authority/commit and
  complete output closure for live claims, verification and bindings. Preserve
  shared receipts and bytes; a consumer alias does not create a publication.

Smallest compatible sequence:

1. After prerequisites, acquire/attach in the native claim transaction. Bind an
   owner to its original prepared attempt and subsequent assignment/fence through
   the existing authority path. Waiters create demands, not ready attempts.
2. A graph cancellation atomically detaches its demands and prevents new demands
   from that graph. Serialize this with concurrent attachment and final-demand
   selection. Persist which exact claims remain live and which need settlement
   before authority/process effects; retries of cancellation replay that decision.
   A claim already committed to final-demand settlement cannot be revived by a
   racing attachment as permission for another default producer.
3. Keep the run cancellation barrier for ordinary work, but authorize continuing
   shared work only through its durable current claim/attempt ownership. Filter
   containment to assignments whose demand has ended. Retain original assignment
   identity and capacity; never move it to the waiter or manufacture a producer
   run. The existing graph `CANCELLING` state can remain while retained physical
   work settles: finalization still must not pretend a live/unknown binding is
   released. Its graph demands are already detached and cannot schedule more
   graph work. This avoids changing terminal-state meaning merely to report
   immediate cancellation.
4. At final demand, revoke continuation and use existing exact pregrant abort,
   local/remote/SLURM containment, terminal winner and fence-close/release rules.
   Reconcile interrupted handoffs before permitting further effects. Shared
   failure is projected to waiters using existing retry/same-realization recovery;
   it is not a miss. A successful original stage remains selectable if another
   stage later fails or the original graph completes cancellation.
5. Retain the original result before verification, verify outside transactions,
   then atomically publish the consumer binding only after current authorization,
   candidate and retention rechecks. Rebuild the same bindings on restart.

Causal coverage for this refinement (selected using the repository's
`loom-targeted-validation` guidance; no runtime tests run by this prose task):

- New `tests/integration/queue/test_action_result_resolution.py`: pause the
  installed text producer after ownership, attach a differently named graph,
  cancel the original demand and assert one unchanged running assignment/fence,
  then original-commit success and waiter binding. Use a separate final-demand
  cancellation case to prove containment/settlement and stale publication
  rejection, not merely a cancelled queue row. Include attachment versus final
  detach and restart between durable detach and its authority/process effects;
  assert no duplicate producer and no resurrection of a settling claim. Reuse
  the same fixture for successful action in a failed source graph, shared failure
  without silent replacement, and original commit recovery after a lost reply.
- Extend `tests/unit/loom/pipeline/stores/test_sqlite_authority.py` cancellation
  and current-fence tests, `tests/contracts/test_managed_authority_contract.py`
  and `tests/integration/authority/test_coordinator_authority_api.py`: legacy
  epoch fencing stays intact; retained ownership permits only the exact producer;
  final-demand settlement preserves terminal-winner/idempotent-fence semantics;
  embedded and authenticated mutations agree. Exercise the supported in-memory
  authority contract if its shared protocol changes.
- Extend affected existing owners
  `tests/integration/queue/test_{local_daemon_production,agent_session_transport,slurm_ready_stage,reboot_recovery}.py`
  for the local, remote and SLURM cancellation/start/restart paths actually changed.
  These are causal boundary checks using existing fixtures, not a new physical
  deployment matrix. Existing run-wide cancellation must still contain unrelated
  work; a surviving claim must not inherit original-graph cancellation on replay.
- Extend `tests/integration/queue/test_shared_publication.py` and affected cleanup
  tests to attempt deletion while verification/bindings retain the original
  authority and primary/companion closure; assert intact original receipt/bytes
  and inspectable consumer references. Reuse read-model tests for consumer
  satisfaction with no copied commit, including authority reload. Retain the
  existing reconciled-run cancellation tests: whole-target contender ownership
  is adjacent behavior, not evidence for cross-graph action demands.

The manager binds runnable selectors/environments while completing the rest of
U2. Expand only for an affected public codec, authority transport, cancellation
consumer, cleanup path or demonstrated race; preserve the approved final gate.

## Implementation Sequence And Validation Selection

The manager verified the refinement against the actual singleton cancellation
barrier and durable cleanup-pin owner. The named question is resolved; reuse
existing approved protocol/readiness review. No new accepted decision or plan
review is required. Private record/helper names remain implementation discretion.

1. Extend native submission with optional `fresh_stages` at the existing
   `queue/run.py:RunRequest` and `cli/run.py` projection. Preserve legacy decoding
   and absent/empty behavior. Carry selection through idempotent native capture,
   assign/store generation tokens before retryable preparation, validate the
   captured node set before target action work, and include retained generation
   mapping in target identity/publication and action identity. Do not mutate the
   scientific key/seed or implement this as the old force selector.
2. Add versioned causal action identity beside audit/resume fingerprints. Reuse
   qualified resident project/environment/executor evidence from explicitly
   declared installed code/asset roots, including the protected processor and
   configured outer factory/init. Do not include whole captured configuration
   again or heuristic-strip YAML. Insufficient installed qualification means
   conservative non-reuse. Resolve actual inputs through original native
   producer commit/ref/closure bindings and output-spec identity; aliases and
   unrelated nodes stay out. Prerequisites still gate selection.
3. Implement native atomic claim/demand/result selection, exact fenced owner
   handoffs and current graph bindings through the resolved ownership sequence
   above. Reuse authority adapters and original commits across placements;
   migrate durable producers/readers/restart/cleanup together. Failed/interrupted
   shared work cannot become a miss or a second default producer.
4. Extend the one installed processor with `verify_result` and its approved
   candidate-bound verified/rejected responses. Validate native successful commit,
   authorized scope, generation/installation, outputs and complete closure first.
   Pin/verify outside database transactions, then recheck mutable facts at bind.
   Use an installed verification child, never coordinator project imports or a
   second callback registry. Preserve bounded structured artifact-identifying
   failure projection and opaque namespaced project codes. Rejection, corruption
   and malformed/crashed verification must never trigger silent execution.
5. Extend the existing installed text fixture with explicit source qualification,
   graph-specific whole-target keys and the same per-node semantic contract.
   Keep U1 assertions and independently check text/count products. Exercise the
   accepted hit/miss, original input realization, shared demand, failed source
   graph, scope, native integrity, project rejection and default/fresh/replay
   cases through actual native dispatch; use existing boundary tests for each
   changed codec, authority transport and placement cancellation consumer.
6. Update existing public preparation/run/fingerprint/authority/cleanup docs as
   affected, record exact local evidence, and deliver the coherent U2 lifecycle.
   No partial publish-only cache or unsupported deployment narrowing may merge.

Exact initial selectors (refine only for actual changed consumers):

- Config-backed native journey: new
  `tests/integration/queue/test_action_result_resolution.py`, existing
  `test_installed_node_contracts.py`, `test_reconciled_runs.py`,
  `test_run_operations.py`, and `tests/integration/config/test_cli_run.py`.
  Run with `uv run --python 3.12 --isolated --locked --group dev --extra config
  pytest <selected paths>`; do not deselect the required optional_dependency
  cases. The installed fixture needs protected source roots for its project
  implementation; imports-only readiness is insufficient evidence of code bytes.
- Identity/codecs: `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`,
  `test_resume.py`, `tests/unit/loom/queue/test_preparation.py`,
  `test_resident_readiness.py` and affected new action-identity tests. Baseline
  direct selection uses the same locked Python command without config extras.
- Authority/ownership: exact test paths in the refinement above, plus
  `tests/unit/loom/pipeline/test_orchestration.py`, affected materialization
  read-model tests, and `tests/unit/loom/pipeline/cleanup/test_safety.py`.
  Select the required config extra according to each fixture's current marker;
  preserve embedded/authenticated and changed placement boundary obligations.
- Submission projections: add a meaningful fresh selection/replay assertion to
  the existing Python/CLI tests and MCP contract consumer if its run schema is
  affected. MCP checks use `--extra config --extra mcp` in their isolated lane.

The final required `make validate-pr` includes baseline/config-extra/MCP-extra,
Ruff, Pyright and builds. Run it when the implementation tree is stable, retain
its evidence and `git diff --check`, then reuse results across PR/review unless
relevant changes invalidate them. No additional summary run is required.
Skipped mandatory cases remain gaps. Expand for concrete new schema/transport,
ownership race, retention, dependency or failure evidence; no additional
physical deployment matrix is authorized or claimed by these native fixtures.

## Execution Handoff And Record

One optional executor is justified by the coherent changes across native
identity, durable authority, installed verification, cancellation and read models.
The optional executor returned without edits after source discovery; the manager
is implementing U2 locally and owns source/tests/docs, this receipt and delivery.
This execution shortfall is not a missing product decision. Draft U2 PR #332 is open for actual-head review while the required full gate
runs. No full qualification or merge is claimed yet. Stop for an
incompatible approved contract or precisely identified missing product decision;
resolve private wiring in scope. Do not alter U1's accepted public wire shapes.

### Current Implementation Progress

Causal identity and native fresh intent are implemented. Coordinator schema 17
adds atomic claims/demands and offline migration from 12/15/16. Per-run authority
schema 7 and authenticated repository schema 8 add immutable consumer bindings;
read models expose original commits/facts without consumer attempts or copied
commit rows. Native preparation envelope 9 reuses the managed child for installed
`verify_result`; envelope 8 retains fresh generation transport. Reuse opts out
unless protected resident readiness qualifies explicit nonempty source roots.

Current implementation checkpoint:
`4db7181f14924d18ab694333c5668a0c2a47d755`, tree
`2d4c3ddcc0229f738c154ca225ec357fa3dcd652`.
`build/validation/action-result-foundations/{pytest,ruff,pyright}.log` retains
123 focused passes (no skips, 168.73 s), Ruff pass and Pyright zero errors/warnings.
The selection covers preparation codecs, claims/migration, verifier rejection
boundaries, both authority adapters, renamed-graph reuse, fresh/default behavior
with identical output bytes, existing U1 native cases, and authority repositories.
`git diff --check` passed. This is partial evidence, not the final U2 gate.

P7 exposed an existing U1 admission defect: worker metadata freezes nested JSON
lists to tuples, while the retained report remains lists. Native
`validate_admitted_worker` now compares normalized plain data; the installed text
fixture carries nested sequence payloads and the native tests pass. rphys remains
on merged U1 until the corrected U2 implementation is reviewed and merged.

Native producer continuation, final-demand settlement and restart are now
implemented across embedded/authenticated authority and local/remote/SLURM
launch boundaries. Producer permissions name the exact original claim/attempt;
remote and SLURM fence publication joins the existing coordinator transaction.
Public graph cancellation detaches demands in its admission transaction before
any restart can replay work. An authorized original-owner retry retains its
claim; a failed waiter can resume without allocating a consumer attempt. Current
status is preserved when failing a resumed consumer with unavailable input.

The installed verifier receives separately materialized read references; immutable
candidate refs retain original producer identity. Existing shared-publication
verification covers the full receipt and companion closure, and existing native
retention protects original run authority and publications. Projects with local
companions must read them through their protected original-root binding; a copied
primary alone does not establish access to a project-defined closure. Portable
closures use existing shared publication rather than project-aware Loom copying.

Current targeted evidence (development receipts, final gate pending):

- `build/validation/action-result-foundations/cancellation-rejections-development.log`:
  5 passes for local shared cancellation/restart and native corruption,
  project rejection and producer failure.
- `retry-failed-graph-development.log`: 8 passes for authorized producer retry
  and reuse of successful work from a failed source graph with new downstream work.
- `retry-public-cancellation-development.log`: readiness, explicit waiter retry
  and whole-target cancellation checks passed (9); two new cancellation assertions
  had a test-only column typo, corrected before the exact rerun below.
- `public-cancellation-restart-development.log`: 2 passes through public
  cancellation acceptance, atomic demand detach, coordinator restart, surviving
  versus final-demand producer and untouched original commit identity.
- Embedded/authenticated producer continuation: 4 passes; remote/SLURM exact
  grant/start boundaries: 3 passes; artifact-access regression selection: 50 passes.
- CLI fresh forwarding and complete shared-closure retention/integrity passed.
  The initial waiter-retry failure was corrected and its selector passed above.

Exact placement coverage refines the initial fixture paths: native local restart
is in `tests/integration/queue/test_action_result_resolution.py`, authority epoch
and original-input binding in `tests/integration/authority/test_action_{producer_cancellation,result_binding}.py`,
remote grant/start in `tests/unit/loom/queue/test_agent_sessions.py`, and SLURM's
existing transaction owner in `test_action_slurm_grant.py`. Shared primary and
companion corruption/retention uses `tests/unit/loom/pipeline/cleanup/test_safety.py`
with the real shared-publication fixture. The final gate also runs existing
placement, run cancellation, shared-publication and read-model regressions.
These tests exercise the affected native boundaries; no physical deployment
qualification is inferred.

An additional administrative-cancellation regression reproduced that shared
continuation could delay an operator's explicit `cancel_active` control. The
control transaction now moves its exact active claims into settlement before
native containment; graph-demand cancellation remains distinct. The regression
and claim selection tests pass (8), followed by all agent-session and claim tests
(57) in `administrative-cancellation-suite.log`. `final-static.log` records Ruff
pass and Pyright zero errors/warnings after this correction. This source delta
was made while the broader gate ran; its affected tests and static checks were
rerun separately and must be reconciled with that gate's receipt.

The final `make validate-pr` is in progress. An initial gate stopped in Pyright
on new test-fixture typing before suite execution; fixture narrowing/annotations
were corrected. Required suites, diff checks, actual PR-head independent review,
merge and synchronization remain pending. No partial U2 merge is permitted.

Current implementation commit: `49d404518d03bd0414c29055e3cbbff78d898b6c`,
tree `fa5b57c12065cadf48ba04112ef0cf177a24ac89`. Subsequent changes in this
receipt are documentation-only. The draft allows independent review to overlap
the healthy full gate; review and all validation remain mandatory before delivery.

### Broad Gate Reconciliation

The broad gate's baseline completed with 3,069 passes, two skips and two failures
(343 deselected, 1,322.73 s). Both failures were stale fixtures: the authenticated
repository schema assertion still expected 7 instead of 8, and the synthetic
SLURM cancellation database omitted the native action tables. Corrected fixtures
use the current schema and its real initializer. The affected repository suite
plus exact SLURM regression passed (7) in `baseline-fixture-corrections.log`.
No production change resulted. Unaffected baseline evidence is retained rather
than repeating the 22-minute suite. Remaining required gate targets are running
with `make test-config-extra test-mcp-extra build`, retained in
`validate-pr-remaining.log`; these are not yet claimed passed. Final gate status
will reconcile the baseline, the affected corrections and remaining targets.
