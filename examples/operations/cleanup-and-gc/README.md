# Preview-First Cleanup And Garbage Collection

This example proves the safe cleanup journey: preview a per-run candidate with
`loom clean`, delete it only after explicit confirmation, then preview and
delete the remaining collection candidate with `loom gc`. Both run directories,
their committed outputs, and unregistered temporary files remain in place.

Loom currently has no public command for authoring cleanup candidates. The
entrypoint therefore uses an isolated, explicitly setup-only repository fixture
to register two temporary payloads before the documented journey starts. That
fixture is not project code or a supported cleanup-candidate API; the behavior
being demonstrated is the public CLI's candidate selection and deletion.

## Workflow

After Loom has registered candidates inside managed run roots, the public
commands are:

```sh
uv run loom clean file:///tmp/loom-examples/runs/first --format json
uv run loom clean file:///tmp/loom-examples/runs/first --delete --yes --format json
uv run loom gc /tmp/loom-examples/runs --format json
uv run loom gc /tmp/loom-examples/runs --delete --yes --format json
```

## Variants

Narrow a preview by the candidate's registered lifecycle reason:

```sh
uv run loom clean file:///tmp/loom-examples/runs/first --reason temporary_payload
```

Run the isolated complete journey from the repository root:

```sh
uv run python examples/operations/cleanup-and-gc/run_cleanup_and_gc.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect all
fixture state and run directories beneath a chosen local output root.
