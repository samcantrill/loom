"""Prepare one stage attempt and execute it through ``loom stage run``."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json
from examples.support import started_authority_session
from weave import compose_config
from loom.pipeline import validate_pipeline_config
from loom.pipeline.execution import (
    create_authority_backed_serial_run_store,
    prepare_stage_attempt,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.stores import (
    LocalArtifactStore,
    path_to_run_uri,
)


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"direct-worker-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"
    with started_authority_session(output_root) as authority:
        store = create_authority_backed_serial_run_store(
            run_root,
            authority_config=authority.authority_config,
        )
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
            resolved_runtime=ResolvedStageRuntimeOptions(
                stage_id="seed",
                executor="local",
            ),
        )

        worker = _run_cli(
            [
                "stage",
                "run",
                "--run-uri",
                run_uri,
                "--stage",
                "seed",
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        result = worker["result"]
        parent_outputs_persisted = (
            store.read_stage_outputs(run_uri, "seed") is not None
        )

    print(f"run_uri: {run_uri}")
    print(f"worker_status: {result['status']}")
    print(f"worker_output_count: {len(result['outputs'])}")
    print(f"parent_outputs_persisted: {parent_outputs_persisted}")


def _configure_import_path() -> None:
    sys.path.insert(0, str(HERE))


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
