# Idle service efficiency

Implementation of the approved 2026-10-05 service-efficiency brief. All generic
behavior belongs to Loom; no project, training-progress or job-duration policy is
introduced. Worktree: `../loom-worktrees/idle-service-efficiency`, branch
`codex/idle-service-efficiency`, base `51f327c9`.

## Current rollout target

The user approved integration and qualification on `rphys-pure-current` on
2026-10-08. The original `rphys` services are stopped; the pre-upgrade fleet selected
rphys `636b1059c` and Loom `c79c8d93`. The latter restores ACTIVE provider
bindings before recovered worker launch. That exact fix is merged into combined
Loom `99648e02b7be8297bd7f3bd236fdf0b9fb16243d`, selected by consumer
rphys `9079ed70fae9070378ac9b1884787a88650976db`. Both branches are pushed.
The deployed scientific source and configurations are unchanged in this
consumer integration. Never deploy the older prepared
`693dcebda` image over the recovery fix. A separate managed qualification fleet
is running on both hosts and is outside this task's mutation scope.

The original image `67c71cea6655d1e4dce0b42825b051aeeb4681b502ae566004018ede34034071`
was built and verified on shared storage but not deployed by this task. The
combined image was built on shazza with the maintained guarded builder and its
digest verified both locally and after copying to shared storage:
`/nas/home/can134/scratch/loom-fleet/rphys/images/9079ed70f/reference-4ecd3c2012199f886fd8ce35602afd6ab9c007d7dd5b623107a6fcce32d45091.sif`.
It is read-only. The exact clean consumer and image passed upgrade preview;
normal coordinated operation `upgrade-c5ab0c3b08d840f6` completed on sleipnir
and shazza, including CPU, shared publication and enforced GPU qualification.
Before starting, the target fleet had no active/waiting admissions or running
assignments, and all four GPUs were free. No unrelated work was cancelled.
The active client is `clients/upgrade-c5ab0c3b08d840f6-shazza.yaml` under the
fleet's private root. A native guarded scheduling reload then applied the sole
configuration change, `poll_interval_seconds: 0.2` to `1.0`, under operation
`idle-efficiency-c5ab0c3b08d840f6-interval` (configuration revision 7). The protected
pre-change role file is retained in the fleet's qualification directory.

Integration coverage: GPU-provider and managed-local journal units, retry and
control-wait units, plus the complete concurrent outbound-agent integration
file. This covers restored claims under the same grant, uncertain restoration,
one launch, control responsiveness, lost replies, independent recovery and
mixed-resource concurrency. Reuse the previous unaffected owner-store and
coordinator evidence. Expand only on an integration failure or changed contract.
Consumer checks cover the pinned native/extension identity and fleet upgrade
boundaries. Physical CPU/latency samples and the completed four-way
CPU/GPU/cancellation qualification are recorded below. Local fixtures alone do
not discharge physical coverage.

Combined Loom validation passed all 119 selected cases, with zero failures,
errors or skips, in `build/idle-efficiency/combined-recovery.xml` (1193.66 seconds).
The selection covers `test_gpu_resource_provider.py`, `test_managed_local.py`,
`test_agent_control_waiting.py`, the two deployment recovery-retry cases, and
the complete `test_concurrent_outbound_agent.py`. Changed-file Ruff, selected
Pyright and diff checks passed. The consumer's locked targeted reference run
passed all 93 cases with no failures, errors or skips, plus all three selected
distribution builds, in `build/test-targeted/reference-povxidya/`. Its stable
tree fingerprint is
`7471dcad73a924b074daf5c54ed0fd4ccade90b0cfcf239119f1079af9a56bcd`.
Physical concurrency qualification passed against this exact consumer/image.

### Physical acceptance and closure

The targeted physical run passed all four selected cases, with zero failures,
errors, deselections or skips, in the consumer's
`build/test-targeted/acceptance-7up8m2a8/` (1611.85 seconds wall time). The
validation tree remained exactly the fingerprint above. JUnit properties verify
consumer `9079ed70f`, native Loom `99648e02`, the selected image/lock digests,
shazza session `session-5ceda5db-58a3-4e72-9f2d-4e709a51a3cb`, and four slots.

