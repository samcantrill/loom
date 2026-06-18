"""Integration coverage for the local service authority backend."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import create_run_store, path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService

pytestmark = pytest.mark.integration


def test_service_backend_admits_runs_through_separate_clients(
    tmp_path: Path,
) -> None:
    with LocalAuthorityService.start() as service:
        config = service.config()

        def admit(index: int) -> str:
            run_uri = path_to_run_uri(tmp_path / "runs" / f"run-{index}")
            store = create_run_store(config)
            store.admit_run(run_uri)
            store.transition_run(
                run_uri,
                from_status=RunStatus.CREATED,
                to_status=RunStatus.RUNNING,
            )
            return run_uri

        with ThreadPoolExecutor(max_workers=4) as pool:
            run_uris = tuple(pool.map(admit, range(12)))

        reader = create_run_store(config)
        assert service.health()["runs"] == 12
        assert all(
            reader.open_run(run_uri).status is RunStatus.RUNNING
            for run_uri in run_uris
        )


def test_service_backend_mutates_stages_through_separate_clients(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "shared")
    with LocalAuthorityService.start() as service:
        config = service.config()
        create_run_store(config).admit_run(run_uri)

        def complete_stage(stage_name: str) -> str:
            store = create_run_store(config)
            stage = store.stage_store(run_uri, stage_name)
            stage.transition(from_status=None, to_status=StageStatus.PENDING)
            allocation = stage.allocate_attempt(
                owner_id=f"worker-{stage_name}",
                lease_ttl_seconds=60,
            )
            assert allocation.lease is not None
            stage.record_output_commit(
                attempt_id=allocation.attempt.attempt_id,
                fencing_token=allocation.lease.fencing_token,
                outputs={
                    "out": ArtifactRef(
                        artifact_id=f"{stage_name}/out",
                        uri=f"{run_uri}/artifacts/{stage_name}/out.json",
                        artifact_type="json",
                    )
                },
            )
            return stage_name

        with ThreadPoolExecutor(max_workers=3) as pool:
            assert set(pool.map(complete_stage, ("a", "b", "c"))) == {"a", "b", "c"}

        snapshot = create_run_store(config).snapshot(run_uri)
        assert {stage.stage_name for stage in snapshot.stages} == {"a", "b", "c"}
        assert all(stage.status is StageStatus.SUCCEEDED for stage in snapshot.stages)
        assert all(stage.latest_commit is not None for stage in snapshot.stages)
