"""Integration coverage for sweep collection over local run materialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    collect_sweep_results,
    plan_sweep,
    write_sweep_plan,
)


pytestmark = pytest.mark.integration


def test_collect_sweep_results_reads_local_run_status_and_artifact_refs(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_uri = path_to_run_uri(run_root / "trial-0001")
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="collection-integration",
            run_uri_root=path_to_run_uri(run_root),
            trials=(ManualTrialSpec(overrides={"pipeline.name": "integration"}),),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    write_sweep_plan(plan, tmp_path / "sweep")
    store = LocalRunStore(run_root)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:00:01Z",
        ),
    )
    store.write_artifact_index(
        run_uri,
        {
            "build.data": ArtifactRef(
                artifact_id="build/data",
                uri=f"{run_uri}/artifacts/build/data.json",
                artifact_type="json",
            )
        },
    )

    result = collect_sweep_results(
        plan,
        run_status_reader=store.read_run_status,
        artifact_reader=store.read_artifact_index,
        collected_at="2026-05-14T00:00:02Z",
    )

    assert result.trial_count == 1
    assert result.artifact_count == 1
    assert result.trials[0].status.outcome.value == "succeeded"
    assert result.trials[0].artifacts[0].artifact_id == "build/data"
