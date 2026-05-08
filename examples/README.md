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

## Example Groups

| Group | Demonstrates |
| --- | --- |
| [Authoring](authoring/README.md) | Trusted YAML composition, includes, recipes, artifact-safe records, structured errors, and explicit `_target_` instantiation. |
| [Execution](execution/README.md) | Local execution, subprocess execution, runtime profiles, Python run options, artifact storage, provenance snapshots, and same-run resume behavior. |
| [Operations](operations/README.md) | Preflight, run status, bounded logs, metadata-only artifact inspection, failure diagnostics, and resource warnings. |

Run smoke examples from the repository root with the commands listed in each
group README.

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect generated
example outputs. Execution and operations examples also accept
`LOOM_EXAMPLE_RUN_ROOT` for run directories.

## Validation Tiers

- `smoke`: fast runnable examples covered by default integration tests.
- `full`: runnable examples that are useful but too slow or broad for the
  default test path; tests should mark these `slow`.
- `manual`: illustrative examples that cannot run in the default environment and
  must document why in their manifest.

Planned v6/v7 SLURM and submitted-operation examples are tracked in
[`docs/features/slurm-example-coverage.md`](../docs/features/slurm-example-coverage.md).

The current examples stay local and synthetic. They do not require remote
stores, distributed execution, scheduler integration, containers, plugins, or
cross-run cache reuse. Once roadmap support lands, new examples should be added
under the user-goal group they teach, for example `execution/slurm/` for live
cluster execution and `experiments/` for sweeps.
