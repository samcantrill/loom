# Storage Examples

Storage examples show the explicit artifact-store extension and local
materialization boundaries. Loom does not select or ship a remote provider.

## Public Python API Workflows

| Example | Demonstrates |
| --- | --- |
| `storage.fake-backend-materialization` | Registering a project-local fake backend, inspecting its unsupported provider materialization operation, then checksum-verifying an explicit local file copy. |

## Run

Run from the repository root:

```sh
uv run python examples/storage/fake-backend-materialization/run_fake_backend_materialization.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` to redirect the source and
materialized local files. The fake backend never contacts a network or implies
that a provider adapter, credentials, upload, download, or automatic
materialization is included.
