# Phase 4A Execution Plan: Authenticated Agent Trust Closure

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 4A
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p4a-authenticated-agent-trust-closure`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p4a-authenticated-agent-trust-closure`
- Base revision: clean `origin/develop`
  `922237c352548abe7c7affc9768ab02510791924`
- PR target: `develop`
- PR title: `feat(protocols): complete authenticated agent sessions`
- Dependencies: Phase 3D merged; Phase 4 and PR #238 are blocked read-only
  evidence and are not a branch base
- Workflow path: expanded for one independent implementation review because
  this phase closes a demonstrated remote trust-boundary failure. No phase
  planner is needed: the maintainer approved the exact fresh-only design.
- Blockers: none

## Objective And Context

- Vertical outcome: merge the already validated outbound mTLS agent-session,
  offer, and wait-only poll path only after clean retirement proves possession
  of the original protected agent journal and independently chosen poll IDs are
  isolated by authenticated principal.
- Earlier evidence: Phase 4 candidate `c373d04` passed `make validate-pr`, a
  2,554-test categorized summary, and CI. Required review found two reachable
  blockers after correction `3/3`: the retirement digest was forgeable by a
  credential holder without the old journal, and poll IDs were globally unique
  in SQLite even though protocol identity was principal-scoped.
- Later work explicitly out of scope: Phase 5 assignment delivery, artifact
  bytes, and remote launch; Phase 9 positive-containment replacement; general
  application-message signing, PKI automation, or compatibility tooling.

## Current Source And Harness

- Start from current `develop`. Selectively reuse only the production source,
  tests, and user-facing queue documentation from candidate `c373d04`; do not
  copy its phase/manifest metadata or stack on its branch.
- Candidate source is concentrated in
  `src/loom/queue/agent_sessions.py`,
  `src/loom/queue/agent_session_transport.py`, and
  `src/loom/queue/local_daemon.py`. Focused tests are
  `tests/unit/loom/queue/test_agent_sessions.py` and
  `tests/integration/queue/test_agent_session_transport.py`.
- Retain the proven agent-owned locked journal, shared direct/HTTP application
  service, mTLS peer extraction, current-policy authorization, coordinator-
  issued session replay, exact CPU/memory offers, held polls, Phase 3 root
  continuity, and causal no-launch sentinels.
- The blocked branch/worktree is evidence only. Its final source/test revision
  is `c373d04`; validation metadata `a991ced` and blocked metadata `e22500f`
  are not implementation inputs.

## Scope

In scope:

- During production registration preparation, generate one fresh 256-bit random
  retirement secret and persist it atomically with the durable registration
  intent before any network send. Exact lost-response replay uses the same
  secret and request. A later session always gets a different secret.
- Send only `SHA-256(secret)` as the registration verifier. Store that verifier
  with the coordinator session; keep the raw secret only in the protected
  agent journal until the retirement response is durably acknowledged.
- Bind the retirement request to the complete existing session and empty-
  reference evidence, reveal the one-session secret over mTLS, and compare its
  SHA-256 value with the stored verifier using a constant-time comparison
  before withdrawing an offer, fencing a poll, or mutating session state.
- Preserve exact retirement replay after response loss. Coordinator durable
  receipts, proof rows, audit, status, logs, and safe errors may retain a digest
  and non-secret evidence, but never the raw secret.
- Change coordinator poll identity to `(principal_id, poll_id)`. Every exact-
  poll read, completion, error cleanup, and ID-targeted fence includes both
  values. Session retirement may still fence all polls by session.
- Preserve every other validated Phase 4 contract and repair any localized port
  conflict against current `develop` without widening the phase.
- Produce the final Phase 4 schema directly. Valid Phase 3 version-1 role roots
  receive the final additive tables and keep all Phase 3 rows/identity. Fresh
  roots use the same final schema. A root claiming the unmerged candidate
  version but lacking the final verifier/secret/composite-key shape is rejected
  untouched.

Conceptually, the two fixed changes are:

