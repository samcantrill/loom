# Phase 7A Execution Plan: Ready-Stage SLURM Trust Closure

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 29, Phase 7A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p7a-slurm-ready-stage-trust-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p7a-slurm-ready-stage-trust-closure`
- Base revision: clean `origin/develop`
  `916c62b0e31dca244adf258acd85a2230ef98560`
- PR target: `develop`
- PR title: `feat(scheduling): secure ready-stage SLURM delegation`
- Dependencies: Phase 6 [PR #241](https://github.com/samcantrill/loom/pull/241)
  squash-merged as `2c6d366`; blocked Phase 7 source/test candidate `3515400`
  and [PR #242](https://github.com/samcantrill/loom/pull/242) are selective
  read-only evidence, never a branch base
- Workflow path: expanded because a site-owned capability preparation side
  effect, the irreversible `sbatch` boundary, scheduler-started bootstrap
  registration, and one-root authorization interact causally. Use one bounded
  phase-planner refinement and one independent implementation review.
- Blockers: required review found a verifier-publication race before fast
  bootstrap registration, missing normal terminal provider revocation, and a
  localized flaky parallel-limit wait after correction 3/3 was exhausted.

## Objective And Context

- Vertical outcome: merge the complete explicit ready-stage SLURM route only
  after the allocated job proves possession of one assignment capability,
  submission cannot inherit protected overrides or daemon secrets, an
  unavailable explicit SLURM route cannot starve independent managed work, and
  fresh coordinator processes prove no repeated `sbatch` call.
- Earlier evidence: candidate `3515400` completed route/profile mapping,
  durable at-most-one submission, fixed bootstrap, Phase 5 relay/result,
  authority grant/start, scheduler observation, and mixed-route execution. It
  passed `make validate-pr`, a 2,620-pass categorized summary, focused
  60-unit/21-integration tests, and CI. Required review found the four failures
  this recovery owns after correction `3/3` was exhausted.
- Later work explicitly out of scope: Phase 8 owns ordinary profile reload and
  cancellation composition; Phase 9 owns privileged resolution of unknown
  submission/start outcomes. Automatic route fallback, allocation-fed agents,
  another scheduler backend, and general credential brokerage remain deferred.

## Current Source And Harness

- Start from clean `develop` `5d466bd`. Selectively reuse only production source,
  tests, and feature documentation from candidate `3515400`; do not copy its
  roadmap metadata, commits, schema versions, or branch history.
- Candidate source is concentrated in
  `src/loom/pipeline/executors/slurm/ready_stage.py`,
  `src/loom/pipeline/executors/slurm/commands.py`,
  `src/loom/queue/slurm_ready_stage.py`,
  `src/loom/queue/slurm_bootstrap.py`,
  `src/loom/queue/agent_session_transport.py`,
  `src/loom/queue/local_daemon.py`,
  `src/loom/queue/local_daemon_execution.py`, and the fixed bootstrap CLI.
- Focused candidate coverage is in
  `tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py`,
  `tests/unit/loom/queue/test_slurm_bootstrap.py`, and
  `tests/integration/queue/test_slurm_ready_stage.py`, with adjacent placement,
  daemon, mTLS, remote-relay, and historical whole-run SLURM regressions.
- Preserve `docs/structure.md` import direction. Pure scheduling must not import
  queue, SLURM, transport, or provider implementations. The site capability
  boundary stays protected and private to the concrete ready-stage profile.

## Scope

In scope:

- Selectively restore the accepted Phase 7 vertical path from `3515400` while
  replacing every unmerged durable/wire schema directly with the final Phase
  7A shape.
- Compose one protected concrete `job_private_file_v1` provider binding in each
  ready-stage profile. The site provider owns secret generation, protected
  staging, allocation-only materialization, expiry, and revocation. Loom gives
  it one stable operation identity and retains only its non-secret receipt,
  SHA-256 verifier, expiry, fixed in-job path, and safe immutable descriptor.
  Authored or durable job data may select the already authorized profile alias;
  it may not select provider code, a host staging path, or secret bytes. The
  existing protected profile surface gains only this fixed delivery kind and
  safe identity; it does not gain a generic provider registry or discovery API.
- Persist the complete capability-preparation intent before the first provider
  call. An exact replay after timeout or process loss must return the same
  receipt, verifier, expiry, path, and descriptor; a changed assignment,
  operation, request digest, issuer epoch, profile identity, or policy revision
  conflicts. Persist the exact prepared result before entering `SUBMITTING`.
  Missing, conflicting, or indeterminate preparation causes zero `sbatch`
  calls. Once `SUBMITTING` is durable, restart uses the retained prepared result
  and never calls provider preparation or `sbatch` again.
- Require the selected site deployment to deliver the opaque secret through a
  Slurm prolog or container runtime into one allocation-private, bounded,
  no-follow regular file at the configured fixed path. A normal shared file
  owned only by the job's Unix user is not conforming. The path and safe
  operation marker may be visible; the secret may not enter the generated
  script, argv, scheduler metadata, submit/job environment, durable Loom state,
  status, diagnostics, audit, or logs.
- Keep profile mTLS as transport authentication and a profile/role gate, not as
  assignment authority. The first registration additionally reveals the file
  secret over mTLS. Before returning delivery bytes or allowing any grant, the
  coordinator compares its SHA-256 value in constant time and atomically binds
  and consumes the capability against the exact assignment, operation, request
  digest, issuer epoch, profile descriptor/fingerprint, credential-policy
  revision, scheduler cluster/job handle, and bootstrap incarnation.
- Preserve response-loss replay: the consume transaction durably retains the
  exact non-secret registration result. Repeating the same registration with
  the same capability returns that result; a changed handle, incarnation,
  request, assignment, or secret conflicts without mutation. Another bootstrap
  incarnation cannot consume the capability or obtain a second authored-root
  permit.
- Bootstrap opens the fixed path without following links, bounds and validates
  one regular-file capability, and never copies it to its workspace. It keeps
  the allocation-private file available across a lost registration response;
  only after the exact non-secret registration result is durable locally does
  it unlink the file. Unlink failure is fail-closed before input delivery,
  grant, or authored code. Normal definitive rejection and terminal release
  revoke remaining provider state; unknown preparation, submission, or start
  retains it for Phase 9 rather than assuming containment.
- Add a ready-stage-only submit operation that passes an explicit protected
  environment to `subprocess.run` and supplies `--export=NIL`. It does not
  inherit ambient `SBATCH_*`, `LOOM_*`, token, credential, or key variables;
  the exact minimal safe environment entries remain private to protected site
  composition. Historical whole-run `sbatch` argv/environment behavior remains
  on its existing owner.
- Continue the scheduling cycle after a route-local unavailable/full/unmappable
  SLURM result so independent ready managed work may run. The affected stage
  remains pinned to its exact SLURM profile and never falls back to an agent,
  another profile, or a later candidate.
- Prove restart through newly constructed coordinator/execution/store objects
  for retained prepared, `SUBMITTING`, `ACCEPTED`, and `UNKNOWN` states.
  Reconciliation may associate one exact discovered handle, but no state at or
  after `SUBMITTING` calls provider preparation or `sbatch` again, rotates the
  capability, or permits another authored root.

Conceptually, assignment authentication becomes two-factor:

```python
# mTLS answers: "may this profile talk to the bootstrap endpoint?"
profile = authenticate_transport(peer_certificate)

