# Phase 2 Execution Plan: Direct Container Resource Mapping

## Metadata

- Status: blocked
- Roadmap stage and phase: Stage 38, Phase 2
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p2-direct-container-resources`
- Worktree: `stage-38-p2-direct-container-resources` under the recorded root
- Base revision: `43b911fb0cfe9d9c5192623726607a1575a41da5`
- PR target: develop
- PR title: `feat(execution): map direct container CPU and memory requests`
- Dependencies: Phase 1 PR #277 merged at `133505b`; audit dispositions accepted
- Workflow path: expanded correctness review for external-runtime mapping
- Blockers: coordinator-responsiveness amendment; candidate review/full gates; live image/session

## Objective And Context

Implement FR-2 while preserving FR-4. Typed resource intent already reaches
`ContainerOptions.resources`; direct argv generation currently omits CPU/memory.
Retain upstream GPU behavior and fix the audit's narrow A-9 malformed multiline
allocation gap. Timeouts and process-ownership redesign are Phase 3 work.

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
infer the execution route from an authored capability record. Preflight's current
CPU/memory check reports advisory mappings without trying exact byte conversion;
reuse the command owner's conversion rules rather than duplicating them there.

Manager refresh verified that these production owners are unchanged since the
audited baseline; the merged predecessor changes CLI validation, its tests/docs,
and a test-only SLURM race. Use Python 3.12 and this worktree's locked environment
(`uv sync --locked --all-groups`), never the dirty checkout's environment.

## Scope

In scope: deterministic CPU/memory argv conversion, actionable unsupported
mapping/runtime failures, truthful capability/preflight/docs, a real-runtime
acceptance hook over existing test infrastructure, and the bounded A-9 correction.
The approved A-13 amendment also covers the reproduced pre-grant control-response
retry omission in `queue/agent_session_transport.py`, focused transport tests,
and its existing queue contract documentation. Reuse the established bounded
assignment retry owner; preserve control replay, rejection, and exhausted-retry
retention. No global transport recovery or ownership redesign is included.
Out of scope: changing resource semantic validators, GPU allocation, fractional
CPU scheduling, new registries/config namespaces, timeouts, container builds or
downloads without explicit authority, and host system administration.

## Fixed Contracts And Private Discretion

- Canonical CPU is a positive integer, unit absent or count, without attributes.
  Do not map zero to unlimited or accept fractional CPUs by broadening Loom.
- Canonical memory is positive with B/KiB/MiB/GiB/TiB. Convert exactly to positive
  integer bytes; reject fractional bytes or values unrepresentable by the
  selected runtime. No silent rounding, overflow, or attribute reinterpretation.
- Two CPUs and 512 MiB produce `--cpus 2 --memory 536870912` before the image.
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
  Current missing-worker-result errors carry redacted process metadata but no
  resource-specific remedy. The new rejection path must explain where to inspect
  runtime diagnostics and how to supply a compatible runtime/cgroup setup,
  without claiming every startup failure was caused by resource limits.
- Preserve upstream GPU passthrough, count validation, redacted metadata, and
  explicit `nv=True`. SLURM remains the CPU/memory enforcement owner on its
  scheduler route; direct flags must not accidentally change that composition.
- A-9: reject an invalid complete allocation value before line-oriented Bash
  parsing; retain accepted opaque token grammar and protected output behavior.
- Private flag/conversion helpers and fixture layout are executor discretion;
  no new shared abstraction is required for one direct adapter family.

## Proportionality

Extend current container intent and capability owners. Add no parallel resource
configuration. The SLURM correction is justified by a reproduced supported
environment-boundary defect and belongs in the existing executable grammar
test, not a replacement scheduling mechanism.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| Canonical request validity | Resource validators | Public intent or config could bypass valid units/amounts | Reuse validation; mapped and rejected examples |
| Exact runtime units | Direct argv conversion | Fractional bytes/overflow silently change limits | Exact byte checks and representative units |
| Honest support/failure | Capabilities, preflight, runtime CLI | Flags exist but host cannot enforce | Consistent diagnostic caveats; runtime rejection and real acceptance |
| Whole allocation grammar | SLURM script boundary | Newline suffix bypasses first-line parsing | Actual Bash and Python agree; raw values not printed |

## Implementation Slices

1. Refresh upstream/resource owners and confirm exact request-to-intent flow.
2. Implement supported mappings and explicit rejection using current validators.
3. Align capabilities, preflight, and docs; preserve GPU and scheduler ownership.
4. Correct A-9 and extend executable grammar coverage with newline cases.
5. Add/run a small real-container acceptance test with an explicitly supplied
   image and bounded CPU/memory work; record unavailable prerequisites honestly.
6. Run focused suites, final gates, and record evidence for independent review.

## Test And Validation Plan

Required: direct command/executor units and integration, capability contract,
preflight tests, executable GPU grammar and SLURM-container composition. Cover
positive CPU, binary units, exact fractional-unit-to-byte conversion, invalid/
unrepresentable requests, no request, argv ordering, and preserved GPU redaction.
Real acceptance must use the generated production command and inspect applied
limits where the host permits it; CLI version/help is not enforcement proof.
The absent prerequisite path must fail clearly without claiming success.

Read-only host evidence during Phase 1: SingularityCE `3.10.4-focal`, cgroups
v2, no user systemd bus socket, and `systemctl --user is-system-running` failed
to connect to the bus. The [runtime requirements](https://docs.sylabs.io/guides/3.10/user-guide/cgroups.html)
include delegated unified cgroups and compatible systemd configuration for
non-root enforcement. These observations identify an acceptance prerequisite
gap, not an actual container enforcement result. The maintainer must supply an
approved local image and a suitable runtime session/host for that check; do not
silently create images, alter host administration, or waive the required check.

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
but do not count a skipped real-runtime check as acceptance. The executor may
complete offline implementation and gates while that external prerequisite is
pending; phase completion and merge remain held for the required runtime proof.

## Risks, Review, And Stops

Do not infer cgroup delegation from a runtime version. Stop the live-runtime
path for a required administrative change or missing image permission, while
completing independent scoped offline work. Stop product implementation for
incompatible public semantics or materially broader unsupported-runtime handling.
An unavailable acceptance check remains an explicit gap; it cannot support a
stronger enforcement claim or a completed-phase receipt.

## Executor Handoff

Read this card and manifest Shared Constraints after startup preparation. The
executor owns listed code/tests/docs and its completion receipt only; it is not
alone and must preserve others' work. No PR/merge, delegation, downloads, host
administration, or timeout implementation. Return exact validation and blockers.

## Workflow State

- Manager preparation: complete; predecessor remote merge, fresh published base,
  source/targeted-lane refresh, ownership, approval, and private discretion verified
- Expanded planning: bounded A-13 retry work was approved; newly observed
  coordinator lock delays require the separate amendment described in planning.md.
  Live acceptance is not waived.
- Implementation: resource mapping complete through `9ebd227`; third pre-grant
  retry candidate remains work in progress and is not merge-ready.
- Independent correctness review: passed for the resource implementation,
  `ff42b6d` acceptance-probe correction, and `9ebd227` A-12 test synchronization.
  These receipts do not approve the third retry candidate. Current full
  validation and live acceptance fail the pre-submit gate; no PR or merge.
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
  uninstrumented trigger and precise lock-delay mechanism remain unproven.
  Stop further product corrections pending the responsiveness amendment; final
  rejection/exhaustion coverage, independent acceptance and full gates remain.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Offline implementation complete: direct Apptainer/Singularity CPU and exact-byte memory flags; resource-intent revalidation and actionable resource-command failure; truthful capability/preflight projection with runtime-intent override and authored-intent fallback; scheduler-owned SLURM composition/preflight; A-9 complete-value grammar check; opt-in cgroup-v2 acceptance hook. Changed `src/loom/pipeline/executors/apptainer/{commands.py,executor.py}`, `src/loom/pipeline/{runtime/capabilities.py,executors/slurm/{container.py,rendering.py}}`, `src/loom/diagnostics/preflight.py`, related scoped tests, and `docs/features/container-executors.md`. |
| Current validation and revision | WIP retry candidate: focused Ruff and whole-tree Pyright pass. Refiner's two-case loopback run had success-case timeout and cancellation pass. Manager's instrumented retry run had five passes and one timeout; its failure trace proves successful retry and eventual release after coordinator lock delays exhausted the test deadline. Additional cycle-timing run: six passed. These are diagnostic receipts, not passing full gates. Last full `make validate-pr` at `9ebd227` had 2,810 passes and one A-13 timeout; no fresh full gates for the candidate. |
| Prior evidence and invalidation | Initial resource tree `7b28cb3`: targeted 138 passed, both gates passed, 2,964 summary passes and four optional skips. Probe correction `ff42b6d`: four shell regressions passed; old-probe negative control failed three cases; `make validate-pr` passed with 2,811 default and 157 config-extra tests. Its summary then exposed A-12: 2,967 passed and one failed, preserved under `build/test-summary-before-session-race-fix.md` and the matching directory. These receipts are not fresh full validation for the subsequent A-12 correction. |
| Real runtime evidence / unavailable checks | No enforcement proof: default hook was opted out; explicit opt-in stopped because the maintainer has not supplied an approved local image and compatible delegated-cgroup runtime session. The hook reads the payload cgroup path from `/proc/self/cgroup` before inspecting `cpu.max` and `memory.max`; it performs no pull, build, download, or host administration. |
| PR, review, and merge | Resource mapping and the first two localized corrections independently accepted. The third candidate is WIP, requires final review and fresh full gates, and does not resolve the coordinator-responsiveness failure. No PR opened or branch pushed. |
| Residual risk and cleanup | Three correction passes consumed; separate responsiveness amendment and approved live image/session requested. Keep the candidate and worktree for continuation. Original failed fixture had no worker; a later instrumented fixture completed work after the test deadline. Both supervisors of that later failed fixture were verified stopped. Original dirty checkout remains preserved; published develop remains `43b911f`. |