```python
# Agent journal, in the same transaction as the registration intent.
secret = secrets.token_bytes(32)
registration = build_registration(
    retirement_verifier=hashlib.sha256(secret).hexdigest(),
)
persist_registration_intent(registration, retirement_secret=secret)

# Coordinator, before any retirement state change.
actual = hashlib.sha256(revealed_secret).hexdigest()
if not hmac.compare_digest(actual, session.retirement_verifier):
    raise InvalidRetirementProof()
```

```sql
CREATE TABLE agent_polls (
    principal_id TEXT NOT NULL,
    poll_id TEXT NOT NULL,
    -- existing session/revision/digest/result fields
    PRIMARY KEY (principal_id, poll_id)
);
```

Out of scope:

- A permanent root secret, a secret reused across sessions, public-key signing,
  a general MAC/signature envelope, at-rest key management, an external secret
  service, or a new runtime dependency.
- Supporting or migrating the unmerged Phase 4 candidate schema, dual reads or
  writes, compatibility adapters, warning periods, or recovery of a lost agent
  journal.
- Any assignment, reservation, artifact, provider, authority-lifecycle, worker,
  or launcher mutation from the agent-session operations.
- Redesigning mTLS identity, authorization scopes, offers, long-poll policy,
  session allocation, or Phase 9 containment.

Assumptions:

- The agent root and its file permissions are the current protection boundary
  for the raw secret. A principal with only the mTLS credential does not also
  possess that root.
- Standard-library `secrets`, `hashlib`, and constant-time comparison are
  sufficient; the coordinator is trusted to process but not durably retain the
  revealed one-time secret.

## Fixed Contracts And Private Discretion

- Observable behavior: missing, malformed, or wrong retirement secret is a
  definite safe rejection with no offer, poll, session, tombstone, or receipt
  mutation. Correct proof may then enter the existing fence-first `RETIRING`
  flow; unresolved coordinator references remain safely retiring and replayable.
- Durable/wire shape: registration carries one non-secret verifier; the agent
  journal owns the corresponding raw secret; the coordinator session owns only
  the verifier. Retirement carries the secret only in transit. Exact private
  column/table placement is discretionary if those ownership and atomicity
  rules hold.
- Replay: the secret/verifier participates in the canonical request identity.
  A lost registration or retirement response retries the same persisted bytes;
  changed content conflicts. The next session creates a new commitment.
- Poll identity: `(principal_id, poll_id)` is the durable operation identity.
  One principal cannot complete, fence, or clean up another principal's same-
  named poll.
- Compatibility: hard cut-over. Phase 3 version 1 is the supported immediate
  predecessor and upgrades additively to the final schema. The never-merged
  candidate schema has no consumer and is rejected without mutation.
- Cross-phase boundary: remote offers remain retained protocol facts and cannot
  enter scheduling/assignment until Phase 5. Phase 9 remains the only lost-root
  replacement owner.
- Private choices: helper names, secret encoding, exact local secret table or
  column, internal proof type split, SQL index names, and test fixture layout.

## Proportionality

- Reuse the complete validated Phase 4 path and its focused tests.
- Add only one per-session preimage commitment and one composite SQLite key,
  each answering a demonstrated reachable failure.
- Do not add a signing framework, key hierarchy, migration layer, generic poll
  abstraction, or future execution behavior.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only the original protected journal can prove cooperative retirement | Agent registration journal + coordinator session verifier | Credential holder constructs copied fields/arbitrary digest without old root | False clean retirement and unsafe replacement | Direct/HTTP missing, malformed, wrong, copied, and original-root cases with before/after DB snapshots |
| Registration replay preserves the same commitment | Agent registration intent | Lost response or restart between coordinator commit and local session persistence | Unretirable live session or changed replay | Persist-before-send and exact lost-response replay tests |
| Revealing one secret cannot weaken another session | Agent session journal | Reusing a root-wide secret after clean rollover | Later session can be retired with disclosed old material | Consecutive-session secret/verifier inequality and old-secret rejection |
| Coordinator never retains the raw secret | Coordinator codec/service/store projection | Request serialization, receipt/proof persistence, logging, status, audit, or error normalization | Journal possession secret leaks beyond its owner | Coordinator database and observable-output inspection on success/failure/replay |
| Same caller poll ID is independent across principals | Coordinator poll store | Two authorized principals choose the same ID | SQLite collision, 5xx, or cross-agent fencing | Concurrent/same-ID success and cross-principal completion/failure/fence isolation |
| Phase 4A cannot launch or transfer | Agent application view | Porting candidate accidentally exposes later owners | Premature remote side effect | Existing causal assignment/provider/artifact/launcher sentinels for every operation |