- Four CPU jobs overlapped; excess work waited and ran after acknowledged release.
- Four real CUDA jobs overlapped on four distinct claimed/observed GPU UUIDs;
  the excess job waited, then reused a released device.
- Three RTX 3090 jobs overlapped with CPU work. After the CPU slot released,
  a further compatible-GPU job still waited for GPU capacity, then succeeded.
- Cancelling one of four concurrent assignments produced the exact native
  containment proof, while its three peers succeeded with overlapping intervals.

At 2026-10-08T00:53:31Z the coordinator was healthy and scheduling-ready, with
zero active/waiting admissions and zero running assignments. All 38 test
assignments (including preparation) were RELEASED: 37 succeeded and the one
deliberately cancelled workload was CANCELLED. Shazza was ACTIVE/available with
four slots, an unexpired offer and all four GPU statuses available; an independent
`nvidia-smi` query showed no compute processes. No unrelated work was cancelled.
This qualifies the selected runtime/concurrency contracts, not a fresh full-data
scientific experiment or a full repository test suite.

### Active-fleet baseline

The fresh pre-upgrade idle window ended at 2026-10-07T23:18:21Z (2026-10-08
local time). The coordinator reported healthy with no active/waiting admissions
or running assignments before and after. Shazza was ACTIVE and available, with
all four GPU observations refreshed at 23:18:38Z. Explicit service PIDs and
start-tick identities were stable; child CPU is excluded. Other validation was
running on both hosts, so these are service CPU deltas under shared-host load,
not an uncontended-machine benchmark. This task's local validation had finished.

| Role | PID | 30-second CPU seconds | One-core CPU |
| --- | ---: | ---: | ---: |
| sleipnir coordinator | 1106591 | 5.18 | 17.27% |
| shazza agent | 2810465 | 6.94 | 23.13% |
| shazza supervisor | 2811068 | 0.02 | 0.07% |

These measurements apply to the active c79c8d93 recovery runtime and its explicit
0.2-second coordinator interval, not the older fleet measured below.

The first owned running probe, `idle-efficiency-before-20261007T231852`, used
legacy `clients/qualification.yaml`; its resident profile is no longer offered
by shazza. It remained in preparation and was explicitly cancelled through the
native API (confirmed `cancelled`), without starting an execution. Use
`clients/pure-binding-636b1059c-shazza.yaml` for this deployment, and the newly
returned client file after upgrade. No live profile was changed to accommodate
the probe.

The corrected probe `idle-efficiency-before-20261007T232359` requested one CPU
on shazza and remained RUNNING for the entire 30-second window ending at
23:25:21Z. Coordinator CPU was 13.61 seconds (45.37% of one core), agent 8.70
seconds (29.00%), and supervisor 1.41 seconds (4.70%). Submission returned in
0.589 seconds; RUNNING was observed after 41.657 seconds, including preparation
and container startup. Cancellation of only this probe returned in 0.127 seconds
and settled to CANCELLED with its assignment RELEASED after 9.190 seconds.
The protected JSONL receipt is under the consumer's ignored
`build/idle-efficiency/idle-efficiency-before-20261007T232359.jsonl`.

### Upgraded physical samples

The thirty-second idle sample ended at 2026-10-08T00:12:49Z. Coordinator PID
1851058 and agent PID 2180152 each used 0.56 CPU seconds (1.87% of one core);
supervisor PID 2180902 used 0.02 seconds (0.07%). Coordinator health, zero work,
agent availability and fresh GPU evidence were checked around the window.