# The one-use capability answers: "may this allocation claim this assignment?"
registration = verify_and_consume(
    profile=profile,
    secret=read_job_private_file_without_persisting(),
    operation_id=operation_id,
    request_digest=request_digest,
    slurm_job_id=slurm_job_id,
    incarnation=incarnation,
)
# After the exact non-secret registration result is durable locally:
unlink_job_private_file_or_fail_closed()
```

The site provider, not the batch script, owns secret delivery:

```text
persist capability intent
  -> provider.prepare(exact operation) -> verifier + non-secret receipt
  -> persist prepared receipt
  -> persist SUBMITTING
  -> sanitized sbatch --export=NIL
  -> Slurm prolog/container writes allocation-private file
  -> bootstrap reads file without copying it to durable state
  -> coordinator atomically verifies + consumes + retains registration result
  -> bootstrap persists non-secret result, then unlinks before delivery/grant
```

Out of scope:

- Compatibility readers, migrations, dual writes, fallback authorization, or
  recovery of the never-merged Phase 7 candidate schemas and credentials.
- Passing secrets through scripts, arguments, scheduler comments/metadata,
  exported environment, shared user-readable files, Phase 5 relay, or the
  profile-wide TLS credential.
- A public generic secret-provider API, provider discovery/plugin loading, a
  bundled always-on broker, KMS/PKI automation, encrypted durable Loom secrets,
  or proof that arbitrary third-party provider code is trustworthy.
- Changing historical whole-run SLURM planning, submission, status,
  cancellation, manifests, or durable ownership.
- Automatically retrying an unknown submission, switching routes, transparent
  scheduler requeue, or granting another bootstrap after an ambiguous start.

Assumptions:

- The selected site can provision the fixed file using scheduler-privileged or
  container-isolated machinery that distinguishes allocations even when jobs
  share a Unix account. Default CI uses a deterministic conforming fake; a real
  cluster receipt remains opt-in.
- Authored project/config remains trusted, but only protected deployment
  composition selects the profile provider, submit environment allowlist,
  endpoint, certificates, and in-job capability path.
- Conservative unavailable/unknown states may reduce liveness. They never
  authorize fallback, duplicate submission, capability rotation after an
  ambiguous boundary, or a second authored root.

## Fixed Contracts And Private Discretion

- Observable route: the stage remains explicitly pinned to one named profile.
  Provider preflight or a definite preparation failure produces a safe route-
  local diagnostic and zero `sbatch` calls; indeterminate preparation remains
  retained and also causes zero `sbatch` calls. Unrelated managed work remains
  schedulable in either case.
- Provider boundary: `job_private_file_v1` is the only accepted delivery kind.
  Preparation is stable-operation idempotent and returns verifier-only Loom
  state. Its safe descriptor participates in the existing profile fingerprint
  and retained assignment identity. Concrete binding/invocation remains private
  protected-profile wiring; no generic protocol, discovery mechanism,
  serialized live provider, or public conformance package is part of this
  phase.
- Durable ordering: one authoritative coordinator operation owns
  `intent -> prepared receipt -> SUBMITTING -> submit outcome`. Before
  `SUBMITTING`, only exact provider preparation may be replayed. At or after
  `SUBMITTING`, neither preparation nor `sbatch` may be invoked again; only exact
  scheduler-handle reconciliation may advance retained state.
- Registration ordering: transport identity alone can perform only the bounded
  handshake. The assignment owner verifies and consumes the capability in the
  same durable transaction that binds the exact handle/incarnation and retains
  the registration result, before returning delivery. Bootstrap persists that
  non-secret result and removes the file before input, grant, start, result, or
  release. Those later operations require the retained capability-bound
  registration and exact incarnation.
- Submit isolation: ready-stage invocation has a distinct explicit environment
  policy and `--export=NIL`; shared command parsing/discovery helpers may be
  reused, but the historical submit path is observably unchanged.
- Hard cut-over: build the final schema from current `develop` and reject every
  unmerged candidate shape without translation or mutation. No compatibility
  adapter, warning period, or profile-wide authorization fallback is retained.
- Cross-phase boundary: Phase 8 composes ordinary cancellation and provider/
  profile reload; Phase 9 alone resolves unknown provider/submit/start state
  using positive containment. Phase 7A owns normal definitive cleanup only.
- Private choices: exact module/table/helper names; whether final coordinator
  state extends an existing retained record or uses a private companion record;
  provider call signatures; safe receipt/descriptor column layout; secret
  encoding within the bounded file; exact protected submit allowlist; retry
  timing before `SUBMITTING`; SQL indexes; and test fixture layout.

## Proportionality

- Existing seam reused: the validated Phase 7 route, mapping, tagged target,
  submission state machine, bootstrap, Phase 5 relay/result, authority fence,
  and historical SLURM command fakes.
- Material additions and current justification: one private concrete site
  delivery boundary plus verifier/consumption state closes the demonstrated
  cross-assignment claim; ready-stage submit isolation closes ambient override
  and secret export; loop continuation closes demonstrated starvation; fresh-
  object restart tests prove the accepted at-most-one contract.
- Optional hardening and future capability deferred: generic brokers, multiple
  delivery kinds, provider plugins, remote submit gateways, at-rest encryption,
  automatic cleanup of ambiguous work, and stronger scheduler fencing have no
  accepted current consumer.
- Validation follows the independent causal barriers above. Do not multiply
  provider, submit, registration, route-order, and restart cases into a
  Cartesian matrix where the dimensions do not change one another's outcome.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only the allocated job can claim one assignment | Site provider + coordinator capability record | Same-profile credential holder supplies another operation/handle | Cross-run data access or authored execution | Same-profile two-assignment attack, wrong secret/handle/incarnation, exact replay, and zero-mutation rejection |
| Secret delivery never uses visible job inputs | Site provider + ready-stage submit adapter + bootstrap file reader | Script/argv/metadata/environment/shared-file leakage | Credential theft and another assignment claim | Rendered script/argv/environment/SQLite/status/log scan plus shared-user nonconformance tests |
| Provider preparation precedes irreversible submit and is replay-stable | Coordinator capability/submission owner | Crash or timeout around external provider preparation | Job starts without a usable secret or secret rotates under retained work | Separate intent-before-call, response-before-receipt, receipt-before-`SUBMITTING`, and `SUBMITTING` restart barriers with exact provider-call identity |
| Ready-stage `sbatch` cannot inherit overrides or daemon secrets | Ready-stage command adapter | Ambient `SBATCH_*`, `LOOM_*`, token, credential, or private-key variables | Weakened hard mapping or secret export | Real subprocess environment sentinel and exact `--export=NIL` argv; historical-path regression |
| One retained operation causes at most one `sbatch` across real restarts | Submission store + reconciler | Fresh coordinator process opens `SUBMITTING`, `ACCEPTED`, or `UNKNOWN` | Duplicate external job | New-object/store restart matrix with one-call sentinel and exact discovery cardinality |
| Route-local wait cannot starve independent managed work | Coordinator scheduling cycle | First ready SLURM profile is unavailable/full/unmappable | Healthy branch never progresses | Parallel mixed-route permutations; blocked SLURM remains pinned while managed branch completes |
| One capability and fence permit at most one authored root | Capability record + authority start permit + bootstrap journal | Duplicate/requeued bootstrap or lost response | Duplicate authored effects | Consume-before-response replay, local-result-before-unlink replay, different-incarnation rejection, and existing grant/start one-root barriers |
| Historical whole-run SLURM remains unchanged | Existing queue/live owners | Shared command helper or schema port | Regression or competing lifecycle owner | Exact existing contract/integration/E2E suite plus argv/environment separation |

## Implementation Slices

1. Selectively restore candidate source/tests/docs onto the fresh branch,
   replace its schema identities, and establish the existing focused baseline
   without importing blocked workflow metadata.
2. Add the private job-private-file provider binding and authoritative
   intent/prepare/receipt ordering. Keep `sbatch` unreachable until the exact
   prepared result is durable, and prove the four causal preparation barriers.
3. Isolate ready-stage submission environment and `--export=NIL` without
   changing historical whole-run submission; add leakage/override regressions.
4. Add verifier-only consumption and exact registration replay, retaining the
   allocation-private file through response loss and unlinking it after the
   non-secret result is durable but before any delivery/grant/authored code.
5. Continue past route-local waits; add fresh coordinator/store restart
   coverage for prepared, `SUBMITTING`, `ACCEPTED`, and `UNKNOWN`; complete
   normal provider cleanup, redaction, mixed-route/historical regressions, and
   the full gate.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Import direction and dependency weight | New site boundary stays queue/SLURM-private; public imports remain intentional; no new dependency |
| Unit | required | Provider preparation, capability state, file safety, submit environment, resource mapping, scheduler continuation | Exact preparation replay/conflict/expiry; causal prepare barriers; wrong/missing/shared file rejection; secret absent from durable/observable state; forbidden ambient variables absent; `--export=NIL`; route-local continuation |
| Contract | required | Final tagged assignment/submission/bootstrap shapes and least-privilege view | Candidate schema rejects untouched; profile mTLS alone cannot register; exact consumed replay succeeds; changed binding conflicts; no broad role operation |
| Integration | required | Full dispatcher/bootstrap/relay/result path across the causal barriers | Same-profile attack rejected; consumed-response replay succeeds before file unlink; unlink precedes delivery/grant; fresh coordinator objects never prepare/resubmit; independent managed work progresses; one authored root |
| E2E / opt-in | mixed | Simulated mixed-route run and historical regression required; real provider/cluster environment-dependent | `preprocess(agent) -> train(SLURM) -> evaluate(agent)` completes with safe secret lifecycle; opt-in receipt proves allocation-private file and exact job binding |

Targeted commands:

    uv run pytest -q tests/unit/loom/pipeline/executors/slurm/test_ready_stage.py
    uv run pytest -q tests/unit/loom/queue/test_slurm_bootstrap.py
    uv run pytest -q tests/integration/queue/test_slurm_ready_stage.py
    uv run pytest -q tests/unit/loom/queue/test_local_daemon.py
    uv run pytest -q tests/integration/queue/test_agent_session_transport.py
    uv run pytest -q tests/unit/loom/pipeline/executors/slurm tests/unit/loom/queue/test_slurm_adapter.py
    uv run pytest -q tests/contracts/test_queue_delegated_slurm_contract.py tests/integration/queue/test_delegated_slurm_controller.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: treating a same-user `0600` file as allocation-private; allowing
  profile mTLS to bypass capability proof; retaining raw secrets coordinator-
  or bootstrap-workspace-side; unlinking before a consumed response can be
  replayed or after delivery/grant begins; provider prepare after `SUBMITTING`;
  secret rotation after ambiguity; leaking ambient `SBATCH_*`/daemon variables;
  changing historical submission; returning on a route-local wait; or testing
  restart with the same object.
- Review focus: concrete provider ownership and conformance, verifier-only
  durability/redaction, exact preparation/submit/register/unlink order, handle/
  incarnation binding, consumed-response replay, ready-stage-only environment,
  mixed-route continuation, fresh-process zero-reprepare/one-submit evidence,
  one root, and historical whole-run isolation.
- Stop if the selected provider cannot distinguish allocations sharing a Unix
  account; secret bytes must enter the generated script, argv, scheduler
  metadata, submit/job environment, shared user storage, or durable Loom/
  bootstrap state; provider preparation cannot replay one stable operation;
  the current protected profile composition cannot hold the provider without a
  new public framework; a hard resource request must weaken; registration needs
  profile-wide authority; a second `sbatch` or root remains reachable;
  historical whole-run ownership must change; or any new material public,
  durable, deployment, compatibility, or migration decision appears.
- Accepted debt and revisit trigger: capability-provider or coordinator outage
  can strand an explicit SLURM stage; unknown preparation/submission/start
  retains provider/profile capacity until Phase 9; real-cluster evidence is
  opt-in. Revisit only with a concrete credential-broker requirement, stronger
  scheduler identity API, remote submit gateway, or automated unknown-work
  recovery contract.

## Executor Handoff

- Read this file from `Current Source And Harness` through `Risks, Review, And
  Stops`, plus manifest `Summary`, `Shared Constraints`, `Phase Index`, and
  `Quality Gate` where they cite Phase 7A.
- Own selective Phase 7 source/test/feature-doc reuse, the four reviewed
  closures, and this phase-plan workflow/completion state inside the dedicated
  worktree. Preserve unrelated work and do not delegate.
- Use the five implementation slices in order. Keep `sbatch` disabled until
  capability preparation and environment-isolation tests pass; keep authored
  root launch disabled until capability consumption/grant/start tests pass.
- Do not revisit the approved job-private-file contract, hard cut-over, explicit
  route/no fallback, verifier-only Loom state, authority lifecycle ownership,
  Phase 5 relay/result ownership, or historical whole-run separation.
- Return a qualified blocker if a stop condition occurs, the candidate cannot
  be selectively ported without reopening an accepted contract, or the real
  provider boundary cannot be represented without an unused public framework.
  Do not substitute a same-user file, environment credential, or profile-wide
  authorization to keep implementation moving.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `916c62b`; dedicated
  branch/worktree, repository `samcantrill/loom`, predecessor merge, blocked
  candidate evidence, source/test owners, target/title, validation gates, and
  stop conditions verified
- Expanded planning: complete; the provider owner, causal crash/replay order,
  private implementation discretion, proportional validation, and stop
  conditions are implementation-ready with no reopened decision
- Implementation: complete locally; selective Phase 7 vertical now uses the
  concrete `job_private_file_v1` binding, verifier-only assignment consumption,
  ready-stage-only `--export=NIL` submission, route-local continuation, and
  final schemas.
- Refiner: correction 1/3 complete locally: replaced the process-local
  capability fake with the concrete strict site-helper adapter, moved
  capability proof ahead of scheduler-handle mutation, and added fresh-daemon
  retained-submission evidence. Correction 2/3 complete locally: added causal
  fresh-object prepared/`SUBMITTING`/`ACCEPTED`/`UNKNOWN` submission evidence
  and proved an unavailable pinned SLURM root does not starve an independent
  managed root. Correction 3/3 complete locally: repaired the new crash-barrier
  test callbacks' static types and kept process-launch support lazy after the
  full pre-submit gate exposed both defects.
- Pre-submit gate: complete at validated implementation revision `ac1bfd9`;
  focused Phase 7A selectors, `make validate-pr`, `make test-summary`, and
  `git diff --check` passed
- Independent review: complete at head `a70986c`; blocked because a fast
  allocation can register while the assignment verifier is still null, normal
  terminal release never revokes provider state, and the parallel-limit test
  waits for calls rather than accepted mirrors
- Blocker corrections: 3/3 exhausted
- Phase status: blocked; no PR opened and no merge attempted

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Restored the Phase 7 ready-stage vertical under `src/loom/` and closed its capability, submission, registration, bootstrap, and scheduler-loop boundaries; correction 1 replaces the process-local raw-secret provider with one strict non-secret site-helper adapter, makes helper replay survive fresh provider construction, revokes on definite submit rejection, and verifies/consumes capability before any scheduler-handle mutation. Updated `docs/features/slurm.md`. |
| Tests added or updated | Added deterministic protected-site helper coverage for verifier-only replay/materialization, malformed or unavailable helper zero-submit, definite-rejection revocation, wrong-capability zero-mutation, and fresh daemon/provider retained-acceptance zero-resubmit; retained ready-stage transport coverage uses the fake materialized file rather than a production test escape hatch. Correction 2 adds fresh replacement provider/runner/store evidence for retained prepared, `SUBMITTING`, `ACCEPTED`, and `UNKNOWN` states, including exact unknown-handle reconciliation, plus an unavailable pinned SLURM root alongside a completing independent managed root. |
| Validated revision/tree state and evidence | Implementation revision `ac1bfd9` passed the focused Phase 7A matrix (153 passed), `make validate-pr` (Ruff; Pyright 0 errors; default 2,490 passed; config-extra 141 passed and 3 skipped; package build passed), `make test-summary` (overall passed: 2,631 passed, 3 skipped), and `git diff --check`. |
| Validation-relevant changes after evidence | none; this completion-record update is documentation-only |
| PR, review, and merge | Required independent review blocked submission. No PR was opened. Preserve the branch and validated implementation `ac1bfd9` as read-only evidence; correction 3/3 is exhausted. |
| Residual risk and cleanup | Supported fast bootstrap can receive a definitive conflict before the verifier reaches the assignment owner; successful terminal release leaves site provider state unreleased; the parallel-limit integration wait is flaky. Unknown preparation/submission/start containment remains Phase 9, and a real protected site-helper/prolog receipt remains opt-in. |
