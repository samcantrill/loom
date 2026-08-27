# Phase 9F Execution Plan: Session Replacement And Recovery Operations

## Metadata

- Status: merged
- Stage/phase: Stage 29, Phase 9F
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9f-session-replacement-recovery-operations`
- Worktree: `/home/can134/work/active/loom-worktrees/stage-29-p9f-session-replacement-recovery-operations`
- Base: `241286265f066548374ce44df23ccf4ed4700a7f`
- PR: [#249](https://github.com/samcantrill/loom/pull/249), squash-merged
  to `develop` as `a6cd482`; title
  `feat(scheduling): close recovery operations and replacement`
- Dependencies: merged Phase 9C2 `b0ed116`, 9D2 `82b311f`, and Phase 9E
  `0dab7a9`; blocked Phase 9 is read-only replacement-contract evidence.
- Workflow: expanded because replacement joins coordinator, agent journal,
  provider/supervisor, authority/recovery, and transport owners. One omitted
  reference can expose capacity beside old live work.
- Blocker corrections: 2/3

## Objective And Scope

Replace a lost agent session only after its complete retained reference set is
safe. The successor is a new identity with zero capacity until fresh protected
configuration/provider observation and an old-reference recheck complete.
Finish the authorized operation, bounded joined status, operational guidance,
fresh-process proof, and Stage 29 validation evidence.

Cover assignments, provider preparations/claims, deliveries, controls,
transfers, results/outputs, events/outbox, recovery, supervisor evidence, and
release. Reject delayed old mutations; exact cleanup may advance only its old
claim. Expose the same operation through public Python/direct, Unix socket,
authenticated HTTP, and CLI.

This remains the approved hard cut: no compatibility reader, migration, legacy
import/adoption, automatic replacement/recovery, HA, inferred containment,
checkpointing, repair tooling, route fallback, or moved authority/provider/
authorization ownership. Missing or incompatible protected state fails closed.

## Current Source And Harness

- `src/loom/queue/agent_sessions.py` owns sessions and coordinator protocol
  state; both coordinator and agent reference indexes currently record only
  deliveries, so clean retirement is not a complete replacement proof.
- `src/loom/queue/agent_session_transport.py` owns remote journal, supervisor,
  HTTP, replay, and retirement seams. `src/loom/queue/local_daemon.py` and
  `src/loom/queue/local_daemon_execution.py` own recovery, cross-owner
  execution, release, and status. `src/loom/queue/local_daemon_transport.py`,
  `src/loom/queue/__init__.py`, and `src/loom/cli/queue.py` own socket/public/CLI
  adaptation; adapters own no policy.
- Use the targeted tests below. Keep `loom.scheduling` import-light and all
  session/recovery behavior in queue application infrastructure.

## Fixed Contracts And Private Discretion

The public request contains only unique replacement operation ID, stable
`agent_id`, and bounded reason. Authorization derives the sole current old
session; callers provide neither session ID nor containment. Exact replay
returns the durable result and changed reuse conflicts. Ordinary registration
may consume one open decision only when protected policy still maps its
credential to the same agent; the coordinator mints a different session. It
inherits no claim, request, revision, transfer, token, process, launch, event,
or outbox state. Absence, operator prose, credentials, and an empty root never
qualify as evidence.

Decision and readiness are distinct:

1. A decision requires `complete = True` and every reference either terminal
   plus physically released, or covered by exact target-owned Phase 9E
   containment followed by the accepted authority close. Containment may
   authorize only a fenced zero-capacity successor.
2. Readiness additionally requires exact old release or a fresh successor-owned
   full provider observation reflecting/withholding every retained old claim,
   then a complete post-fence reference recheck. Only one fresh availability
   revision may then publish and enable polling.

An unavailable old journal/supervisor is an explicit unavailable owner, never
an empty set. It is coverable only per assignment already present in the
complete coordinator inventory, using exact containment/close and successor
observation. One assignment's evidence cannot cover another assignment, an
unscoped control, or an incomplete coordinator inventory. Ordinary verified
terminal truth always prevails over recovery choice.

Use one coordinator-owned durable replacement/readiness record, binding the
request digest, agent and derived old/new identities, fence result, projection
digest/revision tokens, and readiness result. Owner rows remain authoritative;
do not copy payloads into a generic ledger. Row layout, helpers, query
composition, intermediate states, and safe diagnostic wording are private.
Advance fresh schema/protocol identities without migration. Status exposes only
bounded owner/class counts, decision/release/readiness state, and withholding
reason—never secrets, credentials, tokens, private paths, or payloads.

### Complete owner inventory

Every applicable class must yield deterministic bounded items or name why
`complete = False`. Children join through their authoritative assignment;
absence is not progress.

| Class | Enumeration owner | Safe fact |
| --- | --- | --- |
| Session/protocol | Coordinator session, tombstone, offers, polls, deliveries, reference index | Fence invalidates offer/poll and forbids new delivery; delivery resolves only with exact assignment release |
| Reservation/claim | Execution-store assignments for old `session_id`, with atoms, offer/decision, events | Coordinator `released` plus agent/provider release is clean; `terminal`/`logical_released` still holds capacity; contained-and-closed is decision-only |
| Remote execution/data | Coordinator remote assignment, transfers/authorizations, report/output, assignment controls | Remote `RELEASED` and resolved delivery is clean; pending bytes/auth never imply release |
| Controls | Coordinator and available agent ordinary/assignment controls | Applied/failed and acknowledged is terminal; pending unscoped control is fenced and retained as superseded audit state |
| Agent/provider/process | Available execution journal assignment, claims, process/fence/launch, result, events/outbox; provider/supervisor facts | `RELEASED`, or `DECLINED` without prepared claim, is clean; containment must match immutable identities and closed recovery receipt |
| Authority/recovery | Authority snapshot and recovery row joined by run/stage/attempt/assignment/fence/process | Exact ordinary terminal/release, or closed Phase 9E receipt with qualifying evidence; pending/unknown/failed recovery does not qualify |
| Readiness | Coordinator/agent release plus successor full provider observations | Every old claim released or reflected/withheld; every configured provider and current configuration observed |

Unknown kind, malformed/conflicting identity, missing parent, revision
regression, unavailable completeness-critical coordinator store, or an old
owner not bounded by the complete coordinator assignment inventory makes the
projection incomplete and causes no decision.

### Fence and recheck

1. Derive the old session and snapshot the complete classified inventory with
   owner revision/digest tokens; reconcile verified current-fence terminal facts
   through ordinary paths.
2. Under the mutation exclusion used by assignment/delivery/control creation,
   recheck session-facing revisions and the complete assignment-ID set. On an
   exact eligible match, atomically persist decision/result, fence/tombstone the
   old session, and invalidate offers/polls. Every later old-session writer must
   reject before mutation except exact old-ID cleanup.
3. Ordinary same-agent registration binds the new session with readiness false,
   zero capacity, and offers/polls disabled.
4. After full fresh configuration/provider observation, re-enumerate old
   references. Accept only monotonic terminal/release/audit additions; fail
   closed on a new assignment, conflicting identity, unavailable owner, or
   regression. Durably bind observation and post-fence digest before exactly
   one fresh availability publication. Crashes replay or remain at zero.

Do not hold SQLite transactions across authority, supervisor, or provider calls.

## Implementation And Validation

Implement in this order: complete projection/classifier; durable decision,
fence, successor and readiness gate; stale-writer/cleanup enforcement; joined
status; one authorized operation through all adapters; guidance and evidence.
Reuse session service, authorizer, Phase 9E receipts, authority CAS, provider
release/observation, joined status, and dispatch seams. Add no second recovery
machine, adapter policy, or generic CRUD surface.

| Test seam | Causal proof |
| --- | --- |
| Unit: `tests/unit/loom/queue/test_agent_sessions.py`, `tests/unit/loom/queue/test_local_daemon.py` | One item per owner class; incomplete/malformed/weak evidence rejects before mutation; exact/conflicting replay; authorization, redaction, zero readiness |
| Integration: `tests/integration/queue/test_agent_session_transport.py`, `tests/integration/queue/test_local_daemon_production.py` | Multi-assignment/provider/control/data/outbox inventory; lost owner; new reference before decision recheck; revision change before readiness; crash around decision/bind/observation/publication; successor inherits nothing; stale old writes cannot mutate it |
| Integration: `tests/integration/queue/test_slurm_ready_stage.py`, `tests/integration/queue/test_cli_operations.py` | Replacement does not absorb SLURM ownership or release its held slot; direct/socket/HTTP/CLI parity and least privilege |
| E2E: `tests/e2e/test_queue_cli.py` | Fresh managed/SLURM processes, one launch/submit, terminal-versus-contained close, lost old root, different successor, no early offer/poll |

Targeted commands are the named unit files, named integration files, then the
named E2E file with `pytest -q`. Final gates: `make validate-pr` and
`make test-summary`.

## Risks, Review, And Stops

Review must trace every inventory writer to the durable fence and every
offer/poll entry to readiness. Stop if a listed owner lacks a bounded query, an
old-session assignment/reference writer bypasses the fence, a provider cannot
produce a full fresh observation, eligibility needs inference from absence, the
coordinator inventory is incomplete, a causal post-fence recheck is impossible,
or safety needs a new product/public/trust decision. Runtime loss of the old
journal alone is not a stop when the complete coordinator assignment inventory
scopes exact containment and successor observation. Capacity remains withheld
while evidence is unknown.

## Executor Handoff

Read this plan, Phase 9C2/9D2/9E completion records, and only blocked Phase 9's
`Session replacement` contract. Preserve owner boundaries and Phase 9E
arbitration. Do not reopen compatibility, caller-selected identity, weak
containment, automatic replacement, or recovery outcome policy. Stop under the
conditions above; do not solve incompleteness with a ledger or second machine.

## Workflow State

- Manager preparation and expanded refinement: complete at base `2412862`
- Implementation: complete at `efdeabf`; the bounded manager-local correction
  closed the executor's complete-inventory blocker after the optional refiner
  became unavailable. Independent review then found two reachable late-cleanup
  blockers and one status inconsistency. Bounded correction 2/3 at `eb0537d`
  now requires old-root/provider release proof before restoring capacity,
  derives fresh coordinator offer identities when withholding changes, and
  updates current owner counts in the same cleanup transaction.
- Pre-submit gate: passed again on corrected source. `make validate-pr` passed
  Ruff, Pyright, 2,578
  default tests, 142 config-extra tests with 3 expected skips, and both package
  builds. `make test-summary` passed 2,720 tests with no failures or errors.
- Independent review: complete. Its provider-release, immutable-offer-replay,
  and stale-status findings are closed by correction 2/3 and the causal
  transport regression.
- Refiner: no further pass planned; corrections 2/3
- PR: [#249](https://github.com/samcantrill/loom/pull/249) merged into
  `develop`; corrected scope, body, target, title, non-draft state, and clean
  mergeability passed final manager review before merge.
- Merge: complete as `a6cd482` at 2026-08-27T04:36:30Z

## Completion Record

| Item | Result |
| --- | --- |
| Implementation/tests/validation | Corrected source complete at `eb0537d`. The full 179-test phase matrix passed: 102 unit/CLI/package/E2E, 46 production/SLURM integration, and 31 agent-transport integration tests. Fresh full gates passed as recorded above. |
| Validation-relevant later changes | None. This concise workflow metadata update does not change source, tests, dependencies, build inputs, or validation configuration. |
| PR/review/merge/cleanup | Independent review findings are closed; final manager review approved PR [#249](https://github.com/samcantrill/loom/pull/249), squash-merged as `a6cd482`. Merged metadata is being recorded on `develop`; dedicated worktree and branch cleanup follows this commit. |
