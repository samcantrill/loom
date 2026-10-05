# Idle service efficiency

Implementation of the approved 2026-10-05 service-efficiency brief. All generic
behavior belongs to Loom; no project, training-progress or job-duration policy is
introduced. Worktree: `../loom-worktrees/idle-service-efficiency`, branch
`codex/idle-service-efficiency`, base `51f327c9`.

## Scope and delivery checks

1. Reproducible quiet, running-without-output, retained-history and recoverable
   failure measurements. Process-local counters only; no durable metrics schema.
2. Coordinator generation-based wake-up, bounded safety reconciliation, passive
   operation/admission waits, immediate shutdown and bounded scheduling batches.
3. Authenticated bounded control waiting, durable-receipt suppression (never
   acknowledgement), compatibility negotiation, reserved client/server capacity,
   no locks held across waits, replay and notification-race coverage.
4. Deduplicate structural store validation inside verified operations, retaining
   live deletion/substitution, owner identity and fence checks.
5. Per-operation recoverable-error backoff, preserving exact replay and uncertain
   outcomes, independent resource renewals, GPU freshness and urgent control.
6. Measure again; connection pooling is conditional on remaining connection cost.
   If needed, exclusive checkout per request and independent channel capacity.
7. Accurate behavior docs and regression tests, actual before/after CPU and
   latency evidence, followed by downstream pinned-consumer qualification.

The initial safety fallback is one second. Explicit existing polling settings
remain configuration choices; no silent rewriting of a deployed role. Durable
schemas, ownership proofs and terminal-conflict semantics remain unchanged.

## Validation rationale

Extend `test_agent_waiting.py`, `test_local_daemon.py`, and
`test_concurrent_outbound_agent.py`: notification before/during wait, suppressed
notification fallback, exact lost-reply replay, passive revision waits, shutdown,
wait-capacity saturation, cancellation during held IO, renewal and multi-job
progress. Retain live owner-store loss/substitution checks. Cover new wire fields
at transport boundaries and config defaults in deployment tests. Use locked
Python 3.12 baseline and config-extra environments as appropriate. Expand to the
affected queue/transport suites and static checks once the full change is stable;
never treat synthetic tests as physical fleet qualification.

## Current state

- Dedicated clean worktree created; unrelated checkouts and fleet untouched.
- Baseline captured at `51f327c9` plus the diagnostic harness only, using
  `uv run --python 3.12 --isolated --locked --group dev python -m
  tools.service_benchmark --seconds 10 --coordinator-interval 0.2`.
- Coordinator/status waiting implemented: shared generation primitive, commit
  hints for passive status readers, one-second default safety interval, committed
  offer/assignment wake-ups, immediate continuation after a full scheduling batch.
- Baseline unit selection: 107 passed (`build/idle-efficiency/coordinator-waits.xml`).
  Selection: `test_service_signals.py`, `test_agent_waiting.py`,
  `test_local_daemon.py` under `tests/unit/loom/queue/`.
- Config-extra integration selection: 9 passed
  (`build/idle-efficiency/concurrent-service.xml`): held worker/short assignment
  ceiling, four exclusive devices with mixed CPU/excess GPU, and cancellation
  during held transfer/publication in `test_concurrent_outbound_agent.py`.
- Changed-file Ruff and selected-source/test/tool Pyright passed. Pyright used
  the isolated environment's interpreter; no environment was installed in a
  control checkout. `git diff --check` passed.
- Control waiting implemented with authenticated session-scoped receipts,
  namespace-qualified suppression IDs, read-only empty checks, capability
  fallback and separate bounded wait capacity. Receipt does not apply a drain
  or fence a locally unanswered work poll.
- Owner-store validation deduplicated within construction and each operation;
  live ownership and agent-journal structure checks remain mandatory.
- Admission and outbound retained-assignment recovery now have independent
  jittered pacing, scoped progress resets and redacted retry-deadline diagnostics.
  Remaining transport/local-observer retry audit, final affected-suite evidence
  and downstream qualification remain outstanding. No runtime or image pin has
  changed.
- No implementation or deployment completion is claimed yet.

## Baseline evidence

Each window lasted 10 seconds. Coordinator, agent and TLS handlers share one
process in the synthetic fixture; child CPU is excluded. Counters use in-memory
wrappers and SQLite tracing, so CPU figures include identical diagnostic costs
in the before/after harness. These are not deployed-fleet idle measurements.