The silent one-CPU probe `idle-efficiency-after-20261008T001302` was RUNNING on
shazza throughout the window ending at 00:16:28Z. Coordinator CPU was 3.84 seconds
(12.80%), agent 2.06 seconds (6.87%), supervisor 0.79 seconds (2.63%). Submission
reply took 0.494 seconds; RUNNING took 164.846 seconds. Cancellation reply took
0.115 seconds and settled to CANCELLED/RELEASED after 21.462 seconds. No other
operation was cancelled. These results show lower CPU, but do not establish
preserved launch/settlement latency: an independent image build was running on
shazza and the agent was observed in IO wait. The preparation worker itself
took two seconds in both samples; the added delay was outside that work.
The independent image build was allowed to exit normally, without signalling it.

The repeat probe `idle-efficiency-after-20261008T002353` reached RUNNING in
48.571 seconds; submission returned in 0.477 seconds. Its thirty-second running
window ended at 00:25:22Z: coordinator 3.94 CPU seconds (13.13%), agent 3.01
(10.03%), supervisor 1.17 (3.90%). Cancellation returned in 0.122 seconds and
settled to CANCELLED/RELEASED in 22.173 seconds. The worker's CANCELLED result
was timestamped about five seconds after cancellation was issued; the remaining
time includes collection, containment/publication and durable resource release.
The baseline worker cancellation was about two seconds after issue, with full
settlement in 9.190 seconds. These physical observations are not isolated-machine
benchmarks or precise attribution to one internal phase.

The idle reduction is substantial (coordinator 17.27% to 1.87%; agent 23.13% to
1.87%). Silent-running overhead also falls (45.37% to 13.13% and 29.00% to
10.03%). Operator request replies remain subsecond and repeat startup is near
the baseline, but full cancellation settlement is slower in both after samples.
Do not claim unchanged end-to-end cancellation latency. All three measured
probes have explicit terminal cancellation and released ownership; none was
relaunched or abandoned. Their protected JSONL receipts are retained under the
consumer's ignored `build/idle-efficiency/` directory.

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
  checkouts remain untouched. The combined recovery/efficiency runtime is deployed
  on `rphys-pure-current`; the exact image and native upgrade receipt are above.
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
  well. Local and downstream checks passed; physical after-change CPU/latency
  and all four selected concurrency cases passed as recorded above.
- Implementation, deployment and the selected physical qualification are complete.
  TLS pooling remains deliberately deferred for lack of measured need. Slower
  full cancellation settlement remains an explicit measured performance caveat;
  no ownership or assignment-isolation failure was observed.

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
GPU occupancy counters consequently remain zero. The separate physical evidence
above, not these synthetic counters, qualifies the deployed fleet.

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
roughly ninety short requests. TLS counts fell to five or six per window;
connection pooling was not justified by these counts. The later deduplication
and pacing evidence follows. CPU figures remain synthetic combined-process
observations, not fleet measurements.

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
service release (the committed-progress reset consumer). Transport indeterminate
replies and local-assignment observer retries are covered by the final selection
below.

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

## Delivery outcome

The accepted implementation and selected physical checks are complete. Branches
remain separate from develop; the deployed consumer is fixed at `9079ed70f`.
The useful remaining performance investigation is phase-level cancellation
settlement attribution (about 22 seconds after versus 9 seconds before), not
weaker cleanup proofs or a longer urgent-control wait. No additional deployment,
scientific rerun, connection pool or CPU/memory enforcement is implied by this
completion.

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

## Operational entrypoint

The consumer worktree is `../rphys-worktrees/loom-idle-service-efficiency`, branch
`chore/loom-idle-service-efficiency`. Fresh bootstrap and coordinator templates
select the one-second fallback; upgrades preserve explicitly authored settings.
The combined pin and current physical evidence are recorded at the top.

Retain the deployed operational launcher from
`../rphys-worktrees/fleet-upgrade-efficiency/tools/loom-fleet/rphys-fleet` on both
hosts, selecting the consumer checkout with coordinator `--source` on an upgrade.
Its agent lifecycle recognizes the current instrumented Python command as well
as the plain legacy command; the consumer checkout's plain launcher does not
recognize the current instrumented process. The operational wrapper and target
project source are separate inputs. Do not interpret that launcher mismatch as
an absent service or bypass native ownership checks.
