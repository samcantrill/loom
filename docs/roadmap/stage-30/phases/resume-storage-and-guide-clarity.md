# Phase 3 Execution Plan: Resume, Storage, And Guide Clarity

## Metadata

- Status: planned
- Roadmap stage and phase: Stage 30, Phase 3
- Manifest: `docs/roadmap/stage-30/implementation-plan.md`
- Branch: `agent/stage-30-p3-resume-storage-and-guide-clarity`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; `/home/can134/work/active/loom-worktrees/stage-30-p3-resume-storage-and-guide-clarity`
- Base revision: current `origin/develop` after Phase 2 is remotely merged
- PR target: develop
- PR title: `Stage 30 phase 3: clarify resume storage and feature support`
- Dependencies: Stage 30 Phases 1 and 2 remotely merged; existing Stage 0/15/16/22 behavior.
- Workflow path: fast
- Blockers: Phases 1 and 2 must merge first.

## Objective And Context

- Vertical outcome: the local example explains fingerprint-backed reuse and
  branch invalidation, a storage example demonstrates explicit backend and
  materialization contracts, and related feature docs expose current support,
  one quick start, and deferred behavior near the top.
- Earlier dependency: Phases 1-2 provide the final Stage 30 example inventory
  that this phase routes and validates as a whole.
- Later work explicitly out of scope: runtime changes, real providers, broad
  documentation rewrite, and generated docs tooling.

## Current Source And Harness

- Relevant files and symbols: `examples/execution/local`, planner actions and
  fingerprint records, `ArtifactStoreBackendRegistry`, payload operation
  requests/results, `ArtifactMaterializationRequest`,
  `materialize_artifact_locally`, root/group catalogs, and directly related
  feature docs.
- Existing tests and seams: local example smoke test, resume integration tests,
  artifact backend/materialization contract tests, example inventory checks,
  and docs link validation.
- Import, dependency, or harness constraints: changed-input scenario must use a
  normal public config/RunRequest path and a graph with an unaffected branch;
  storage fake must implement only the public protocols needed by the example;
  docs summaries must not replace authoritative detailed contracts.

## Scope

In scope:

- Strengthen `examples/execution/local` so it prints useful config/pipeline
  fingerprint evidence, asserts unchanged stages are `REUSE`, and executes a
  changed-input case with an unaffected branch reused and the affected branch
  rerun.
- Adjust the small pipeline only as needed to make branch-specific behavior
  understandable and deterministic.
- Add `examples/storage/` routing and one focused external-backend and local
  materialization example with README, manifest, entrypoint, and project helper.
- Register a fake backend through `ArtifactStoreBackendRegistry`, show explicit
  capability/operation evidence, then checksum-verify a local copy through
  `materialize_artifact_locally`; clearly state that Loom ships no selected
  remote provider.
- Add focused integration assertions for resume and storage entrypoints.
- Add compact `Current Support`, `Quick Start`, and `Deferred` sections near the
  top of the directly related major feature docs: run catalog, reliability,
  sweeps, container executors, resume, remote stores, and plugins/event sinks as
  needed for truthful routing.
- Finalize root/group catalogs and run complete repository validation.

Out of scope:

- Planner/fingerprint changes, transparent caching, automatic materialization,
  cloud/tracking adapters, credential behavior, network operations, plugin
  installation machinery, editing every feature document, or generating docs.

Assumptions:

- Existing planner actions and persisted fingerprint records provide enough
  public/user-facing evidence without a new result field.
- A three-stage fork/join or two-branch pipeline can show one unaffected branch
  reused while the changed branch and its downstream consumers rerun.
- The storage example may keep its fake factory/handler project-local and
  intentionally small.

## Fixed Contracts And Private Discretion

- Observable behavior: non-empty stable fingerprint summaries; all unchanged
  second-run actions are reuse; changed input yields the documented reuse/run
  split; materialization copies exact bytes with checksum evidence; backend
  registry reports the fake kind; docs distinguish implemented and deferred
  behavior.
- Public or durable shapes: existing planner actions, fingerprint records,
  backend descriptors/capabilities/operation results, materialization records,
  and example manifests.
