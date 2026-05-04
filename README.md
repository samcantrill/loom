# Loom

`loom` is a lightweight, generic runtime for composing, configuring, running, and
resuming small Python pipelines.

The v0 implementation is deliberately local-only:

- trusted config composition, recipe expansion, and `_target_` construction
- local artifact + run stores on disk
- deterministic planning with conservative same-run resume
- local in-process execution
- error messages with path-oriented context
- import-safe boundaries between config, pipeline, execution, and CLI stub modules

## Quickstart (Python API)

```python
from pathlib import Path

from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import LocalRunStore

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
run_store = LocalRunStore(run_root)
runner = PipelineRunner(run_store=run_store)

composed = compose_config(config_path)
result = runner.run(
    RunRequest(config=composed.resolved, run_id="run1")
)
assert result.stage_results["build"].status.name == "SUCCEEDED"
```

## Same-Run Resume

```python
resume = runner.run(
    RunRequest(config=composed.resolved, run_id="run1", open_existing=True)
)
assert resume.stage_results["build"].action == "REUSE"
assert resume.stage_results["report"].action == "REUSE"
```

Artifacts from prior stages are reused only when status, fingerprint, and required
outputs match. `RUNNING`, failed, missing, corrupt, or checksum-mismatch state is
not reused.

## Run Directory Layout

Successful runs are materialized as:

```text
runs/RUN_ID/
  run.json
  status.json
  plan.json
  artifacts.json

  config/
    raw.yaml
    resolved.yaml
    resolved.redacted.yaml
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
- [docs/features/config.md](docs/features/config.md)
- [docs/structure.md](docs/structure.md)
- [implementation-plan-v0.md](docs/implementation-plans/implementation-plan-v0.md)
- [v0 public API migration notes](docs/briefs/v0_public_api_migration_notes.md)

## Development

```sh
uv sync --all-groups
make validate-pr
make test-summary
make build
```
