"""Unit coverage for the internal authority-backed execution adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from loom.authority.app import create_authority_app
from loom.authority._repository import initialize_authority_repository
from loom.authority.services import repository_authority_services
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
    AuthorityBackedSerialRunStore,
    AuthorityClientBackedPerRunAuthorityStore,
    create_authority_backed_serial_run_store,
)
from loom.pipeline.execution.continuation import (
    ContinuationStateError,
    StageJobRunRequest,
    run_stage_job,
)
from loom.pipeline.execution.lifecycle import write_run_status, write_stage_submitted
from loom.pipeline.execution.stage_attempts import prepare_stage_attempt
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import (
    ResolvedStageRuntimeOptions,
    RunOptions,
    build_runtime_metadata,
)
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityClient,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityFactoryError,
    AuthorityStoreError,
    LocalArtifactStore,
    LocalRunStore,
    PerRunAuthorityStore,
    path_to_run_uri,
    run_uri_to_path,
)
from loom.pipeline.stores.authority import OutputCommit
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    SubmittedOperationState,
    submitted_stage_metadata,
)
from loom.serialization import PlainData


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


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class _AuthorityRequestKwargs(TypedDict):
    authority_attempt_id: str
    authority_lease_id: str
    authority_owner_id: str
    authority_fencing_token: str


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _store(tmp_path: Path, authority: PerRunAuthorityStore):
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )


def _http_authority_run_store(tmp_path: Path) -> AuthorityBackedSerialRunStore:
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    services = repository_authority_services(
        repository,
        workspace_id="workspace-a",
    )
    app_client = TestClient(create_authority_app(services=services))

    def transport(
        url: str,
        payload: Mapping[str, PlainData],
        _timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        response = app_client.post(urlsplit(url).path, json=payload)
        assert response.status_code == 200
        parsed = response.json()
        assert isinstance(parsed, dict)
        return parsed

    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        endpoint="http://authority.test",
        workspace_id="workspace-a",
        reference_id="test-http-authority",
    )
    assert config.endpoint is not None
    authority_store = AuthorityClientBackedPerRunAuthorityStore(
        client=AuthorityClient(config.endpoint, transport=transport),
        config=config,
        readiness=services.readiness_report,
    )
    return AuthorityBackedSerialRunStore(
        local_store=LocalRunStore(tmp_path / "runs"),
        authority_store=authority_store,
        authority_config=config,
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


def test_authority_backed_store_fails_closed_without_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(AuthorityFactoryError, match="online mutation mode requires"):
        create_authority_backed_serial_run_store(tmp_path / "runs")



def test_authority_backed_store_rejects_removed_transitional_sqlite_config(
    tmp_path: Path,
) -> None:
    with pytest.raises(AuthorityStoreError, match="no longer a supported runtime"):
        create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=AuthorityConfig(
                backend_kind=AuthorityBackendKind.TRANSITIONAL_SQLITE,
            ),
        )


def _single_stage_pipeline() -> PipelineSpec:
    pipeline = _pipeline()
    return PipelineSpec(stages=(pipeline.get_stage("build"),))


def _authority_request_kwargs(
    raw_request: Mapping[str, object],
) -> _AuthorityRequestKwargs:
    metadata = raw_request.get("metadata")
    assert isinstance(metadata, Mapping)
    authority_attempt = metadata.get("authority_attempt")
    assert isinstance(authority_attempt, Mapping)
    return {
        "authority_attempt_id": str(authority_attempt["attempt_id"]),
        "authority_lease_id": str(authority_attempt["lease_id"]),
        "authority_owner_id": str(authority_attempt["owner_id"]),
        "authority_fencing_token": str(authority_attempt["fencing_token"]),
    }


def _prepare_authority_stage_job(
    tmp_path: Path,
    *,
    authority: PerRunAuthorityStore | None = None,
):
    authority = authority or SQLitePerRunAuthorityStore(
        clock=lambda: "2020-01-01T00:00:00Z"
    )
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    spec = _single_stage_pipeline()
    run_store.create_run(run_uri)
    write_run_status(
        run_store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        build_runtime_metadata(
            RunOptions(run_uri=run_uri, executor="local"),
            stage_ids=spec.stage_names,
        ).to_dict(),
    )
    prepare_stage_attempt(
        run_store=run_store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        clock=lambda: "2020-01-01T00:00:02Z",
    )
    raw = run_store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert raw is not None
    return run_store, authority, run_uri, raw


def _mark_authority_build_submitted(
    run_store: AuthorityBackedSerialRunStore, run_uri: str
) -> None:
    raw_request = run_store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert isinstance(raw_request, dict)
    existing_metadata = raw_request.get("metadata")
    assert isinstance(existing_metadata, Mapping)
    record = _submitted_record(run_uri)
    submitted_metadata = submitted_stage_metadata(
        record=record,
        stage_name="build",
        attempt=1,
        continuation_executor="local",
        stage_metadata={"job_key": "build"},
    )
    metadata = {**dict(existing_metadata), **dict(submitted_metadata)}
    run_store.write_submitted_operation(run_uri, record)
    run_store.write_stage_worker_request(
        run_uri,
        "build",
        {**raw_request, "metadata": metadata},
        attempt=1,
    )
    write_stage_submitted(
        run_store,
        run_uri=run_uri,
        stage_name="build",
        attempt=1,
        submitted_at="2020-01-01T00:00:03Z",
        owner={"component": "test-submitter"},
        metadata=metadata,
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


def test_authority_backed_serial_run_executes_through_http_authority_client(
    tmp_path: Path,
) -> None:
    run_store = _http_authority_run_store(tmp_path)
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    assert result.status is RunStatus.SUCCEEDED
    snapshot = run_store.authority_store.snapshot(run_uri)
    assert snapshot.status is RunStatus.SUCCEEDED
    assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
        "build": StageStatus.SUCCEEDED,
        "report": StageStatus.SUCCEEDED,
    }
    assert all(stage.latest_commit is not None for stage in snapshot.stages)
    assert all(stage.active_lease is None for stage in snapshot.stages)
    assert set(run_store.read_artifact_index(run_uri)) == {"build.data", "report.text"}
    assert (run_uri_to_path(run_uri) / "status.json").is_file()


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


def test_authority_backed_reads_ignore_deleted_and_corrupt_legacy_documents(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    run_path = run_uri_to_path(run_uri)
    (run_path / "status.json").unlink()
    (run_path / "artifacts.json").write_text("not json", encoding="utf-8")
    (run_path / "stages" / "build" / "outputs.json").write_text(
        "not json", encoding="utf-8"
    )

    run_status = run_store.read_run_status(run_uri)
    assert run_status is not None
    assert run_status.status is RunStatus.SUCCEEDED
    assert set(run_store.read_artifact_index(run_uri)) == {"build.data", "report.text"}
    outputs = run_store.read_stage_outputs(run_uri, "build")
    assert outputs is not None
    assert set(outputs) == {"data"}


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


def test_authority_backed_submitted_operations_ignore_deleted_local_registry(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    submitted = _submitted_record(run_uri)
    run_store.write_submitted_operation(run_uri, submitted)
    (run_uri_to_path(run_uri) / "submitted_operations" / "sub-1.json").unlink()

    assert run_store.read_submitted_operation(run_uri, "sub-1") == submitted
    assert run_store.list_submitted_operations(run_uri) == (submitted,)


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


def test_authority_backed_stage_job_requires_worker_request_fencing(
    tmp_path: Path,
) -> None:
    run_store, authority, run_uri, raw = _prepare_authority_stage_job(tmp_path)
    unsafe = dict(raw)
    unsafe_metadata = dict(cast(Mapping[str, PlainData], unsafe.get("metadata", {})))
    unsafe_metadata.pop("authority_attempt", None)
    unsafe["metadata"] = cast(PlainData, unsafe_metadata)
    run_store.local_store.write_stage_worker_request(
        run_uri,
        "build",
        unsafe,
        attempt=1,
    )

    with pytest.raises(
        ContinuationStateError,
        match="stage-job request is missing authority fencing facts",
    ):
        run_stage_job(
            run_store=run_store,
            request=StageJobRunRequest(
                run_uri=run_uri,
                stage_name="build",
                executor="local",
            ),
        )

    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert snapshot.status is RunStatus.RUNNING
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None


def test_authority_backed_stage_job_rejects_foreign_fencing(
    tmp_path: Path,
) -> None:
    run_store, authority, run_uri, raw = _prepare_authority_stage_job(tmp_path)
    request_kwargs = _authority_request_kwargs(raw)
    request_kwargs["authority_fencing_token"] = "foreign-token"

    with pytest.raises(ContinuationStateError, match="worker metadata|backend lease"):
        run_stage_job(
            run_store=run_store,
            request=StageJobRunRequest(
                run_uri=run_uri,
                stage_name="build",
                executor="local",
                **request_kwargs,
            ),
        )

    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert snapshot.status is RunStatus.RUNNING
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None


def test_authority_backed_stage_job_rejects_expired_fencing(
    tmp_path: Path,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    authority = SQLitePerRunAuthorityStore(clock=clock)
    run_store, _authority, run_uri, raw = _prepare_authority_stage_job(
        tmp_path,
        authority=authority,
    )
    request_kwargs = _authority_request_kwargs(raw)
    clock.value = "2020-01-02T00:00:01Z"

    with pytest.raises(ContinuationStateError, match="lease has expired"):
        run_stage_job(
            run_store=run_store,
            request=StageJobRunRequest(
                run_uri=run_uri,
                stage_name="build",
                executor="local",
                **request_kwargs,
            ),
        )

    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert snapshot.status is RunStatus.RUNNING
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None


def test_authority_backed_stage_job_commits_attempt_without_run_finalization(
    tmp_path: Path,
) -> None:
    run_store, authority, run_uri, raw = _prepare_authority_stage_job(tmp_path)
    _mark_authority_build_submitted(run_store, run_uri)
    refreshed = run_store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert refreshed is not None
    request_kwargs = _authority_request_kwargs(refreshed or raw)

    result = run_stage_job(
        run_store=run_store,
        request=StageJobRunRequest(
            run_uri=run_uri,
            stage_name="build",
            executor="local",
            **request_kwargs,
        ),
    )

    assert result.status is StageStatus.SUCCEEDED
    assert result.run_status is RunStatus.RUNNING
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert snapshot.status is RunStatus.RUNNING
    assert build.status is StageStatus.SUCCEEDED
    assert build.latest_commit is not None
    assert build.artifact_facts
    assert build.active_lease is None


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
    run_store.create_run(run_uri)

    lock = run_store.acquire_run_lock(
        run_uri,
        owner={"component": "unit-test"},
    )

    assert run_store.read_run_lock(run_uri) == lock
    assert (tmp_path / "runs" / "run1" / "lock.json").is_file()
    run_store.release_run_lock(run_uri, lock.token)
    assert run_store.read_run_lock(run_uri) is None
    assert not (tmp_path / "runs" / "run1" / "lock.json").exists()