- Trust and failure boundaries: resume trusts valid fingerprints/artifacts, not
  path presence alone; materialization is explicit and local-copy-only; fake
  provider cannot imply network/provider support.
- Cross-phase contracts: final catalogs include all Stage 30 examples and retain
  Phase 1-2 validation links.
- Reproducibility and compatibility: deterministic input variants, checksummed
  bytes, local output roots, no new persisted formats.
- Private choices the executor may simplify: pipeline topology, fingerprint
  truncation/display, fake handler implementation, exact docs wording, and test
  helper factoring.

## Proportionality

- Existing seam reused: current local example, public artifact contracts, and
  directly related feature docs.
- Material additions and current justification: one storage group/example and
  bounded edits to one example and seven related docs.
- Optional hardening and future capability deferred: corruption/resume failure
  matrix, multiple fake providers, upload/download permutations, real backend
  acceptance, and repository-wide docs normalization.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Reuse follows fingerprints and valid artifacts | Planner/resume logic | Changed config/input and persisted run boundary | Example teaches path-existence reuse | Action split plus fingerprint evidence |
| Unaffected branch remains reusable | Pipeline graph/planner | Branch-specific input change | Invalidation guidance misleading | Explicit per-stage action assertions |
| Materialization verifies and copies exact bytes | Materialization API | File/checksum boundary | Storage claim false or corrupt | Result evidence, checksum, and bytes assertion |
| Fake backend is not a provider claim | Backend registry docs/example | Extension/provider boundary | Users expect bundled cloud support | README and feature-doc current/deferred sections |
| Quick starts remain subordinate to detailed contracts | Feature docs | Long-lived spec boundary | Summary drifts or overrides detail | Link and content review plus existing docs tests |

## Implementation Slices

1. Refine the local pipeline/run script and focused validation for fingerprint,
   reuse, and branch-specific invalidation evidence.
2. Add the storage group and fake-backend/materialization journey with focused
   integration validation.
3. Add current support/quick start/deferred summaries to directly related docs
   and finalize all catalogs/manifests.
4. Run targeted checks, full `make validate-pr`, and `make test-summary`; record
   completion evidence without creating sidecars.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public imports unchanged | Existing suite |
| Unit | required via final gate | Existing planner/backend helpers | Existing suite; no redundant matrix |
| Contract | required | Backend/materialization shapes unchanged | Existing artifact contracts |
| Integration | required | Resume branch behavior and storage journey | Execute entrypoints; assert actions, fingerprints, bytes/evidence |
| E2E / opt-in | deferred unless existing harness naturally covers | No new CLI journey in this phase | Integration plus final full suite is proportionate |

Targeted commands:

    uv run pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py
    uv run pytest tests/contracts/test_artifact_store_backend_contract.py tests/contracts/test_artifact_materialization_contract.py
    uv run pytest tests/integration/pipeline -k 'resume or fingerprint or materialization'
    uv run ruff check examples tests/integration/examples

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: choosing an input change that invalidates the whole graph;
  exposing unstable/private fingerprint internals; overbuilding a fake backend;
  implying local copy materialization downloads remote data; inserting summary
  sections that contradict detailed docs.
- Review focus: action evidence is accurate, public surfaces only, fake/provider
  boundary explicit, docs summaries match code/tests, and all Stage 30 examples
  are catalogued and validated.
- Stop if: branch-specific rerun needs planner behavior changes, storage journey
  requires a provider/runtime API, or a docs summary exposes an unresolved
  public-contract choice.
- Accepted debt and revisit trigger: only directly related docs adopt the new
  summary pattern; extend opportunistically when other feature docs are changed.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the four slices above.
- Decisions not to revisit: no runtime/provider work; one small storage example;
  bounded docs set; existing public/durable contracts are fixed.
- Conditions requiring manager action: any source change, new public surface,
  provider dependency, or contradiction between current behavior and accepted
  docs scope.

## Workflow State

- Manager preparation: approved; prepare from current `origin/develop` only
  after Phase 2 remote merge.
- Expanded planning: not needed.
- Implementation: pending.
- Refiner: not needed / pending evidence.
- Pre-submit gate: pending.
- Independent review: not needed / pending residual-risk check.
- Blocker corrections: 0/3
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
