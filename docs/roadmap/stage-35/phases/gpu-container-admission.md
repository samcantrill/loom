# Phase 2 Execution Plan: GPU Container Admission

## Metadata

- Status: planned
- Roadmap stage and phase: Stage 35, Phase 2
- Manifest: `docs/roadmap/stage-35/implementation-plan.md`
- Branch: `agent/stage-35-p2-gpu-container-admission`
- Worktree root and path: `/nas/home/can134/work/loom-worktrees`;
  `/nas/home/can134/work/loom-worktrees/stage-35-p2-gpu-container-admission`
- Base revision: current `origin/develop` after Phase 1 remotely merges
- PR target: develop
- PR title: `Stage 35 phase 2: add GPU container admission`
- Dependencies: merged Stage 35 Phase 1 and existing resource, Apptainer, and
  Slurm container paths
- Workflow path: expanded; host/scheduler/container trust boundary and
  intentionally importable executor helper
- Blockers: none; implementation begins only after Phase 1 remotely merges

## Objective And Context

- Vertical outcome: one exclusive generic GPU request enables NVIDIA
  passthrough, validates exactly one operator- or scheduler-visible opaque
  device, and carries that visibility through a clean local or Slurm container.
- Earlier dependency: Phase 1 supplies the configuration/store closure needed
  by the current downstream recipe but contributes no GPU semantics.
- Later work explicitly out of scope: GPU inventory/discovery, managed queue
  assignment changes, shared/fractional modes, CPU/memory flags, timeouts,
  distributed/rank launch, and project-specific framework behavior.

## Current Source And Harness

- Relevant files and symbols: `ResourceRequest`, `ApptainerExecOptions`, direct
  `_prepare_apptainer_attempt`, container environment projection, Slurm resource
  mapping/wrapping/planning/rendering, executor descriptors, and preflight GPU
  checks.
- Existing tests and seams: pure command builders, fake Apptainer executor,
  Slurm planner/script tests, dry-run integration/e2e, capability contracts,
  diagnostics tests, and real-container opt-in markers.
- Import, dependency, or harness constraints: helper remains executor-owned and
  dependency-light; default tests never require CUDA, Apptainer, or Slurm;
  physical tokens must not enter safe persisted command metadata.

## Scope

In scope:

- Add `loom.pipeline.executors.gpu_visibility` with immutable evidence,
  exclusive-count extraction, `validate_cuda_visibility`, and
  `project_apptainer_gpu_options`.
- Keep tokens opaque, validate missing/empty/`-1`, token shape, duplicates, and
  exact positive requested count; zero request performs no managed injection or
  isolation claim.
- Accept only an attribute-free exclusive count, project
  `nv = authored.nv or requires_gpu`, preserve every other exec option, and fail
  on ROCm conflicts when a GPU resource is requested.
- Wire direct Apptainer/Singularity setup to validate host visibility before
  launch, reject authored container visibility, and explicitly inject the
  validated value through clean environment command construction.
- Pass the same per-stage resources into Slurm-afterok container wrapping so
  `--gres` and `--nv` agree; render allocation-time validation and both
  Apptainer/Singularity environment prefixes immediately before the command.
- Update preflight/capability wording, public import tests, feature docs, and
  hermetic unit/integration/e2e coverage.

Out of scope:

- Choosing physical device IDs, changing queue GPU providers, exposing raw
  device tokens in persisted metadata, GPU utilization/model discovery,
  attribute-bearing exclusive requests, non-exclusive modes, Slurm single-job
  GPU aggregation, Docker GPU support, CPU/memory flags, timeout/process
  supervision, rank variables, and mandatory live tests.

Assumptions:

- Canonical `ResourceRequest` has already validated positive exclusive count
  entries; the helper additionally rejects every attribute-bearing or
  non-exclusive shape at the executor mapping boundary.
- Local operators restrict `CUDA_VISIBLE_DEVICES` before invoking Loom; Slurm
  supplies it only inside an allocated job.
- Apptainer and Singularity honor their respective prefixed environment values
  under clean environment execution.

## Fixed Contracts And Private Discretion

- Observable behavior: one GPU produces `--nv`, one matching visible token in
  the container, and setup/admission failure before the worker on missing,
  malformed, duplicate, or mismatched visibility.
- Public or durable shapes: importable projection/validation functions and
  evidence `to_dict()` containing requested count and opaque token list; no new
  persisted schema.
- Trust and failure boundaries: local host or scheduler owns physical binding;
  Loom owns count admission and container propagation; project config cannot
  author `CUDA_VISIBLE_DEVICES` for a managed GPU request.
- Cross-phase contracts: resolved resources and configured run/artifact mounts
  remain unchanged; downstream projects consume normal Loom execution.
