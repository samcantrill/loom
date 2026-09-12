# Docker Agent Worker Example

The run entrypoints use public `loom.run` with a protected installed agent
profile. Preparation, execution, fenced results and owned-service cleanup follow
the [configured lifecycle](../../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). The native admission supplies run status;
typed materialized worker results supply output and diagnostic details after
owned services stop. The short deployment root printed by the script is retained
for inspection; artifacts default to this example's `runs/` directory. Set
`LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to relocate artifacts.

The two run scripts bind an explicit local fake daemon endpoint and an absolute
runtime command in the installed profile. The stateful fixture runs the real
execution-only worker and retains container state independently of each CLI
helper. It tests native admission, Docker metadata, numerical outputs, failure
logs and cleanup; it does not qualify a physical Docker installation.

```sh
uv run python examples/execution/containers/docker/run_docker_pipeline.py
uv run python examples/execution/containers/docker/run_failure_diagnostics.py
uv run python examples/execution/containers/docker/run_preflight.py
```

The separate preflight script keeps its pure command fixture and authored Docker
adapter options. The managed run records `runtime.profile=null` as a preparation
override: its installed agent profile owns container selection. The shared YAML
remains available for standalone preflight consumers.

The supervisor creates an exactly named/labelled container with `--restart=no`
and `--pull=never`, captures the immutable ID, starts it once, and observes daemon
terminal evidence before removal. No `--rm` erases evidence at exit. Worker mounts
preserve host/container paths and the image must already contain the selected
Python, Loom, Weave and project dependencies. See the [installed profile contract](../../../../docs/features/container-executors.md#managed-agent-workers).

Physical acceptance remains opt-in under `tests/container_acceptance`; fixture
results do not qualify an image or site. No image build or pull is performed.
