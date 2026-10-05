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
- Control waiting, store-validation deduplication, recovery backoff, conditional
  connection pooling decision, final affected-suite evidence and downstream
  qualification remain outstanding. No runtime or image pin has changed.
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

## Next implementation constraints

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
