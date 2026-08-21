# Fake Backend and Explicit Local Materialization

This example registers a project-local fake artifact-store backend through
`ArtifactStoreBackendRegistry`, prints its explicit unsupported provider
materialization capability/operation evidence, then checksum-verifies an
explicit local copy through `materialize_artifact_locally`.

Loom does not select or ship a remote provider here. The fake backend never
contacts a network and does not imply support for credentials, upload, download,
or automatic materialization.

## Public Python Surface

The walkthrough uses `ArtifactStoreBackendRegistry`, backend descriptors and
capability/operation records, `ArtifactMaterializationRequest`, and
`materialize_artifact_locally`. The resulting copy is an explicit local `file:`
payload operation, not a remote download.

Run from the repository root:

```sh
uv run python examples/storage/fake-backend-materialization/run_fake_backend_materialization.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect the source and
materialized local files.
