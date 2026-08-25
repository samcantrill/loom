# Phase 7B Execution Plan: Ready-Stage SLURM Lifecycle Closure

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 7B
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p7b-slurm-ready-stage-lifecycle-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p7b-slurm-ready-stage-lifecycle-closure`
- Base revision: clean `origin/develop`
  `84ccb2a77c6e39268bdb07edba594bc82bf0c187`
- PR target: `develop`
- PR title: `feat(scheduling): close ready-stage SLURM lifecycle ordering`
- Dependencies: Phase 6 merged as `2c6d366`; Phase 7 candidate `3515400` and
  Phase 7A implementation `ac1bfd9` are selective read-only source/test
  evidence, never branch bases
- Workflow path: expanded because verifier publication and provider revocation
  cross durable assignment/submission ownership on opposite sides of the
  irreversible `sbatch` and final-release boundaries
- Blockers: none. The maintainer approved this fresh hard-cut recovery and no
  compatibility with either unmerged candidate.

## Objective And Context

- Vertical outcome: one explicitly routed ready stage prepares one private
  allocation capability, makes its verifier authoritative before Slurm can
  start the job, submits at most once, registers exactly once, executes through
  the existing relay/result path, and revokes provider state before final
  release.
- Earlier evidence: Phase 7A closed inherited environment leakage,
  profile-wide assignment authority, route-local starvation, and restart-proof
  gaps. Implementation `ac1bfd9` passed 153 focused tests, `make validate-pr`,
  and 2,631 categorized tests. Required review then demonstrated a fast-job
  verifier-publication race, missing normal terminal provider revocation, and
  one localized parallel-limit test wait after correction 3/3.
- Later work explicitly out of scope: Phase 8 owns ordinary cancellation and
  profile reload; Phase 9 owns containment and operator resolution for unknown
  preparation, submission, start, and cleanup outcomes. Automatic route
  fallback, allocation-fed agents, another scheduler backend, and a generic
  credential provider framework remain deferred.

## Current Source And Harness

- Current `develop` contains no Phase 7/7A production source. Selective evidence
  is available on `agent/stage-29-p7a-slurm-ready-stage-trust-closure`, with
  validated source/test revision `ac1bfd9` and blocked metadata head `bfa5eab`.
- The preparation/submission owner is
  `src/loom/pipeline/executors/slurm/ready_stage.py`;
  `src/loom/queue/slurm_ready_stage.py` owns assignment authorization state;
  `src/loom/queue/local_daemon_execution.py` composes both owners and the two
  release entry paths. The fixed bootstrap remains in
  `src/loom/queue/slurm_bootstrap.py` and its CLI adapter.
- Focused evidence is in
  `tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py`,
  `tests/unit/loom/queue/test_slurm_bootstrap.py`,
  `tests/integration/queue/test_slurm_ready_stage.py`, and
  `tests/integration/queue/test_agent_session_transport.py`.
- Preserve `docs/structure.md` import direction and cheap SLURM package imports.
  Use the standard library only; process-launch support remains lazy.

## Scope

In scope:

- Selectively restore the validated Phase 7A vertical source, tests, and feature
  documentation onto a fresh branch from current `develop`.
- Split capability preparation from the external submission call sufficiently
  for the assignment authorization owner to durably install the exact verifier
  before the submission owner can enter `SUBMITTING`. Mirror that eligible
  submission state to the authorization owner before `sbatch`, so a bootstrap
  that registers inside the synchronous call sees both facts.
- Keep the retained prepared receipt replay-stable. A crash before verifier
  publication replays only the same handoff; a crash after publication but
  before `SUBMITTING` may make the one permitted submit; at or after
  `SUBMITTING`, neither provider preparation nor `sbatch` runs again.
- Make provider revocation the required replay-safe step between definite
  coordinator terminal reconciliation. Definite submit rejection enters that
  same owner instead of calling the provider directly.
- Repair the parallel-limit integration wait so completion is caused by the
  expected submit count and accepted assignment mirrors; for the limiting case,
  also observe a later limit decision while the first assignment is retained.
- Use request, submission, and delivery schema version 3 and helper envelope
  version 2. Reject the unmerged Phase 7 version-1 and Phase 7A version-2
  durable/wire shapes, the Phase 7A helper version-1 envelope, and either old
  assignment-store column set without migration or mutation. Retain the
  approved `job_private_file_v1` delivery kind; helper-envelope version and
  delivery kind are separate contracts.

Out of scope:

- Retrying or redispatching unknown submissions; revoking state whose
  preparation, submission, start, or containment remains unknown; cancellation
  fan-out; profile reload; provider plugins; broker discovery; scheduler
  identity inference; automatic fallback; historical whole-run SLURM changes.
- A compatibility adapter, migration command, warning period, or support for
  blocked candidate roots/config/protocol documents.

Assumptions:

- The approved site helper can replay exact prepare and revoke operations by
  stable non-secret identity, and only site machinery can materialize the
  secret inside one allocation-private file.
- The secret is unavailable before allocation materialization. Publishing its
  verifier before `sbatch` therefore grants no profile-wide authority;
  registration still requires the correct route, operation, request, profile,
  policy, job handle, bootstrap incarnation, and eligible submission state.
- Authored configuration remains trusted project code, but cannot select helper
  code, host staging paths, secret bytes, or a compatibility path.

## Fixed Contracts And Private Discretion

- Observable behavior: a fast allocation may register while the coordinator's
  synchronous `sbatch` call is still in progress and must succeed when its exact
  secret and binding match. Wrong or early unsupported registration fails with
  zero mutation. Exactly one authored root remains possible.
- Durable order: `intent -> prepared receipt -> assignment verifier installed
  -> SUBMITTING -> authorization owner records submission eligibility -> sbatch
  -> submit outcome`. `SUBMITTING` remains the at-most-once external-call
  barrier; `sbatch` is unreachable until both owner-local commits are visible.
  The authorization owner accepts only an exact idempotent verifier handoff;
  changed assignment/operation/request/profile/policy or verifier conflicts
  with zero mutation.
- Release order: authoritative terminal result or definite submit rejection ->
  logical release -> exact provider revoke -> final released. A definite revoke
  failure or indeterminate response leaves cleanup retryable and does not
  advertise final release.
- Unknown behavior: for unknown preparation, submission, or start, no provider
  revoke, external retry, resubmit, fallback, or release claim is inferred from
  absence or transport failure. Phase 9 owns positive containment.
- Trust boundary: Loom durably stores only the non-secret receipt/verifier/
  expiry/path/descriptor. Secret bytes never enter script, argv, scheduler
  metadata, submit/job environment, durable Loom/bootstrap state, diagnostics,
  status, logs, or shared same-user files.
- Compatibility: hard cut. The final ready-stage request, submission, and
  delivery versions are 3; the final site-helper request/response envelope is
  version 2; and both ready-stage SQLite stores require `PRAGMA user_version =
  3` plus their final exact table/column sets. Decoders/openers reject old,
  unversioned, or mixed shapes before mutation, and helper responses must match
  the final exact field set. Existing merged whole-run SLURM behavior and its
  command environment remain unchanged.
- Private choices: exact private method/callback names, how the existing
  composition invokes each owner, internal retry scheduling, and test fixture
  layout. Reuse the assignment owner's existing logical/final release states;
  do not add a new public provider protocol, generic lifecycle framework,
  distributed transaction, migration surface, or compatibility adapter.

## Causal Handoff And Release Protocol

Verifier publication and submission use the two existing durable owners in this
fixed order:

1. The submission owner creates/replays the intent, invokes or exactly replays
   the stable provider prepare operation under one operation identity, and
   commits one complete non-secret prepared receipt. A response lost before
   that commit may repeat the same provider operation, never rotate its identity.
2. The composition hands that retained verifier to the assignment authorization
   owner with the exact assignment, operation, request, profile, and policy
   binding. The owner commits absent-to-exact once, accepts an exact replay, and
   rejects any changed binding or verifier without mutation. A lost handoff
   response therefore replays only this step; preparation and `sbatch` remain
   unreachable.
3. Only after the handoff succeeds may the submission owner commit
   `SUBMITTING`. The composition then records the matching submission-eligible
   state in the authorization owner before entering the runner. Once
   `SUBMITTING` exists, restart/reconciliation never invokes prepare or `sbatch`
   again; it may only replay the exact authorization-owner mirror and reconcile
   external evidence.
4. The synchronous `sbatch` call is last. Registration during that call accepts
   the exact capability and binding because the verifier and eligible state are
   already authoritative. Registration before eligibility, with a changed
   binding, or without the verifier fails with zero mutation. The later exact
   submit response may associate the same handle; a different handle conflicts.

Crash coverage must distinguish: receipt commit before handoff, handoff commit
before/lost response, handoff before `SUBMITTING`, `SUBMITTING` before its exact
authorization mirror, the mirror before runner entry, bootstrap registration
inside the runner call, and the existing call/response/outcome commits. Only a
crash strictly before `SUBMITTING` may resume the one permitted submit.

The existing local-daemon release composition is the sole provider-revoke-before-
final-release owner. Definite submission rejection, authenticated bootstrap
release after terminal result, and coordinator terminal reconciliation all
request logical release through it. It reads the exact retained provider receipt
from the submission owner, verifies the assignment/operation/profile binding,
replays the stable provider revoke operation, and asks the assignment owner for
final `released` only after a definite exact helper acknowledgement. Helper
failure, malformed response, timeout, or response loss leaves logical release
durable and retryable with the same receipt; exact replay after a committed
final release is already successful. Submission/bootstrap states whose prepare,
submit, or start outcome is unknown never enter this cleanup path. That unknown
containment remains Phase 9; ambiguity of a revoke response for already-
releasable work is instead handled by exact idempotent revoke replay here.

## Proportionality

- Existing seam reused: the validated Phase 7A route, mapping, site-helper
  adapter, verifier comparison, bootstrap, relay/result, submission state
  machine, assignment lifecycle, and route-local continuation.
- Material additions and current justification: one pre-submit verifier handoff
  closes the reproduced fast-bootstrap rejection; one shared retryable revoke-
  before-release operation closes the demonstrated provider-lifetime leak; one
  corrected wait removes observed test nondeterminism.
- Optional hardening and future capability deferred: external fencing,
  encrypted receipts, generalized provider discovery, automatic ambiguous
  cleanup, and broader cancellation/recovery belong to later accepted work or
  have no current consumer.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Registration always sees the prepared verifier and eligible state once a job can start | Assignment authorization owner, fed in order by submission composition before runner entry | Scheduler starts bootstrap before synchronous `sbatch` returns | Legitimate job receives definitive conflict and stage strands | Runner barrier invokes real registration before returning the job handle; pre-eligibility registration mutates nothing |
| One operation retains one preparation and submits at most once across crashes | Ready-stage submission store | Crash or response loss before/after prepared receipt, verifier handoff, `SUBMITTING`, authorization mirror, or runner entry | Rotated secret or duplicate job | Fresh provider/runner/store crash matrix distinguishes every named edge with exact operation/call sentinels |
| Wrong capability or changed binding mutates nothing | Assignment authorization transaction | Same-profile caller or concurrent different job/incarnation | Cross-assignment claim or consumed valid capability | Before/after snapshots plus concurrent exact replay/conflict |
| Definite completion or rejection cannot outlive provider capability state | Local-daemon release composition, with assignment owner holding release state and site helper owning physical revoke | Definite submit rejection, bootstrap release, coordinator reconciliation, helper timeout/response loss | Rematerializable secret or leaked provider capacity after `released` | All three entries converge on one operation; ack loss replays exact revoke; helper failure cannot commit final release |
| Unknown work is retained, not guessed safe | Phase 9 boundary enforced by Phase 7B release logic | Unknown preparation, submission, or start outcome | Unsafe duplicate or premature cleanup | Negative tests prove no revoke/final release for those ambiguous states; ambiguous revoke responses after definite logical release instead replay exactly |
| Unmerged candidate state cannot be adopted accidentally | Final codec/store/helper version checks | Phase 7/7A database, serialized value, delivery, or helper response | Silent mixed-contract execution or unsafe replay | Both prior versions, unversioned stores, mixed current/old fields, and helper envelopes reject before mutation |
| Historical whole-run SLURM remains unchanged | Existing whole-run command owner | Shared command/helper edits | Existing submissions change environment or lifecycle | Existing contract/integration/E2E regressions and exact argv/environment split |

## Implementation Slices

1. Selectively restore Phase 7A source/tests/docs onto current `develop`; set
   request/submission/delivery and both SQLite-store identities to 3 and the
   helper envelope to 2; establish the focused baseline without importing
   blocked roadmap metadata or branch history.
2. Separate replay-stable preparation, verifier publication, submission-state
   commits, and runner entry at the existing composition seam. Add the exact
   authorization-owner handoff, eligible-state mirror, fast-bootstrap barrier,
   and every named crash-order test before enabling `sbatch`.
3. Remove the submission owner's direct rejection revoke and route definite
   rejection, bootstrap release, and terminal reconciliation through the one
   local-daemon revoke-before-final-release operation. Retain logical release on
   helper failure or response ambiguity and leave Phase 9 unknowns untouched.
4. Replace the parallel-limit sleep with a joint accepted-mirror predicate and
   a post-acceptance limit-decision barrier for the one-slot case; retain
   route-local continuation,
   response-loss registration, one-root, redaction, import-boundary, and
   historical whole-run regressions.
5. Complete the focused matrix, full validation, categorized evidence,
   independent review, PR, CI, and squash merge.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Import direction and cheap public imports | No eager `subprocess`, queue dependency from pure layers, or new public surface |
| Unit | required | Prepare/publish/submit and cleanup ordering | Crash at each named causal barrier; stable prepare replay; zero rotated prepare/resubmit; all three release entries use one revoke owner; ack loss retries exact revoke |
| Contract | required | Final durable/wire/helper shapes and least privilege | Version-1/version-2 and unversioned/mixed stores or payloads reject before mutation; helper v1 rejects; mTLS alone insufficient; exact capability result replay only |
| Integration | required | Real coordinator/bootstrap interleaving and release convergence | Registration succeeds inside blocked `sbatch`; definite rejection/bootstrap/coordinator cleanup each revoke then release; helper outage stays logically released and retryable; parallel limit uses causal barriers |
| E2E / opt-in | mixed | Mixed managed/SLURM vertical and historical regression required; real site helper remains opt-in | One submit/root/result/revoke, no starvation/fallback, unchanged whole-run behavior |

Targeted commands:

    uv run pytest -q tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py
    uv run pytest -q tests/unit/loom/queue/test_slurm_bootstrap.py
    uv run pytest -q tests/integration/queue/test_slurm_ready_stage.py
    uv run pytest -q tests/unit/loom/queue/test_local_daemon.py
    uv run pytest -q tests/integration/queue/test_agent_session_transport.py
    uv run pytest -q tests/unit/loom/pipeline/executors/slurm tests/unit/loom/queue/test_slurm_adapter.py
    uv run pytest -q tests/contracts/test_queue_delegated_slurm_contract.py tests/integration/queue/test_delegated_slurm_controller.py
    uv run pytest -q tests/package/test_import_boundaries.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: publishing only submission-store state while the authorization
  owner remains null; allowing registration before an eligible submit state;
  calling `sbatch` before the verifier handoff and eligible-state mirror commit;
  treating a committed handoff with a lost response as conflict; rotating
  preparation on replay; invoking a second `sbatch` after `SUBMITTING`; retaining
  the rejection-only direct revoke; marking `released` before a definite revoke
  acknowledgement; silently dropping a lost revoke response; revoking unknown
  work; accepting either candidate schema/helper envelope; using elapsed time as
  parallel-limit evidence; or changing whole-run submission.
- Review focus: the exact receipt/handoff/`SUBMITTING`/authorization-mirror/
  runner sequence, registration inside synchronous `sbatch`, exact crash replay,
  one release-composition owner across all three entry paths, retryable revoke
  semantics, version-3 store/wire and helper-v2 hard cuts, secret redaction, no
  fallback, one root, and the post-acceptance limit-decision barrier.
- Stop if the verifier cannot become authoritative before `sbatch` without
  profile-wide authorization; registration cannot be made eligible before
  runner entry without weakening the at-most-once barrier; the three definite
  release entries cannot share one exact retained receipt and release owner;
  release requires guessing containment; provider revoke is not stable-operation
  idempotent; secret bytes must enter a visible channel; a second submit/root
  remains reachable; the hard cut needs migration/compatibility; or the fix
  requires a new public provider framework or Phase 8/9 behavior.
- Accepted debt and revisit trigger: unknown cleanup may hold provider state and
  capacity until Phase 9 positive containment. A real site-helper/prolog receipt
  remains opt-in until a configured cluster is available.

## Executor Handoff

- Read `Metadata` through `Implementation Slices`, then `Test And Validation
  Plan` and `Risks, Review, And Stops`.
- Safe implementation slices: selective Phase 7A source/test port; final schema
  cut; exact verifier handoff before `SUBMITTING`; eligible-state mirror before
  `sbatch`; shared retryable revoke-before-release; causal tests; feature
  documentation.
- Decisions not to revisit: allocation-private file provider, verifier-only Loom
  state, profile mTLS as transport-only, hard cut with no migration, explicit
  route/no fallback, Phase 5 relay/result ownership, historical whole-run
  separation, and Phase 8/9 boundaries.
- Conditions requiring manager action: any stop condition, new public/durable
  design choice, inability to preserve one-submit/root, or scope outside the
  named source/tests/docs.

## Workflow State

- Manager planning: complete; maintainer approved the fresh Phase 7B recovery
- Manager preparation: complete; dedicated branch/worktree created from clean
  `origin/develop` `84ccb2a`, repository `samcantrill/loom`, target/title,
  predecessor evidence, write boundaries, gates, and stop conditions verified
- Expanded planning: complete; the exact idempotent verifier handoff and
  pre-runner eligibility order, three-entry shared revoke-before-release owner,
  version-3/helper-v2 hard cut, causal parallel-limit barrier, crash/replay
  coverage, private discretion, and Phase 9 stop boundary are implementation-
  ready with no reopened decision
- Implementation: complete; Phase 7A's selected vertical source/test/doc
  baseline is restored with the final v3/helper-v2 hard cut, pre-`sbatch`
  verifier/eligibility ordering, and shared revoke-before-final-release owner
- Refiner: correction 2/3 complete; both terminal-return sites reconcile exact
  retained SLURM result/binding/fence evidence and use the shared
  revoke-before-final-release owner before terminal admission return
- Manager correction: correction 3/3 makes the intermediate `terminal` state an
  exact replay that continues to logical release; the full gate exposed the
  coordinator/bootstrap concurrency window after focused validation
- Pre-submit gate: pending a fresh full run after correction 3/3
- Independent review: complete; its terminal-reconciliation blocker is addressed
- Blocker corrections: 3/3; no further correction pass remains
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Corrections 1-2 gate both terminal admission returns through exact authority/assignment reconciliation and the shared revoke owner. Correction 3 makes a retained intermediate `terminal` transition replay-safe under coordinator/bootstrap concurrency. |
| Tests added or updated | Restored the successful mixed-route end-to-end replay, final run state, one-root, script-redaction, and release assertions. Separate integration cases now stop causally after authority-result and the actual assignment-`terminal` commit, then lose the first revoke acknowledgement and require replay before `released`. |
| Validated revision/tree state and evidence | Focused and full validation pending after correction 3/3; the preceding full gate exposed the now-corrected intermediate-terminal replay conflict after 2,494 other tests passed. |
| Validation-relevant changes after evidence | None. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Unknown containment remains Phase 9; real site-helper/prolog validation remains opt-in. No further qualified blocker is known. |