| Scenario | CPU seconds | One-core CPU | DB opens | Schema table checks | Cycles | TLS connections | Control requests | Renewals | Recovery attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy idle | 3.525 | 35.25% | 911 | 720 | 45 | 92 | 88 | 2 | 0 |
| Running without output | 8.058 | 80.58% | 2513 | 7379 | 29 | 100 | 96 | 2 | 0 |
| Retained terminal history | 3.407 | 34.07% | 884 | 720 | 45 | 92 | 90 | 1 | 0 |
| Recoverable error | 3.549 | 35.49% | 1004 | 720 | 44 | 93 | 89 | 2 | 45 |

The harness starts and cleans only its own roles and jobs, using the existing
mutual-TLS and supervisor integration fixture. No physical GPUs are requested;
GPU occupancy counters consequently remain zero. Physical GPU/renewal latency
qualification remains a distinct outstanding gate.

## Coordinator/status checkpoint

Same command and ten-second windows, omitting `--coordinator-interval` to use the
new one-second default. Existing explicitly authored intervals are not changed.
No additional implementation changes occurred while either measurement ran.

| Scenario | CPU seconds | One-core CPU | DB opens | Schema table checks | Cycles | TLS connections | Control requests | Renewals | Recovery attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy idle | 2.501 | 25.01% | 463 | 160 | 10 | 95 | 91 | 2 | 0 |
| Running without output | 5.663 | 56.63% | 1632 | 2547 | 9 | 110 | 106 | 2 | 0 |
| Retained terminal history | 2.562 | 25.62% | 443 | 160 | 10 | 92 | 89 | 1 | 0 |
| Recoverable error | 2.854 | 28.54% | 476 | 160 | 9 | 93 | 89 | 2 | 10 |

The remaining control/TLS counts are expected: agent control waiting is the next
slice. Do not treat this checkpoint as completion of the approved brief.

## Control-wait checkpoint

- Unit selection: 121 passed (`build/idle-efficiency/control-waits.xml`):
  `test_agent_control_waiting.py`, `test_agent_waiting.py`,
  `test_agent_sessions.py` under `tests/unit/loom/queue/`.
- Integration selection: 13 passed in `control-service.xml`: late-poll drain
  (inline/shared), lost control replies across reconnect/close and legacy
  capability fallback, cancellation during held input/publication (six cases),
  and four exclusive devices with mixed CPU/excess GPU.
- The same run found two test defects: the new capacity test used a zero wait
  for the existing work-poll protocol (which requires at least one millisecond),
  and the 32-worker test's pool-budget assertion omitted the new wait lane.
  Both corrected, with 8 passing cases in `control-boundaries.xml`: the two
  affected tests plus protocol decoding, authenticated role rejection,
  client/operator views and query-role result/permission boundaries.
- The 32-worker test covers independent observation, ten offer renewals,
  assignment-scoped cancellation and eventual release of all assignments.
- Changed-file Ruff, selected Pyright and diff checks passed. Source/tests are
  validated in the locked Python 3.12 config-extra environment. This is targeted
  evidence, not full-suite or physical-fleet qualification.
- Disk-full failures in an earlier run were environmental; the selected runs
  above completed after space became available. The isolated validation runtime
  and pytest temporary files use task-owned tmpfs storage; production is unchanged.

Same ten-second instrumented fixture windows, with no concurrent task validation:

| Scenario | CPU seconds | One-core CPU | DB opens | Schema table checks | Cycles | TLS connections | Control requests | Renewals | Recovery attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy idle | 0.434 | 4.34% | 204 | 160 | 10 | 6 | 2 | 2 | 0 |
| Running without output | 2.747 | 27.47% | 1392 | 2547 | 9 | 6 | 2 | 2 | 0 |
| Retained terminal history | 0.387 | 3.87% | 189 | 160 | 10 | 5 | 2 | 1 | 0 |
| Recoverable error | 0.428 | 4.28% | 223 | 160 | 9 | 6 | 2 | 2 | 10 |

The empty-control hot loop is removed: two control waits per window, down from
roughly ninety short requests. TLS counts are now five or six per window;
connection pooling is not yet justified by these counts. Remaining running-job
database/schema work and recoverable-error pacing are the next slices. CPU
figures remain synthetic combined-process observations, not fleet measurements.

