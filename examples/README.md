# Loom Examples

These examples show supported `loom` behavior through small, domain-neutral
projects. Project code owns concrete stages and recipes; `loom` owns
configuration, artifact records, local execution, provenance snapshots, and
same-run resume decisions.

Examples are organized by user goal. Each group has its own README with the
runnable examples and what each one demonstrates. The layout is intended to
scale with the roadmap: authoring examples teach how to describe work,
execution examples teach how work runs, and operations examples teach how to
inspect, debug, and manage runs. Later roadmap items can add `experiments/`,
`storage/`, and `extensions/` groups without making individual backends top
level concepts.

## CLI Workflows

| Group | Primary user-facing workflows |
| --- | --- |
| [Execution](execution/README.md) | Runtime-profile runs, subprocess execution, Docker container execution, offline-first import, and SLURM dry-run/live command flows. |
| [Operations](operations/README.md) | Authority lifecycle, local diagnostics, failure inspection, resource preflight, offline import rejection, and live SLURM job commands. |

## Public Python API Workflows

| Group | Primary public Python surfaces |
| --- | --- |
| [Authoring](authoring/README.md) | `compose_config`, artifact-safe config inspection, recipe expansion, and trusted target instantiation. |
| [Execution](execution/README.md) | `PipelineRunner` run/resume flows and `RunOptions` construction and validation. |
| [Operations](operations/README.md) | Captured-log execution setup and authority-backed resource coordination APIs. |

Internal demos stay in-repo for regression coverage, but the primary catalog
excludes support-only workflows that rely on service fixtures or synthetic
state seeding.

Run smoke examples from the repository root with the commands listed in each
group README.

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect generated
example outputs. Execution and operations examples also accept
`LOOM_EXAMPLE_RUN_ROOT` for run directories.

## Validation Tiers

- `smoke`: fast runnable examples covered by the docs/example smoke harness.
- `full`: runnable examples that are useful but broader than the smoke path;
  these use named integration or e2e evidence, often in the config-extra
  optional-dependency test leg.
- `manual`: illustrative examples that cannot run in the default environment and
  must document why in their manifest.

## Manifest Inventory Contract

Each `example.yaml` manifest includes these docs-owned catalog fields:

- `public_surfaces`: one or more public surfaces demonstrated by the example.
- `owner_docs`: one or more repo-relative docs that own the example contract
  (group README and feature-coverage docs where applicable).
- `owner_stages`: one or more owning roadmap stages (`v0`, `v1`, ...).
- `validation_path`: required path-style evidence pointer for what proves the example.
- `validation_command`: preferred pytest command for smoke coverage. Smoke
  examples keep this command even when `validation_path` points at stronger
  representative integration or e2e evidence.
- `prerequisites` / `manual_rationale`: required for manual or illustrative
  examples to explain why default execution cannot run.

V6/v7 SLURM and submitted-operation example coverage is tracked in
[`docs/features/slurm-example-coverage.md`](../docs/features/slurm-example-coverage.md).
V10 user-facing authority workflow coverage is tracked in
[`docs/features/authority-example-coverage.md`](../docs/features/authority-example-coverage.md).
V17 container executor coverage is tracked in
[`docs/features/container-example-coverage.md`](../docs/features/container-example-coverage.md).

Runnable examples stay local and synthetic. Manual SLURM examples document the
real-cluster commands and shared-filesystem assumptions but are not executed by
default validation. Future roadmap examples should be added under the user-goal
group they teach, for example `experiments/` for sweeps.
