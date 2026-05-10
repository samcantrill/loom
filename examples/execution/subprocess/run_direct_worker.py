"""Prepare one stage attempt and execute it through ``loom stage run``."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from loom.cli.main import main as loom_main
from loom.config import compose_config
from loom.pipeline import validate_pipeline_config
from loom.pipeline.execution import (
    create_authority_backed_serial_run_store,
    prepare_stage_attempt,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.stores import LocalArtifactStore, path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"direct-worker-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"
    store = create_authority_backed_serial_run_store(run_root)
    store.create_run(run_uri)
    validation = validate_pipeline_config(compose_config(config_path).resolved)
    artifact_store = LocalArtifactStore(store.local_artifact_root(run_uri))
    plan = plan_pipeline(
        validation.spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=artifact_store,
        persist=True,
    )
    stage = validation.spec.get_stage("seed")
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=stage,
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(stage_id="seed", executor="local"),
    )

    worker = _run_cli(
        [
            "stage",
            "run",
            "--run-uri",
            run_uri,
            "--stage",
            "seed",
            "--format",
            "json",
        ]
    )
    result = worker["result"]

    print(f"run_uri: {run_uri}")
    print(f"worker_status: {result['status']}")
    print(f"worker_output_count: {len(result['outputs'])}")
    print(f"parent_outputs_persisted: {store.read_stage_outputs(run_uri, 'seed') is not None}")


def _configure_import_path() -> None:
    sys.path.insert(0, str(HERE))


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    return json.loads(stdout.getvalue())


if __name__ == "__main__":
    main()
