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

Opt in to target readiness checks when the config is trusted project code:

```sh
loom validate pipeline.yaml --check-targets
```

`--check-targets` imports and constructs every `_target_` block after static
validation succeeds, then discards the constructed objects. The command emits a
warning when that consent boundary is crossed.

Preview stage actions without executing or allocating run state:

```sh
loom plan pipeline.yaml --format json
loom plan pipeline.yaml --run-uri file://./runs/example --explain build
```

Run locally through the runtime:

```sh
loom run pipeline.yaml
loom run pipeline.yaml --run-uri file://./runs/example
loom run pipeline.yaml --run-uri file://./runs/example --resume
loom run pipeline.yaml --dry-run --format json
```

If `loom run` is called without `--run-uri`, the local run store allocates a
timestamped run URI under its default root. `loom plan` is read-only and never
allocates a default run URI. `loom run --dry-run` emits the same plan schema as
`loom plan` because no run happened.

Local run commands accept explicit local run URI forms:

```text
file:///absolute/run
file://./relative/run
file://../relative/run
```

Relative run URIs resolve against the current working directory and are displayed
and persisted as absolute `file:///...` URIs. Plain paths, `file://localhost`,
queries, fragments, and non-local schemes are rejected.

## Quickstart (Python API)

```python
from pathlib import Path

from weave import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

run_root = Path("tmp/runs")
config_path = Path("tmp/demo_pipeline.yaml")
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(
    """
pipeline:
  name: demo
  stages:
    - name: build
      factory:
        _target_: tests.support.pipeline_execution_stages.JsonProducerStage
      config:
        value: 1
      outputs:
        data:
          artifact_type: json
          codec_key: json.v1
    - name: report
      factory:
        _target_: tests.support.pipeline_execution_stages.TextConsumerStage
      inputs:
        data: build.data
      outputs:
        text:
          artifact_type: text
          codec_key: text.v1
"""
)
run_store = create_authority_backed_serial_run_store(
    run_root,
    authority_store=SQLitePerRunAuthorityStore(),
)
runner = PipelineRunner(run_store=run_store)
run_uri = path_to_run_uri(run_root / "run1")

composed = compose_config(config_path)
result = runner.run(
    RunRequest(config=composed, run_uri=run_uri)
)
assert result.stage_results["build"].status.name == "SUCCEEDED"
```

## Same-Run Resume

```python
resume = runner.run(
    RunRequest(config=composed, run_uri=run_uri, open_existing=True)
)
assert resume.stage_results["build"].action == "REUSE"
assert resume.stage_results["report"].action == "REUSE"
```

Artifacts from prior stages are reused only when status, fingerprint, and required
outputs match. `RUNNING`, failed, missing, corrupt, or checksum-mismatch state is
not reused.

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
- [examples/README.md](examples/README.md)
- [docs/features/cli.md](docs/features/cli.md)
- [docs/features/config.md](docs/features/config.md)
- [docs/features/testing.md](docs/features/testing.md)
- [docs/structure.md](docs/structure.md)
- [docs/roadmap.md](docs/roadmap.md)

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
