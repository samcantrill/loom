# Phase 2 Execution Plan: Direct Container Resource Mapping

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 38, Phase 2
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p2-direct-container-resources`
- Worktree: `stage-38-p2-direct-container-resources` under the recorded root
- Base revision: `43b911fb0cfe9d9c5192623726607a1575a41da5`
- PR target: develop
- PR: [#278](https://github.com/samcantrill/loom/pull/278)
- PR title: `feat(execution): map direct container CPU and memory requests`
- Dependencies: Phase 1 PR #277 merged at `133505b`; audit dispositions accepted
- Workflow path: expanded correctness review for external-runtime mapping
- Blockers: none for Phase 2; PR #278 merged at `0c0dbf2`; cleanup complete

## Objective And Context

Implement amended FR-2 while preserving FR-4. Direct CPU/memory mapping and A-9
are already implemented. The maintainer now approves explicit scheduling-only
CPU/RAM execution on a host where settings cannot change, while preserving the
existing runtime-limit default and full resource intent. The new policy is
implemented at `8702e06`, with both full gates and the selected-policy SIF smoke
passing. The remaining mixed-stage warning correction is implemented at `04443ed`
and independently accepted with fresh full gates passed. Timeouts and process-ownership
redesign are Phase 3 work.

## Current Source And Harness

Owners: `pipeline/executors/apptainer/commands.py`, executor resource projection,
`pipeline/runtime/capabilities.py`, and `diagnostics/preflight.py`; the A-9 fix
belongs only to `pipeline/executors/slurm/rendering.py`. Read `resources.py`
and `executors/containers.py` to reuse public semantic validation and existing
intent. Relevant tests are direct Apptainer command/executor units and
integration, capability contracts, preflight units, executable SLURM scripts,
SLURM container composition, and `tests/container_acceptance`.

Two existing boundaries need explicit attention: public `ContainerResourceIntent`
can be constructed without `ResourceRequest` semantic validation, and
`slurm/container.py:wrap_slurm_command_with_apptainer` calls the same command
builder while preserving container resource intent. Include that existing
wrapper in scope only as necessary to retain scheduler-owned limits. Do not
infer the execution route from an authored capability record. Preflight now uses
the command builder for exact conversion, but does not pass resolved execution
options to that probe. It must use the selected policy as well as effective intent.

Amendment evidence is the clean active tree at `ecbb497`, with published develop
still `43b911f`. Existing GPU option projection uses `dataclasses.replace`;
effective runtime resources override authored container intent only when nonempty.
The failure helper currently infers emitted limits from resource entries alone,
which must change when requests can survive without flags. Use Python 3.12 and this worktree's locked environment
(`uv sync --locked --all-groups`), never the dirty checkout's environment.

## Scope

In scope: deterministic CPU/memory argv conversion, actionable unsupported
mapping/runtime failures, explicit scheduling-only policy in the existing adapter,
truthful capability/preflight/provenance, separate real-runtime acceptance hooks
over existing test infrastructure, and the bounded A-9 correction. Relevant
runtime profile composition and managed-placement tests are in scope for retained
intent; production queue changes are not part of the resource-policy amendment.
The previously approved A-13 pre-grant retry correction covers the reproduced control-response
retry omission in `queue/agent_session_transport.py`, focused transport tests,
and its existing queue contract documentation. Reuse the established bounded
assignment retry owner; preserve control replay, rejection, and exhausted-retry
retention. No global transport recovery or ownership redesign is included.
The separately approved coordinator amendment changes only the reader-driven
wakeups in `queue/local_daemon.py:LocalDaemon._wait` and `wait_admission`, plus
focused queue tests and documentation. Preserve all lock/transaction owners,
periodic reconciliation, mutation wakeups, deadlines, and release behavior.
Out of scope: changing resource semantic validators, GPU allocation, fractional
CPU scheduling, new registries/config namespaces, timeouts, container builds or
downloads without explicit authority, and host system administration.

## Fixed Contracts And Private Discretion

- Canonical CPU is a positive integer, unit absent or count, without attributes.
  Do not map zero to unlimited or accept fractional CPUs by broadening Loom.
- Canonical memory is positive with B/KiB/MiB/GiB/TiB. In runtime mode, convert
  exactly to positive integer bytes; reject fractional bytes or values
  unrepresentable by the selected runtime. No silent rounding, overflow, or
  attribute reinterpretation. Scheduling-only mode still validates canonical
  semantics but does not impose an unused runtime parser's representability.
- Runtime mode: two CPUs and 512 MiB produce `--cpus 2 --memory 536870912` before the image.
  No-request command behavior remains compatible. Reuse public validators at
  the public mapping boundary; conversion owns runtime representability only.
  Validate the CPU/memory entries owned by this mapping, not unrelated resource
  kinds through a second validator. Existing GPU helper semantics, including
  its supported zero-request public input path, must remain unchanged.
- Report mapping support separately from host-dependent enforcement. Existing
  `SUPPORTED`/`BEST_EFFORT` vocabulary can describe flags plus cgroup caveats;
  do not report observed host enforcement without actual evidence.
- Unsupported runtime options must lead to an actionable failure; never retry
  without requested limits or silently degrade into advisory execution.
  Missing-worker-result errors retain redacted process metadata. Their existing
  resource-specific remedy must apply only to a launch that requested limits,
  without claiming every startup failure was caused by resource limits.
- Preserve upstream GPU passthrough, count validation, redacted metadata, and
  explicit `nv=True`. SLURM remains the CPU/memory enforcement owner on its
  scheduler route; direct flags must not accidentally change that composition.
- A-9: reject an invalid complete allocation value before line-oriented Bash
  parsing; retain accepted opaque token grammar and protected output behavior.
- Private flag/conversion helpers and fixture layout are executor discretion;
  no new shared abstraction is required for one direct adapter family.

### Approved Policy Amendment

- Public option: `ApptainerExecOptions.cpu_memory_enforcement`, serialized as
  `cpu_memory_enforcement` in the existing `adapter_options.apptainer` or
  `adapter_options.singularity` namespace. Accept only `runtime` (default) and
  `scheduling_only`; reject unknown/non-string values. Preserve current namespace
  alias precedence, runtime-profile merge, and exact-stage overrides.
- `runtime` keeps current flag mapping, rejection, and host-dependent enforcement
  reporting. It never means observed enforcement merely because flags exist.
  No implicit runtime retry with limits removed is permitted.
- `scheduling_only` omits only direct CPU/RAM limit flags. Do not clear, mutate,
  or reduce effective resource entries, change placement/reservations or release,
  or imply that direct unmanaged execution acquires a reservation. GPU projection,
  visibility validation/redaction, and actual SLURM-owned CPU/RAM remain unchanged.
- Configuration-aware capability/preflight output and existing executor command/
  process provenance must identify the effective mode and `not_enforced` CPU/RAM,
  with a visible warning. Static descriptors describe available capabilities,
  not selected-policy enforcement. Reuse existing capability/diagnostic vocabulary
  and merge owners; do not add a registry or heavyweight runtime import.
- Preflight must use the same policy, intent precedence, validation, and command
  projection as execution. Validate canonical CPU/memory at the public boundary
  even when flags are disabled. Persist retained intent alongside policy evidence.
- Missing-result errors should give resource-limit remedies only when the launch
  actually requested limits. Scheduling-only launch failures preserve original
  diagnostics/context without falsely blaming cgroup setup.
- Document a generic composable runtime profile and launch examples. Site-local
  image settings remain external; do not commit host identities, private paths,
  credentials, datasets, CUDA allocation tokens, or `.env` modifications.
- Split live receipts: scheduling-only requires a bounded production-command
  smoke with nonempty CPU/memory intent and the approved SIF; runtime-limit proof
  remains a separate fail-closed test, deferred to a compatible approved host.
  A scheduling-only pass does not assert unlimited inherited cgroups, prove
  enforcement, or constitute a full scientific experiment smoke.

### Approved Coordinator-Responsiveness Amendment

Measured evidence in planning.md, Approved Coordinator-Responsiveness Amendment,
shows reader-driven wakeups causing repeated reconciliation lock reacquisition:
a 15.575-second waiter overlaps 271 short cycles, rather than one long database
operation. Suppressing only the two admission wait APIs' wakes reduced the largest
observed wait to 0.112 seconds over three loopback cases. Both baseline and variant
passed overall; these timings identify the mechanism, not universal latency bounds.

Remove only `_wake.set()` from `_wait` and `wait_admission`. Keep observation,
revision/terminal/timeout results and polling cadence unchanged. `wait_operation`
is already passive. Do not change `_serve`, `_cycle_lock`, session/offer reload
guards, SQLite authority, mutation wakeups, retry/release owners, or durable data.
Add no locks, condition variables, queues, backoff, deadlines, or public options.
This is one additional expressly approved bounded amendment; the three historical
corrections remain consumed. Independent startup review precedes implementation.

## Proportionality

Extend current container intent and capability owners. One adapter policy field
is necessary because removing resource declarations also removes scheduler demand.
Add no parallel resource configuration or automatic fallback. The SLURM correction is justified by a reproduced supported
environment-boundary defect and belongs in the existing executable grammar
test, not a replacement scheduling mechanism.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| Canonical request validity | Resource validators | Public intent or config could bypass valid units/amounts | Reuse validation; mapped and rejected examples |
| Exact runtime units | Direct argv conversion | Fractional bytes/overflow silently change limits | Exact byte checks and representative units |
| Honest support/failure | Capabilities, preflight, runtime CLI | Flags exist but host cannot enforce | Consistent diagnostic caveats; runtime rejection and real acceptance |
| Explicit policy without lost demand | Existing adapter parser/merge, command builder, diagnostic/metadata owners | Scheduling-only host has valid requests but cannot apply rootless cgroups | Composed policy/overrides, retained requests and reservation behavior, absent flags and `not_enforced` evidence |
| Whole allocation grammar | SLURM script boundary | Newline suffix bypasses first-line parsing | Actual Bash and Python agree; raw values not printed |
| Passive observation and live service progress | Local daemon wait APIs and existing service loop | Status polling repeatedly wakes reconciliation and delays serialized agent control | Deterministic nonterminal-poll regressions for both APIs, unchanged result outcomes, periodic/mutation progress, real loopback retry and cancellation |

## Implementation Slices

1. Independently review the measured passive-wait correction and combined startup
   packet; preserve historical correction counts and the new bounded authority.
2. Remove the two observer wakeups, add deterministic and live progress coverage,
   and complete retained pre-grant retry rejection/exhaustion coverage. Then add
   the adapter policy and conditional mapping;
   preserve canonical validation, resource intent, default flags, and GPU behavior.
3. Align selected-policy capabilities, preflight, provenance, and failure remedies.
4. Add composed-profile/override and retained managed-demand regressions, preserving
   GPU and SLURM coverage and the already reviewed A-9 correction.
5. Add/run scheduling-only live acceptance over the approved image; preserve the
   separate runtime-limit check and its outstanding positive-proof limitation.
6. Update generic docs/example, run focused and full gates, and obtain independent
   correctness review before any Phase 2 PR or merge.

## Test And Validation Plan

Required: direct command/executor units and integration, capability contract,
preflight tests, executable GPU grammar and SLURM-container composition. Cover
positive CPU, binary units, exact fractional-unit-to-byte conversion, invalid/
unrepresentable requests, no request, argv ordering, and preserved GPU redaction.
Both live checks use production-generated commands. The scheduling-only check
requires nonempty CPU/memory intent retained in metadata, absent limit flags,
explicit no-enforcement evidence, and a successful bounded shell payload. It must
not require a user D-Bus session or assert unlimited inherited controls. The
runtime-limit check still inspects actual payload limits and fails on missing
prerequisites; CLI version/help and the other mode's pass are not enforcement proof.

Current host evidence: SingularityCE `3.10.4-focal`, cgroups v2, and no user
D-Bus session. The maintainer supplied and approved the local shell SIF (checksum
in planning.md) and ordinary execution passes. The actual runtime-limit hook
fails during rootless cgroup setup; report
`build/container-resource-acceptance-local-sif.xml`. The maintainer cannot change
host settings and approved scheduling-only execution with separate acceptance.
The [runtime requirements](https://docs.sylabs.io/guides/3.10/user-guide/cgroups.html)
remain relevant to deferred positive hard-limit proof on another approved host.
Do not build/download an image, administer the host, or treat this failure as a pass.

Required amendment coverage: option parsing/default/round trip and invalid policy;
composed runtime profile plus exact-stage override; both executor names and alias
precedence; unchanged effective intent including authored fallback; policy-aware
capability/preflight/provenance and missing-result remedies; retained managed
resource demand/reservation semantics; GPU projection and SLURM-owned composition.
Use existing fixtures and targeted interactions, not a full Cartesian matrix.

Coordinator coverage must exercise a nonterminal poll in each affected API and
prove observation does not set the reconciliation event while preserving changed,
terminal and timeout outcomes. Exercise periodic service progress without readers
and mutation-triggered wakeups. Avoid fragile wall-clock performance thresholds
or deadline extensions. Retain real loopback lost-response success and
cancel-before-grant outcomes; add proportionate final rejection/exhausted retry
retention coverage using existing owners. Run adjacent session replacement and
daemon production tests. Suggested queue lane:

    .venv/bin/python -m pytest -q \
      tests/unit/loom/queue/test_local_daemon.py \
      tests/unit/loom/queue/test_agent_sessions.py \
      tests/integration/queue/test_agent_session_transport.py \
      tests/integration/queue/test_local_daemon_production.py

Targeted commands (expand only for a changed public seam):

    .venv/bin/python -m pytest -q \
      tests/unit/loom/pipeline/executors/apptainer \
      tests/unit/loom/pipeline/executors/slurm/test_slurm_container.py \
      tests/unit/loom/pipeline/executors/slurm/test_slurm_scripts.py \
      tests/unit/loom/pipeline/test_executor_capabilities.py \
      tests/unit/loom/diagnostics/test_diagnostics_preflight.py \
      tests/contracts/test_executor_capabilities_contract.py \
      tests/contracts/test_container_executor_contract.py \
      tests/contracts/test_diagnostics_preflight_contract.py \
      tests/integration/pipeline/test_apptainer_executor.py \
      tests/integration/pipeline/test_runtime_capabilities_integration.py

Final commands:

    make validate-pr
    make test-summary

Add and exercise the opt-in acceptance hook's absent-prerequisite behavior,
but do not count a skipped real-runtime check as acceptance. The selected
scheduling-only route needs its own positive live receipt. Positive hard-limit
proof is separately deferred under the approved amendment; report the limitation
in any eventual PR. Full gates and independent review remain required for phase
completion; current receipts below satisfy them and close the coordinator blocker.

## Risks, Review, And Stops

Do not infer cgroup delegation from a runtime version. Stop the live-runtime
path for a required administrative change or missing image permission, while
completing independent scoped offline work. Stop product implementation for
incompatible public semantics or materially broader unsupported-runtime handling.
An unavailable hard-limit check remains an explicit gap and cannot support a
stronger enforcement claim. The 3/3 historical correction budget remains consumed;
one additional bounded passive-wait amendment is expressly approved. Stop for a
new unrelated correction or broader coordinator mechanism, not for the superseded
missing-authority condition. Independent startup and final gates remain required.

## Executor Handoff

Read this card and manifest Shared Constraints after startup preparation. The
executor owns listed code/tests/docs and its completion receipt only; it is not
alone and must preserve others' work. No PR/merge, delegation, downloads, host
administration, or timeout implementation. Return exact validation and blockers.
The combined independent startup review passed without findings. Implement this
bounded amendment and scheduling-only policy, retaining the final review/full gates.

## Workflow State

- Current scoped authority: maintainer approved the remaining mixed-stage warning
  correction and one fresh independent verification. "No restrictions if unmapped"
  means no invented direct CPU/RAM limits when intent is absent or the explicit
  scheduling-only policy disables that mapping. Preserve canonical validation,
  default runtime mapping, managed demand, GPU/SLURM ownership, inherited host
  controls, and the explicit CLI strict-warning policy. Historical budgets are
  not reset; broader product changes or unrelated blockers require direction.
- Correction coverage: use the full-stage mapping owner for warning severity;
  test implicit eval fallback beside GPU-only train, FAIL precedence for an
  unrepresentable runtime-mode train request, and no-resource PASS/no invented flags.
  Reuse runtime/SLURM mapping and CLI warning/strict tests; refresh both full gates.
- Additional amendment authority: maintainer approved one bounded cause-backed
  coordinator-responsiveness correction and later scheduling-only implementation.
  Historical correction counts and validation gates remain unchanged. Measured
  evidence selects passive waits; independently review before product work and
  stop for a broader/new remedy.
- Manager preparation: complete; predecessor remote merge, fresh published base,
  source/targeted-lane refresh, ownership, approval, and private discretion verified
- Expanded planning: scheduling-only policy design independently accepted;
  manager corrected minor traceability/authority wording. The separately approved
  passive-wait correction and combined startup passed independent review without
  findings. Both amendments are implemented at `8702e06`. No general
  correction-budget reset is inferred.
- Live acceptance: approved image available; runtime-limit attempt failed for
  missing D-Bus session. Scheduling-only SIF smoke passed (one test); positive
  runtime-limit proof deferred separately, never counted as passing.
- Implementation: resource mapping and approved amendments complete at `8702e06`,
  including retained pre-grant retry safety coverage. Both full gates passed.
- Independent correctness review: passed for the resource implementation,
  `ff42b6d` acceptance-probe correction, and `9ebd227` A-12 test synchronization.
  Fresh independent review also accepted the passive-wait/retry boundary.
  The newly approved independent verification accepted the mixed-stage warning
  correction at `04443ed` without findings. No PR/merge before fresh full gates.
- Blocker corrections: 3/3. First, fail closed on missing cgroup membership and
  control reads; four executable-shell regressions pass and independent
  correction review accepted `ff42b6d`. Second, the refreshed summary exposed
  upstream A-12: background accepted-time sampling races a whole-database
  no-retirement-mutation assertion. Hold the existing cycle lock only around
  before/rejection/after, preserving full equality and production behavior.
  `make validate-pr` passed at `ff42b6d`; its summary had 2,967 passes and this
  one failure. At `9ebd227`, the affected session/probe lane passed 48 tests,
  but the refreshed default gate exposed A-13. The third candidate routes the
  pre-grant control poll through the existing assignment retry owner. A failure
  trace shows that retry succeeding, but prior renewal/control calls waited for
  the coordinator's reconciliation lock until the overall test deadline was
  exhausted. Cancellation replay passes without launch. The original
  uninstrumented trigger's entire causal history remains unproven. The additional
  approved amendment now identifies reader-driven lock reacquisition using new
  measurements. Rejection/exhaustion coverage and full gates passed at `8702e06`;
  independent review accepted the queue implementation.

## Completion Record

The accepted policy is implemented at existing owners. `6b831e7` corrected direct
executor namespace selection and global/explicit-stage fallback warnings.
`04443ed` completes visible warnings for implicit stages inheriting container
CPU/RAM beside a nonempty explicit stage request: the full-stage mapping owner
now returns WARN for `not_enforced` items, with FAIL precedence and unchanged
runtime/SLURM reporting. No new mapping, validation owner, or runtime limit was
introduced. The maintainer expressly approved this final correction and one fresh
independent verification; historical correction and reviewer budgets stay consumed.

The final correction's negative control reproduced two expected warning failures
with five passing boundary checks. Its focused preflight/command/CLI contract and
integration lane passes 80 tests, including a GPU-only train plus implicit eval
memory fallback, an unrepresentable runtime-mode train request that retains FAIL,
and absent-resource PASS/no-limit commands. Existing strict-preflight policy and
canonical validation remain unchanged. Both full gates passed at `04443ed`:
2,994 summary passes and five optional skips. The scheduling-only SIF smoke
passes one test. Fresh bounded independent
verification passed without findings and closed the remaining warning defect.

| Item | Result |
| --- | --- |
| Implementation and changed paths | Implemented the bounded passive-wait correction by removing reader wakeups from `LocalDaemon._wait` and `wait_admission`; mutation and periodic service wake owners remain unchanged. Retained pre-grant control replay/rejection and bounded exhaustion coverage. Added `ApptainerExecOptions.cpu_memory_enforcement` (`runtime` default or `scheduling_only`), command-level canonical validation with conditional CPU/RAM flags, emitted-flag-aware missing-result remedies, selected-policy provenance/capability/preflight evidence, and a scheduling-only live hook. Changed `src/loom/{queue/local_daemon.py,pipeline/executors/apptainer/{commands.py,executor.py},pipeline/runtime/capabilities.py,diagnostics/preflight.py}`, focused queue/container/profile/capability/preflight tests, `tests/container_acceptance/test_real_container_runtimes.py`, and `docs/features/{queue.md,container-executors.md}`. |
| Current validation and revision | Product commit `04443ed`: focused correction lane 80 passed; `make validate-pr` passed (Ruff, Pyright, default 2,837 passed / 138 deselected, config-extra 157 passed / five optional skips / 2,840 deselected, package build). `make test-summary` passed: 2,994 passed, five optional skips, 815.20 seconds; `build/test-summary.md`. Only roadmap metadata changed afterward. Negative control: two expected warning failures and five passes, `build/implicit-stage-warning-negative-control-v2.xml`; focused receipt `build/implicit-stage-warning-correction.xml`. |
| Prior evidence and invalidation | Initial resource tree `7b28cb3`: targeted 138 passed, both gates passed, 2,964 summary passes and four optional skips. Probe correction `ff42b6d`: four shell regressions passed; old-probe negative control failed three cases; `make validate-pr` passed with 2,811 default and 157 config-extra tests. Its summary then exposed A-12: 2,967 passed and one failed, preserved under `build/test-summary-before-session-race-fix.md` and the matching directory. These receipts are not fresh full validation for the subsequent A-12 correction. |
| Real runtime evidence / unavailable checks | Approved local shell SIF checksum matched planning evidence. Scheduling-only production-command smoke passed at `04443ed`: one passed, receipt `build/container-scheduling-only-04443ed.xml`; it retained CPU/RAM intent and omitted direct flags. The runtime-limit hook remains a real rootless D-Bus prerequisite failure at `build/container-resource-acceptance-local-sif.xml`; positive hard-limit proof remains deferred to a compatible approved host. |
| Amendment review and routing check | Independent policy-design and combined amendment startup reviews passed without findings. Passive waits remain the measured, approved correction; deterministic nonterminal observer tests confirm neither path wakes reconciliation while existing queue integration, cancellation replay, retry, and production-daemon coverage pass. |
| PR, review, and merge | [#278](https://github.com/samcantrill/loom/pull/278) squash-merged to develop at `0c0dbf2a79e97ca4c242b34613cd7991ff1c3364`. Resource mapping, localized corrections, and passive-wait/retry independently accepted. Final warning verification passed without findings at `04443ed`. Both full gates passed; manager verified body, scope, target, title, mergeability, and unchanged product tree before merge. Remote merge confirmed; merged tree equals reviewed head `e9f050f`. |
| Residual risk and cleanup | Hard CPU/RAM enforcement remains unproven on this host; scheduling-only smoke is not enforcement evidence. Latest receipts and generated queue logs preserved in integration `build/stage-38-p2-04443ed`, summary SHA-256 `74273b9c989311f8fbe9b7e7b5faab9138a3545614755a540c315c6cb85dd7af`. Earlier receipts remain in `build/stage-38-p2-6b831e7` and `build/stage-38-p2-8702e06`. Original dirty content hashes remain unchanged; the preservation branch and concurrent develop worktree remain untouched. Integration checkout advanced safely to the merged tree; phase worktree and local/remote branches removed. |