## Control-wait implementation constraints

Control receipts must not fence/discard a locally unanswered work poll. Reuse
the durable control journals, separating receipt from effect preparation where
necessary. A received-ID suppression hint must never acknowledge or release
work. Preserve assignment-local cancellation while a bulk transfer is held.
Check the existing 64 KiB protocol envelope and 1..1024 assignment ceiling when
bounding suppression requests; do not silently reduce supported concurrency.
Long control waits need independent executor and server admission capacity.
Existing work-poll subscription/shutdown/authorization behavior is reusable.
Do not let assignment monitoring continue issuing redundant remote control
checks after the dedicated receipt path becomes authoritative.

## Owner-store validation selection

Consolidate construction and `open_owner_stores()` on the existing required-owner
validation helper. Keep the agent-journal schema check separately: the helper
checks its owner binding but does not validate its entire journal structure.
No cross-operation cache, connection reuse or durable schema change is introduced.
Cover one structural open per operation and repeated validation on the next
operation, alongside the complete `test_local_daemon.py` owner-loss/substitution,
startup/shutdown, scheduling and recovery assertions. Repeat the selected mixed
CPU/GPU service case as the coordinator-only consumer. Expand if another owner
or store contract changes; current control-protocol evidence remains reusable.

Result: 66 passed in `build/idle-efficiency/owner-store-validation.xml`, with
changed-file Ruff, selected Pyright and diff checks passing. These checks cover
the exact deduplication tree after the control-wait checkpoint. No schema cache
or skipped ownership validation is used.

## Recovery pacing selection

Share process-local pacing between the existing retained-assignment recovery
loop and coordinator admission failures. Retain the five-second retry ceiling,
add bounded jitter and a reported next deadline, preserve per-assignment fences
and exact requests, and reset coordinator delays only for that run's owner
progress/revision or changed scheduling epoch. Conflicts retain their existing
terminal behavior. No resource-renewal, GPU freshness or control timing changes.
Select deployment retry unit cases, coordinator/status units, real independent
admission recovery and outbound recovery-with-peer-work cases, and mixed-device
service release (the committed-progress reset consumer). Remaining transport
indeterminate-reply and local-assignment observer retry loops still need audit.

Result: 88 passed in `build/idle-efficiency/recovery-pacing.xml` (retry units,
status/coordinator units, scoped admission pacing, independent healthy admission,
outbound peer progress and mixed-device release). An additional 84 passed in
`recovery-boundaries.xml` cover session operations, embedded input replay,
qualification rejection and mixed-device release after tightening start-replay
notifications. Selected Pyright, changed-file Ruff and diff checks pass. Two
existing embedded-worker tests now explicitly assert their configured non-null
agent root/journal before using them, resolving their optional-type diagnostics.

Latest ten-second fixture windows after deduplication and recovery pacing:

| Scenario | CPU seconds | One-core CPU | DB opens | Schema table checks | Cycles | TLS connections | Control requests | Renewals | Recovery attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Healthy idle | 0.371 | 3.71% | 164 | 80 | 10 | 6 | 2 | 2 | 0 |
| Running without output | 2.824 | 28.24% | 1319 | 2403 | 9 | 6 | 2 | 2 | 0 |
| Retained terminal history | 0.302 | 3.02% | 143 | 80 | 10 | 4 | 1 | 1 | 0 |
| Recoverable error | 0.460 | 4.60% | 219 | 112 | 13 | 6 | 2 | 2 | 7 |

Deduplication halves quiet schema checks. The early exponential retry ramp can
add cheap coordinator cycles before reaching its five-second ceiling, while
reducing failed admission attempts. These short CPU windows are noisy (the
running-job figure did not improve over the preceding checkpoint); counters
establish the removed work, not a guarantee of monotonic CPU improvements.
With only four to six TLS connections per ten seconds, defer connection pooling:
there is no measured justification for adding connection ownership machinery.

## Remaining delivery work

- Audit and pace indeterminate transport retries and embedded assignment observer
  retries without delaying renewals/urgent controls or changing exact replay.
- Extend regression coverage for any changes from that audit and collect final
  affected-suite evidence against the completed tree.
- Collect physical before/after service CPU and control/submit latency evidence;
  publish a downstream Loom pin and qualify rphys against that release. Local
  synthetic tests do not discharge this gate. No fleet has been changed here.
