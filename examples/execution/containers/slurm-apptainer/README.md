# Apptainer Agent Worker Example

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

The run script prepares and executes the pipeline through a protected installed
Apptainer profile. Its default fixture supplies an absolute fake runtime command
and an explicit namespace-observation seam, including fresh supervisor processes.
It executes real workers but does not qualify kernel isolation or an HPC site.

```sh
uv run python examples/execution/containers/slurm-apptainer/run_apptainer_pipeline.py
```

An already-qualified local runtime can use `LOOM_APPTAINER_RESOURCE_IMAGE` for an
installed SIF, `LOOM_APPTAINER_COMMAND` for its absolute executable, and optionally
`LOOM_CONTAINER_PYTHON` for image Python. The image must contain Loom, Weave and
project dependencies. The supervisor observes the namespace init before granting
worker effects and requires positive namespace containment before release.

The managed run records a `runtime.profile=null` preparation override so the
installed profile selects the environment. Shared YAML and the separate Slurm
script retain their existing owner. For standalone preflight:

```sh
uv run loom preflight examples/execution/containers/slurm-apptainer/pipeline.yaml \
  --check executor --check filesystem --format json
```

On a real Slurm cluster, allocation remains owned by the existing
`slurm-single-job` or `slurm-afterok` path; Apptainer owns its worker environment.
Live scheduler/container qualification remains site-specific and opt-in.
