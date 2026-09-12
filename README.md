# Loom

`loom` is a lightweight, generic runtime for composing, configuring, running, and
resuming small Python pipelines.

For repository-local terminology and preferred naming, see
[docs/GLOSSARY.md](docs/GLOSSARY.md).

The current implementation is local-first and geared toward deterministic
research workflow evidence:

- functional `loom validate`, `loom plan`, `loom run`, `loom status`, `loom logs`,
  `loom artifacts`, `loom authority`, `loom runs`, `loom sweep`, and cleanup
  commands
- trusted config composition, recipe expansion, and `_target_` construction
- local artifact + run stores on disk, with authority-backed coordination
- deterministic planning with conservative same-run resume
- local in-process, subprocess, fake-Docker, and SLURM dry-run execution paths
- offline-first evidence import, run bundles/catalogs, resource diagnostics, and
  structured failure records
- [native coordinator control](docs/features/coordinator-client.md) from Python
  and CLI over the local Unix socket or authenticated HTTPS
- [agent preparation](docs/features/agent-preparation.md) of shared or explicitly
  staged configuration in a specified existing environment, with coordinator-owned publication
- [MCP tools and portable skills](docs/features/mcp.md) for native coordinator
  control from Codex sessions
- import-safe boundaries between config, pipeline, execution, stores, authority,
  plugins, and CLI modules

Default examples and validation are local, synthetic, and fake-backed. Live
cluster, daemon, provider, and network-backed workflows stay manual unless a
deterministic validation fixture exists.

## Quickstart (CLI)

Validate the config shape and pipeline DAG without importing or constructing
project targets:

```sh
loom validate pipeline.yaml
```

`loom validate` checks Loom-owned graph and runtime/resource settings only.
Project owners construct and perform readiness checks for their `_target_`
objects during execution; project-shaped values remain data at Loom's static
boundary.

Preview stage actions without executing or allocating run state:

```sh
loom plan pipeline.yaml --format json
loom plan pipeline.yaml --run-uri file://./runs/example --explain build
```

Run through an explicitly configured deployment:

```sh
loom run pipeline.yaml --deployment deployment.yaml
loom run pipeline.yaml --deployment deployment.yaml --operation-id experiment-001 --detach
```

`pipeline.yaml` is relative to the deployment's selected preparation project.
The protected deployment selects coordinator/agent role configs, preparation
source/profile and each role's persistent or run-owned lifetime. Configured
local services start or reopen the same durable identities; remote services
are never silently replaced. See [configured startup](docs/downstream-operations.md#configured-startup-and-ordinary-run)
for the file format and copyable selection.

## Quickstart (Python API)

```python
import loom
from loom.coordinator import RunRequest
from loom.queue.preparation import PreparationSource, PrepareRunRequest

request = RunRequest(
    PrepareRunRequest(
        "experiment-001", "experiment-001",
        PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
        "pipeline.yaml", "existing-project",
    ),
    queue_item_id="experiment-001",
)
outcome = loom.run(request, deployment="deployment.yaml")
print(outcome.to_dict())
```

The request's preparation selection must match the deployment. Repeating the
same accepted intent reconciles its original admission; a new experiment needs
new identities. Timeout, Ctrl-C and detached waiting leave accepted work owned
by services. Cancel explicitly through the native coordinator client. Cleanup is
reported separately from execution, preserving persistent services and services
needed by other accepted work.

## Run Directory Layout

Successful local runs are materialized with durable state, plan, config, stage,
artifact, and provenance records. The exact config files depend on whether the
run was started from a composed config object or plain resolved config, but a
typical run directory includes:

```text
runs/RUN_NAME/
  run.json
  status.json
  plan.json
  artifacts.json

  config/
    composition_manifest.json
    recipe_manifest.json
  stages/
    STAGE_NAME/
      status.json
      inputs.json
      outputs.json
      fingerprint.json
      provenance.json
      logs/stdout.log
      logs/stderr.log
  artifacts/
    STAGE_NAME/
      data.json
      text.txt
  provenance/
    environment.json
```

## Extension Contracts

- Stage implementations follow `run(context, inputs) -> Mapping[str, ArtifactRef]`.
- Artifact stores implement `save`, `register`, `load`, `exists`,
  `verify_checksum`, and `validate` for one bound run.
- Run stores implement run documents, user metadata, stage state documents,
  events, and run locks.

These are structural protocol checks (`isinstance(..., Protocol)`), not inheritance
requirements.

## Relevant docs

- [docs/loom.md](docs/loom.md)
- [docs/downstream-installation.md](docs/downstream-installation.md)
- [docs/downstream-operations.md](docs/downstream-operations.md)
- [examples/README.md](examples/README.md)
- [docs/features/cli.md](docs/features/cli.md)
- [docs/features/config.md](docs/features/config.md)
- [docs/features/testing.md](docs/features/testing.md)
- [docs/structure.md](docs/structure.md)
- [docs/roadmap.md](docs/roadmap.md)
- [Coordinator access, MCP, and Loom skills](docs/briefs/mcp-implementation-plan.md) — detailed behavior and code examples; [Stage 40 implementation plan](docs/roadmap/stage-40/implementation-plan.md)

## Development

```sh
uv sync --all-groups
make help
make setup-help
make dev-help
make test-help
make validate-pr
make test-summary
make build
```
