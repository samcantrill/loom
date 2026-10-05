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

- Implementation and downstream consumption use dedicated worktrees; unrelated
  checkouts remain untouched. Normal unchanged-service fleet recovery is recorded
  below; no new image or runtime has been deployed.
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
  Exact transport replay and embedded-observer pacing are now implemented as
  well. Final affected-suite evidence is recorded below; downstream checks and
  physical after-change qualification remain outstanding. The downstream source
  pin is updated; the deployed runtime and image remain unchanged.
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

- Build and deploy the pinned consumer image, then collect physical after-change
  service CPU and control/submit latency evidence and concurrent CPU/GPU checks.
  Local synthetic tests do not discharge this gate. No new fleet software is
  deployed yet. Existing explicit coordinator timing must be changed deliberately
  through guarded configuration reload, not silently rewritten by upgrade.

## Transport and embedded-observer retry selection

Service transport failures now pace exact encoded requests independently; the
existing renewal, resource-offer and urgent-control retry cadence is unchanged.
Suspending during a delay prevents a later dispatch, without asserting that the
retained operation had no effect. Synchronous callers still receive the original
unknown-outcome error. Embedded failed observers retain the original assignment,
use independent deadlines, and reset on journal state/fence or run cancellation.
No executor slot is occupied by a pending observer delay. The coordinator wakes
at the earliest applicable deadline or its safety interval.

Focused evidence: 17 retry/external-error unit cases passed (95 explicitly
deselected non-retry cases in the initial selection), and six embedded production
cases passed: same-assignment replay, frozen-clock backoff with healthy peer and
prompt cancellation, active cancellation and daemon restart/worker rejoin.
Selected source/tests Pyright and changed-file Ruff passed. Final selections cover
the complete affected queue unit files, production daemon, concurrent outbound
service, control-wait capacity, transport, and retirement recovery. Lost-reply
observers recognize the negotiated control-wait operation rather than requiring
legacy empty polling. No physical qualification is inferred from these tests.

## Physical no-active-work sample

Read-only measurements on 2026-10-05 at 04:27:58 UTC sampled explicit owned PIDs
for 30 seconds with `tools/service_cpu_sample.py`. Coordinator status before and
after reported healthy, with zero active/waiting admissions and zero running
assignments. The unchanged deployment was `upgrade-26308d4f2ffc4b4c`, reference
revision `93f70b84e7c093efa7a7283f7edfbe61e3f5be6d`; its coordinator interval is
explicitly 0.2 seconds. These are process-window deltas, not lifetime `ps %CPU`.

| Host / role | PID | CPU seconds | One-core CPU |
| --- | ---: | ---: | ---: |
| sleipnir coordinator | 3072806 | 7.72 | 25.73% |
| shazza agent | 2167137 | 11.86 | 39.53% |
| shazza process supervisor | 2167725 | 0.07 | 0.23% |

Unrelated validation was running on sleipnir; child CPU is excluded. No service
was changed for these samples. A subsequent native agent observation showed
`available: false` and GPU observations stale since 03:28:56 UTC, preceding the
sample. Therefore these numbers do **not** establish a healthy-idle baseline;
coordinator health and zero admissions were insufficient to prove agent health.
The exact instrumented launcher reports the agent process ready. Read-only
agent inspection found all 47 assignments released, all 47 launches contained,
no unresolved references/mutation intents, and poll 2158 pending. Subsequent
normal guarded stop succeeded; starting the unchanged runtime created PID
2236545 but timed out after 300 seconds waiting for native readiness. The owner
was preserved; no database edits, forced signals or job cancellations were used.
The prior upgrade is complete. Physical after-change measurements and workload
latencies are still outstanding. Verified SSH to shazza works; `sudo -n true` on
sleipnir requires an interactive password, so an administrator image build may
need operator assistance. The downstream consumer worktree is
`../rphys-worktrees/loom-idle-service-efficiency`, branch
`chore/loom-idle-service-efficiency`, based on clean `790532a6b`. Fresh bootstrap
and both coordinator templates now select the one-second fallback, with native
template/bootstrap assertions and documentation that upgrades preserve explicit
existing settings. The dependency pin and downstream validation are complete.
Control checkouts and deployed sources remain unchanged.

## Final local validation

The completed retry tree passed 313 affected queue unit tests and 145 baseline
import/control/retry tests in the separate locked no-extra environment. The
full selected integration run executed 301 cases: 278 passed, 18 failed with
overlong Unix socket paths, four failed because their lost-reply injection still
intercepted only legacy control polling, and one retirement setup exceeded its
short fixture deadline. No runtime-source correction was needed. All five
production variants passed under a fresh short `--basetemp`
(`production-short-path.xml`). The complete retirement file, corrected
lost-reply cases and optional/sequence narrowing assertion changes passed all
29 cases in `final-corrections.xml`. Lost-reply assertions require injection to
occur before the grant is allowed, including the negotiated five-second wait.
All changed source/tests/tools pass Ruff and Pyright; `git diff --check` passes.
These are affected-suite results, not a full repository or deployed-fleet gate.
A final JUnit identity audit matched all 23 failed/errored cases from the
301-case run to passing cases in `production-short-path.xml` or
`final-corrections.xml`; none is unresolved or counted as passed through a skip.

