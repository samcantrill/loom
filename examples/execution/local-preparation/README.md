# Prepare and execute a local file stage

From the repository root, run:

```sh
LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-local-file uv run --python 3.12 --locked --extra config python examples/execution/local-preparation/run_local_file.py
```

The example installs its stage through the protected worker project/Python search
path, creates a tiny UTF-8 input, and uses the ordinary native `RunRequest`
lifecycle. Its protected preparation profile selects `configuration_policy: local`.
The final override supplies the real `weights_ref.path` before preparation.
The stage reads that file and the caller checks the committed JSON artifact after
native completion. No dataset, container runtime or external service is required.

Expect `run_status: SUCCEEDED`, stopped owned coordinator cleanup and
`local_file_verified: true`. Artifact and deployment locations are printed.
All actions are hard-bound to the selected local agent and its launch bindings;
remote export refuses the unresolved local scope. See
[agent preparation](../../../docs/features/agent-preparation.md#protected-local-configuration)
for the policy and restart contract.
