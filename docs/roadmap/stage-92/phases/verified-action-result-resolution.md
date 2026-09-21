# Phase 2: Verified Action Result Resolution And Fresh Execution

## Metadata And Scope

- Status: merged; PR #332, required local validation and independent actual-head review passed.
- Base: `32f8d90d4af6ea8f0e4ccb78a024b5dc7de67ed2`.
- U1: PR #331 merged at `a0d29b3fedac7495bbb994e630b07aa41f7cf579`; metadata published and shared synchronization passed at the base above.
- Coordination branch: `agent/stage-92`; use the manifest's clean control and stage worktree paths.
- Branch: `agent/stage-92-p2-verified-action-result-resolution`.
- PR title: `Stage 92 Native Project Contracts And Result Resolution - Phase 2: Verified Action Result Resolution And Fresh Execution`.
- PR: https://github.com/samcantrill/loom/pull/332 (merged).
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

The manager implemented U2 after the optional executor returned discovery without
edits. The complete native lifecycle is on PR #332; no partial U2 delivery is
claimed. The implementation uses coordinator schema 17, per-run authority schema
7, authenticated repository schema 8 and preparation envelopes 8/9. Legacy
readers and whole-target reconciliation remain supported.

Native causal identity separates project semantics, installed implementation,
actual original committed inputs, output contracts and fresh generation from
captured graph authorship. Qualified claims and graph demands own one producer;
consumer bindings preserve original commits/facts without consumer attempts or
copied commits. Installed `verify_result` runs in the existing preparation child.
Native integrity/retention checks precede and follow project verification.

Exact producer permissions preserve work for surviving graph demand across
cancellation and restart. Final-demand cancellation cannot revive ownership.
Administrative `cancel_active` settles its exact active producer even when another
graph wants its result. Original-owner and failed-waiter retries remain explicit.
Remote/SLURM grant/start publication joins the current coordinator transaction.

The verifier receives materialized read references separately from immutable
candidate identity. Existing shared-publication receipts protect complete portable
closures. Local project companions require the protected original-root binding;
a copied primary alone does not establish companion access. No domain-aware copy,
scientific failure enum, extra registry or project scheduler was added to Loom.

P7 exposed U1's list/tuple attachment comparison defect. Native validation now
normalizes plain metadata, covered by nested sequence payloads in the installed
fixture. rphys must consume the merged corrected revision and qualify its image.

### Validation And Evidence Reconciliation

Final production revision: `28cde46b27fcb53ca903bf5941e0ad871e41c6a5`, tree
`71072cd05f52e4c087dfaff5dbc75326c62e6b51`. Later changes are two schema-test
fixtures and this delivery receipt; production code is unchanged. All evidence
below is under `build/validation/action-result-foundations/`.

The required `make validate-pr` components are satisfied by the broad runs and
bounded reruns below. The initial aggregate command did not exit successfully;
its fixture failures and intervening production corrections are explicitly
reconciled instead of repeating unaffected long suites.

| Gate / evidence | Result and applicability |
| --- | --- |
| `validate-pr.log` baseline | 3,069 passed, two skipped, two stale fixture failures, 343 deselected; 1,322.73 s. Repository schema expectation and synthetic SLURM database corrected. |
| `baseline-fixture-corrections.log` | Seven affected repository/SLURM checks passed; no production delta. |
| `validate-pr-remaining.log` config-extra | 289 passed, 15 skipped, eight failures, 3,123 deselected; 2,391.46 s. Seven failures were predecessor-schema fixtures; one qualified retry timed out on the production revision loaded before the review correction. |
| `config-gate-corrections.log` | Nine passed, 104.33 s: all seven schema cases and both qualified/unqualified retry variants. Predecessor fixtures remove tables absent from schemas 12/15 and expect coordinator schema 17; data/journal/restart assertions remain. The reviewed terminal-producer reconciliation closes the retry failure without another production edit. |
| `mcp-build-gate.log` | 45 MCP tests passed, 3,375 deselected; 98.88 s. Source distribution and wheel built successfully. |
| `administrative-cancellation-suite.log`, `final-static.log` | 57 agent-session/claim checks passed after the administrative containment correction; Ruff pass, Pyright zero errors/warnings. |
| `review-correction-regressions.log`, `review-correction-static.log` | 26 native action-resolution, rejection/retry, failure-policy and both-authority regressions passed, 328.22 s; Ruff pass, Pyright zero errors. |
| `fail-fast-action-regression.log` | Seven focused authority/native fail-fast and explicit retry checks passed. |

Changed schema fixtures pass Ruff; `git diff --check` passes. Earlier 123-test
foundation evidence and subsequent selected lifecycle/closure checks remain
supporting development receipts, not substitutes for the reconciled final gate.
Two baseline skips require optional `python-dotenv` in the isolated environment;
15 configuration skips are explicitly gated physical container acceptance. The
native U1/U2 journeys executed. These runs do not qualify physical fleets,
SLURM installations or the changed rphys container.

### Independent Review And Delivery

The required independent reviewer reviewed PR #332 at
`c6258ea3bec2193d5e91aa575ce6f765bbc4058c` and found one product blocker:
fail-fast termination could strand an owned prepared producer that could no
longer launch, making a later equivalent graph wait forever.

The correction at `28cde46b27fcb53ca903bf5941e0ad871e41c6a5` reconciles claims
at terminal run settlement and consumer observation. Native authority settles the
exact pending stage and attempt together with its continuation permission,
refusing abandonment with a live execution binding. Waiters fail explicitly;
authorized original-owner and waiter retry retain consistent native history.
The one-CPU native regression proves this sequence and original-result reuse.

The same reviewer confirmed that exact head: blocker resolved, no remaining
concrete blocker. The initial review and correction confirmation remain valid
for unchanged production code. Final verification accounts for the two later
schema fixtures and completed validation receipt before delivery. PR #332 merged at `14d8715e42e24405e86d4bcdc1ec31e0f479f6ad` after final
independent head verification approved `4bc2e351eedcd4d62e7b77b35c3fb450b819f176`.
The delivery helper verified the remote merge and leased deletion of that exact
remote phase branch. Shared transition passed. Metadata publication, final sync
and exact local cleanup follow on the coordination branch.

Retained U1/U2 raw validation archive before stage cleanup:
`/nas/home/can134/scratch/rphys/loom-native-action-validation-ltlfjzrb/validation`. No unknown or unrelated work is included.