Final synthetic checkpoint at commit `1d54b3ae` (same ten-second fixture windows,
no concurrent task validation): idle 3.96%, silent running job 28.54%, retained
history 3.14%, recoverable error 4.43% of one core. Corresponding DB opens were
163/1315/146/220; schema checks 80/2403/80/112; TLS connections 6/6/5/6; control
requests two per window; error retries seven. Running-job overhead remains
measurable; these results are not a claim of negligible supervision cost.

The validated Loom checkpoint is published on `codex/idle-service-efficiency`;
the downstream reference pin and matching extension lock now select its full
commit `1d54b3ae97c88f4c2acb9400676a95d5c3efcb2b`. Consumer checks select native
templates, fresh setup, detached operations, upgrades, and pinned native/extension
identity. Physical concurrent CPU/GPU/cancellation cases remain a separate gate.

The unchanged fleet recovered after a normal coordinator stop/start, without
editing retained records. Coordinator PID is now 1740750, agent PID 2236545,
supervisor PID 2167725. Agent availability and all four fresh GPU observations
were confirmed after epoch reconciliation. No new image or software was deployed
for recovery.

## Healthy physical baseline

Thirty-second healthy-idle samples ended at 2026-10-05T05:14:44Z, after confirming
current agent availability and all four fresh GPU observations. The coordinator
used 6.14 CPU seconds (20.47% of one core), agent 7.11 seconds (23.70%), and
supervisor 0.02 seconds (0.07%). The same PIDs and unchanged explicit 0.2-second
coordinator interval apply. These are service-only process deltas, not lifetime
CPU averages or child workload CPU.

The finite owned probe `idle-efficiency-before-20261005T0515` succeeded and its
assignment was released. Its running window ended before sampling; no running
CPU claim is made from that probe. A second automated owned probe,
`idle-efficiency-before-20261005T052319`, requested one CPU on shazza and slept
silently for up to 180 seconds. Samples ended at 05:24:48Z; the exact assignment
was RUNNING on shazza before and after the window. Coordinator CPU was 20.75
seconds (69.17%), agent 7.13 seconds (23.77%), supervisor 1.51 seconds (5.03%).
Submission reply took 0.577 seconds, and the assignment reached RUNNING after
48.699 seconds including shared preparation and container startup. Cancellation
of only that freshly created probe returned after 0.122 seconds and reached
CANCELLED with its assignment RELEASED after 5.564 seconds. No unrelated work
was cancelled. Protected request/result receipts and the automated measurement
script are retained in the downstream worktree's ignored `build/idle-efficiency/`.

The running-job coordinator overhead is substantial and is an important physical
after-change comparison; the synthetic fixture does not predict its exact value.

## Downstream validation and image handoff

The consumer is committed at `693dcebda183e044a468ab2cad5e411667e241d4`. Targeted
reference validation at tree fingerprint
`1df7fc59748e202654485c786c55e042996fc05b94d3767083a0009c21c2342d` executed all 93
selected cases. In `build/test-targeted/reference-p8igljpf/`, 89 passed and four
failed because the temporary test roots were on tmpfs, which the existing
persistent-local-storage guard correctly rejects. The same four cases passed
unchanged using a fresh short ext4 `/tmp/lrie.*` pytest base in
`build/test-targeted/reference-dovessmd/`; isolated environments remained on
task-owned tmpfs. No skips, errors, source corrections or relaxed assertions.
Both executions passed the three selected reference distribution builds.
Changed Python files pass Ruff lint/format checks; diff checks pass. This remains
targeted evidence, not full repository or physical SIF qualification.

No new image is built yet. Both hosts require an interactive sudo password;
sleipnir has only 8.5 GB free, versus 567 GB on shazza. A guarded operator build
launcher is prepared under the consumer's ignored
`build/idle-efficiency/build-image-on-shazza.sh`. It requires the clean exact
consumer commit and physical shazza host and writes only the fresh owned local
directory `/data/can134/loom/rphys/image-build.idle-efficiency.7IDBE7Eu`. The image
will be verified and placed on shared storage before the normal coordinated
upgrade; no deployed source or image is modified in place.

For that upgrade, retain the currently deployed operational launcher from
`../rphys-worktrees/fleet-upgrade-efficiency/tools/loom-fleet/rphys-fleet` on both
hosts, and select the new consumer checkout with coordinator `--source`.
Its agent lifecycle recognizes the current instrumented Python command as well
as the plain legacy command; the consumer checkout's plain launcher does not
recognize the current instrumented process. The operational wrapper and target
project source are separate inputs. Do not interpret that launcher mismatch as
an absent service or bypass native ownership checks.
