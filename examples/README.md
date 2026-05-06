# Loom Examples

These examples show supported `loom` behavior through small, domain-neutral
projects. Project code owns concrete stages and recipes; `loom` owns
configuration, artifact records, local execution, provenance snapshots, and
same-run resume decisions.

Examples are organized by user-facing capability. Each group has its own
README with the runnable examples and what each one demonstrates.

## Example Groups

| Group | Demonstrates |
| --- | --- |
| [Config](config/README.md) | Trusted YAML composition, overlays, includes, recipes, artifact-safe records, structured errors, and explicit `_target_` instantiation. |
| [Pipelines](pipelines/README.md) | Local pipeline execution, artifact storage, provenance snapshots, and same-run resume behavior. |

Run smoke examples from the repository root with the commands listed in each
group README.

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect generated
example outputs. Pipeline examples also accept `LOOM_EXAMPLE_RUN_ROOT` for run
directories.

## Validation Tiers

- `smoke`: fast runnable examples covered by default integration tests.
- `full`: runnable examples that are useful but too slow or broad for the
  default test path; tests should mark these `slow`.
- `manual`: illustrative examples that cannot run in the default environment and
  must document why in their manifest.

The v0 runtime is local-only. It does not provide a functional CLI, remote
stores, distributed execution, scheduler integration, or cross-run cache reuse.