## Implementation Slices

1. Selectively port candidate source/tests/docs onto the fresh branch and prove
   the focused baseline without importing blocked workflow metadata.
2. Add journal-generated per-session secret/verifier registration, coordinator
   verification before retirement mutation, exact replay, and redacted durable
   proof/receipt handling.
3. Change poll storage and every ID-targeted query/update to composite principal
   identity; strengthen schema validation so the unmerged candidate shape fails
   closed.
4. Add the two negative/concurrency matrices, retain the full mTLS/restart/
   offer/no-launch regression set, and run the complete repository gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Import direction and dependency weight | Queue-private modules import without a new dependency; public imports remain intentional |
| Unit | required | Secret lifecycle, proof rejection, replay, schema, poll identity | Pre-send durability; same verifier on replay; new secret per session; wrong/missing secret causes zero mutation; composite PK and cross-principal SQL isolation; candidate-schema rejection |
| Contract | required | Direct and HTTP semantics, safe errors, no secret observability | Same definite/indeterminate result and idempotency behavior; secret absent from coordinator state/status/audit/errors |
| Integration | required | Real loopback mTLS, restart, rotation, lost responses, held polls | Original journal succeeds after coordinator restart/credential rotation; replacement/lost root fails; two principals share a poll ID; one principal cannot affect the other |
| E2E / opt-in | required loopback; optional two-machine | Complete no-launch connectivity gate | Register/reconcile/offer/wait/retire path passes while assignment, provider, artifact, authority, and launcher sentinels remain unchanged |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue/test_agent_sessions.py tests/integration/queue/test_agent_session_transport.py
    uv run pytest -q tests/unit/loom/queue/test_local_daemon.py tests/contracts/test_local_daemon_authority_contract.py tests/contracts/test_queue_python_api_contract.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: generating the secret after send; persisting it coordinator-side;
  checking it after fencing; reusing it across sessions; allowing a direct view
  to bypass the production journal; leaving one global poll cleanup query; or
  accidentally accepting the blocked candidate schema.
- Review focus: transaction order, exact replay bytes, constant-time verifier
  check before mutation, complete secret redaction, session-to-secret lifetime,
  every poll SQL predicate, final schema validation, Phase 3 continuity, and
  causal no-launch evidence.
- Stop if closure requires general application signing, a new dependency,
  migration/compatibility for the unmerged candidate, coordinator storage of a
  reusable raw secret, weakening current mTLS/authorization, or enabling any
  Phase 5 side effect.
- Accepted debt: loss of the protected agent journal blocks clean retirement
  until Phase 9 positive containment; filesystem permissions are not at-rest
  encryption; optional site credentials remain outside default CI.

## Executor Handoff

- Read this file from `Current Source And Harness` through `Risks, Review, And
  Stops`, plus manifest `Summary`, `Shared Constraints`, `Phase Index`, and
  `Quality Gate`.
- Own Phase 4A source, tests, queue feature documentation, and phase-plan
  completion state in the dedicated worktree. Preserve unrelated work and do
  not delegate.
- Do not revisit the approved per-session preimage, composite poll key, hard
  cut-over, current authorization, agent/coordinator ownership, or no-launch
  boundary.
- Return a qualified blocker if a stop condition occurs or the candidate cannot
  be selectively ported without changing a fixed contract.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `922237c`; dedicated
  branch/worktree, repository `samcantrill/loom`, target/title, read-only Phase 4
  evidence, source/test owners, validation gates, and stop conditions recorded
- Expanded planning: complete; maintainer approved the exact trust/durable-
  format design, one removal-first safety review passed, and one plan-quality
  review passed after correcting only an ambiguous lifecycle label from phase
  `approved` to phase `pending` with design approval explicit
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: required because this closes the demonstrated remote
  retirement trust boundary
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
