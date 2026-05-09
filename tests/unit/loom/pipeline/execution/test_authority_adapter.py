"""Unit coverage for the internal authority-backed execution adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import (
    OutputSpec,
    PipelineRunner,
    PipelineSpec,
    RunRequest,
    StageFactorySpec,
    StageSpec,
)
from loom.pipeline.execution.authority_adapter import (
    create_authority_backed_serial_run_store,
)
from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus
from loom.pipeline.stores import (
    AuthorityStoreError,
    LocalArtifactStore,
    LocalRunStore,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.pipeline.stores.authority import OutputCommit
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState


class CommitFailingAuthority(SQLitePerRunAuthorityStore):
    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        raise AuthorityStoreError("backend output commit failed")


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _store(tmp_path: Path, authority: PerRunAuthorityStore):
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )


def _submitted_record(run_uri: str) -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="slurm",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1.json",
        summary_counts={"submitted": 1, "active": 1},
    )


def _pipeline() -> PipelineSpec:
    return PipelineSpec(
        stages=(
            StageSpec(
                name="build",
                factory=StageFactorySpec(
                    target_path=(
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                ),
                stage_config={"value": 7},
                outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
            ),
            StageSpec(
                name="report",
                factory=StageFactorySpec(
                    target_path=(
                        "tests.support.pipeline_execution_stages.TextConsumerStage"
                    )
                ),
                inputs={"data": "build.data"},
                outputs={"text": OutputSpec(artifact_type="text", codec_key="text.v1")},
            ),
        )
    )


def test_authority_backed_serial_run_commits_outputs_and_releases_leases(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    assert result.status is RunStatus.SUCCEEDED
    snapshot = authority.snapshot(run_uri)
    assert snapshot.status is RunStatus.SUCCEEDED
    assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
        "build": StageStatus.SUCCEEDED,
        "report": StageStatus.SUCCEEDED,
    }
    assert all(stage.latest_commit is not None for stage in snapshot.stages)
    assert all(stage.artifact_facts for stage in snapshot.stages)
    assert all(stage.active_lease is None for stage in snapshot.stages)
    assert not (tmp_path / "runs" / "run1" / "run.lock").exists()


def test_authority_backed_reads_ignore_conflicting_local_live_state(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    local_store = LocalRunStore(tmp_path / "runs")
    local_store.write_artifact_index(run_uri, {})
    local_store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.FAILED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            message="conflicting local status",
        ),
    )
    fake_ref = ArtifactRef(
        artifact_id="local/conflict",
        uri=f"{run_uri}/artifacts/local/conflict.json",
        artifact_type="json",
    )
    local_store.write_stage_outputs(run_uri, "build", {"data": fake_ref}, attempt=1)

    assert set(run_store.read_artifact_index(run_uri)) == {"build.data", "report.text"}
    status = run_store.read_run_status(run_uri)
    assert status is not None
    assert status.status is RunStatus.SUCCEEDED
    outputs = run_store.read_stage_outputs(run_uri, "build")
    assert outputs is not None
    assert outputs["data"] != fake_ref


def test_authority_backed_run_lock_uses_controller_lease(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)

    lock = run_store.acquire_run_lock(run_uri, owner={"component": "unit-test"})
    try:
        with pytest.raises(AuthorityStoreError, match="active controller lease"):
            run_store.acquire_run_lock(run_uri, owner={"component": "other"})

        observed = run_store.read_run_lock(run_uri)
        assert observed is not None
        assert observed.token == lock.token
        assert not (tmp_path / "runs" / "run1" / "run.lock").exists()
    finally:
        run_store.release_run_lock(run_uri, lock.token)


def test_authority_backed_submitted_operations_ignore_conflicting_local_registry(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    submitted = _submitted_record(run_uri)

    run_store.write_submitted_operation(run_uri, submitted)
    LocalRunStore(tmp_path / "runs").write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="local-conflict",
            mode="batch",
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            state=SubmittedOperationState.FAILED,
            manifest_relative_path="submitted/sub-1.json",
            summary_counts={},
        ),
    )

    assert run_store.read_submitted_operation(run_uri, "sub-1") == submitted
    assert run_store.latest_active_submitted_operation(run_uri) == submitted
    assert authority.snapshot(run_uri).submitted_operations == (submitted,)


def test_authority_backed_worker_request_carries_attempt_fencing_metadata(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    plan = plan_pipeline(
        _pipeline(),
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )

    request = prepare_stage_attempt(
        run_store=run_store,
        run_uri=run_uri,
        stage=_pipeline().get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        metadata={"source": "unit-test"},
        clock=lambda: "2020-01-01T00:00:00Z",
    )

    raw = run_store.read_stage_worker_request(run_uri, "build", attempt=request.attempt)
    assert raw is not None
    metadata = raw["metadata"]
    assert isinstance(metadata, Mapping)
    authority_attempt = metadata["authority_attempt"]
    assert isinstance(authority_attempt, Mapping)
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert build.active_lease is not None
    assert authority_attempt == {
        "attempt_id": build.attempts[0].attempt_id,
        "lease_id": build.active_lease.lease_id,
        "fencing_token": build.active_lease.fencing_token,
        "owner_id": build.active_lease.owner_id,
    }


def test_authority_backed_commit_failure_leaves_no_authoritative_outputs(
    tmp_path: Path,
) -> None:
    authority = CommitFailingAuthority(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "store_commit"
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "outputs.json").is_file()
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert snapshot.status is RunStatus.FAILED
    assert build.status is StageStatus.FAILED
    assert build.latest_commit is None
    assert build.artifact_facts == ()
    assert build.active_lease is None
    assert authority.list_cleanup_candidates(run_uri) == ()


def test_public_local_run_store_still_uses_file_lock(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    assert result.status is RunStatus.SUCCEEDED
    assert run_store.read_run_lock(run_uri) is None
    assert (tmp_path / "runs" / "run1" / "status.json").is_file()
