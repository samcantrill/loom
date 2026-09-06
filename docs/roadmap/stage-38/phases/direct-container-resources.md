# Phase 2 Execution Plan: Direct Container Resource Mapping

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 38, Phase 2
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p2-direct-container-resources`
- Worktree: create under recorded root after Phase 1 is remotely merged
- Base revision: resolve current published develop at startup
- PR target: develop
- PR title: `feat(execution): map direct container CPU and memory requests`
- Dependencies: Phase 1 merge; independent audit dispositions
- Workflow path: expanded correctness review for external-runtime mapping
- Blockers: predecessor pending; actual container acceptance image/prerequisites

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

## Scope

In scope: deterministic CPU/memory argv conversion, actionable unsupported
mapping/runtime failures, truthful capability/preflight/docs, a real-runtime
acceptance hook over existing test infrastructure, and the bounded A-9 correction.
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
- Report mapping support separately from host-dependent enforcement. Existing
  `SUPPORTED`/`BEST_EFFORT` vocabulary can describe flags plus cgroup caveats;
  do not report observed host enforcement without actual evidence.
- Unsupported runtime options must lead to an actionable failure; never retry
  without requested limits or silently degrade into advisory execution.
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

Final commands:

    make validate-pr
    make test-summary

Manager refreshes exact targeted commands against current source at startup.

## Risks, Review, And Stops

Do not infer cgroup delegation from a runtime version. Stop for a required
administrative change, missing image permission, incompatible public semantics,
or materially broader unsupported-runtime handling. An unavailable acceptance
check remains an explicit gap; it cannot support a stronger enforcement claim.

## Executor Handoff

Read this card and manifest Shared Constraints after startup preparation. The
executor owns listed code/tests/docs and its completion receipt only; it is not
alone and must preserve others' work. No PR/merge, delegation, downloads, host
administration, or timeout implementation. Return exact validation and blockers.

## Workflow State

- Manager preparation: pending predecessor merge and source refresh
- Implementation, pre-submit gate, independent review, PR and merge: pending
- Blocker corrections: 0/3

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | not started |
| Tests and validated revision | pending |
| Real runtime evidence / unavailable checks | image and prerequisites pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
