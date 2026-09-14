# Authority Lifecycle

This example demonstrates the v10 public authority lifecycle:

1. `loom authority start`
2. `loom authority status`
3. `loom authority doctor`
4. `loom authority restart`
5. `loom authority stop`
6. Repeat `loom authority stop` and confirm `stopped` again.

It uses an explicit state directory and workspace registry so the output shows
the supported authority operator workflow directly. One live authority owns a
state directory and workspace at a time. Stop checks the recorded process
identity before signalling it, so a reused process ID cannot target an unrelated
process. A successful stop confirms exit; the runner requires `stopped` for both
CLI calls. The second call goes directly through the CLI because the session
helper skips repeated stops. An unverifiable live process identity produces an
explicit failure instead of an unsafe signal.

## Workflow

This workflow uses:

- `loom authority start`
- `loom authority status`
- `loom authority doctor`
- `loom authority restart`
- `loom authority stop`

## Variants

Canonical start command:

```sh
uv run loom authority start \
  --state-dir /tmp/loom-authority-state \
  --workspace-root /tmp/loom-authority-workspace
```

Fixed workspace identifier:

```sh
uv run loom authority start \
  --state-dir /tmp/loom-authority-state \
  --workspace-root /tmp/loom-authority-workspace \
  --workspace-id workspace-a
```

Fixed port for local automation:

```sh
uv run loom authority start \
  --state-dir /tmp/loom-authority-state \
  --workspace-root /tmp/loom-authority-workspace \
  --port 8765
```

Run from the repository root:

```sh
uv run python examples/operations/authority-lifecycle/run_authority_lifecycle.py
```