- Reproducibility and compatibility: physical tokens remain invocation data,
  not fingerprints; no GPU entry leaves authored options unchanged and the
  ordinary default remains CPU-only.
- Private choices the executor may simplify: internal parser/count helper
  names, safe count-only executor metadata, shell helper factoring, and exact
  diagnostic codes consistent with current conventions.

## Proportionality

- Existing seam reused: canonical resources, immutable exec options, container
  environment projection, Slurm `--gres`, wrapper, renderer, descriptors, and
  fake runners.
- Material additions and current justification: one pure module and one
  allocation-time shell block are required to prevent resource/container/
  visibility drift across two supported execution paths.
- Optional hardening and future capability deferred: inventory, share modes,
  distributed launch, token-to-hardware verification, torch probes, Docker GPU,
  and live default tests.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Exclusive GPU request maps to one passthrough decision | GPU projection helper | canonical resources plus authored exec options | resource and container access disagree | pure projection/conflict tests |
| Direct visible count matches request before launch | direct executor setup | operator host environment | worker sees missing/extra GPU | fake executor success/failure cases |
| Slurm validates only allocation environment | generated script | scheduler-populated job environment | submit-host state is mistaken for allocation | rendered-script assertions and shell execution harness if existing |
| Clean container receives scheduler/operator binding | container env projection / Slurm prefixes | `cleanenv` boundary | PyTorch sees all or no devices | command/script environment assertions |
| Raw token is not durable command identity | metadata/redaction owner | executor result persistence | physical allocation contaminates identity or leaks | redacted metadata tests |

## Implementation Slices

1. Add the pure GPU module and focused public/resource/token tests.
2. Integrate resource-derived options and visibility into direct Apptainer/
   Singularity preparation, command, safe metadata, and fake executor tests.
3. Thread resources through Slurm container wrapping and add allocation-time
   validation/propagation with planner/script tests.
4. Align preflight/capability diagnostics, public package assertions, docs, and
   public dry-run integration/e2e evidence.
5. Run targeted and full gates and update only this phase's workflow state.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional executor helper import without broad root re-export | package/import boundary assertion |
| Unit | required | Token/count/projection, direct command/setup, Slurm wrapper/script, preflight | success and reachable negative producers only |
| Contract | required | Capability and runtime handoff truth remain domain-neutral | descriptor/execution envelope assertions |
| Integration | required | Fake direct execution and Slurm dry-run carry coherent resource/access/env | one local and one Slurm vertical journey |
| E2E / opt-in | hermetic e2e required; real opt-in deferred | Public CLI script contains `--gres`, `--nv`, and allocation handoff; physical success needs infrastructure | fake CLI journey plus documented live acceptance |

Targeted commands:

    uv run pytest tests/unit/loom/pipeline/executors/apptainer tests/unit/loom/pipeline/executors/slurm tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/integration/pipeline/test_apptainer_executor.py tests/integration/pipeline/test_slurm_dry_run_planning.py tests/e2e/test_cli_slurm_dry_run.py
    uv run ruff check src/loom/pipeline/executors src/loom/diagnostics tests/unit/loom/pipeline/executors tests/unit/loom/diagnostics

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: interpreting selectors or share resources as device counts;
  validating Slurm on the submit host; losing the
  scheduler value under `cleanenv`; persisting raw binding tokens; or claiming
  distributed/hardware allocation.
- Review focus: exact resource owner, local versus allocation boundary,
  passthrough conflicts, token opacity, clean environment behavior, metadata
  redaction, public API intent, and no queue/distributed scope creep.
- Stop if: correct behavior requires GPU inventory, share enforcement,
  scheduler discovery, rank launch, a new durable schema, or a mandatory live
  environment.
- Accepted debt and revisit trigger: Python and generated shell validators must
  mirror the same small grammar; revisit only if another allocation-time shell
  consumer or richer binding grammar appears.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above.
- Decisions not to revisit: bare exclusive count only, additive resource-derived `nv`, opaque
  tokens, direct-host versus Slurm-allocation validation, authored visibility
  rejection, count/redacted persistence, and no distributed/CPU/memory/timeout
  work.
- Conditions requiring manager action: public compatibility evidence requiring
  a second `nv` authority, inability to propagate through cleanenv, a current
  supported share-mode consumer, or a durable/raw-token requirement.

## Workflow State

- Manager preparation: pending planning and Phase 1 merge.
- Expanded planning: completed; all three concrete findings were resolved in
  the stage planning document.
- Implementation: pending.
- Refiner: not needed unless a qualified blocker appears.
- Pre-submit gate: pending.
- Independent review: required for scheduler/container boundary.
- Blocker corrections: 0/3.
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
