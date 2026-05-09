"""Unit coverage for the internal authority-backed execution adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

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
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityStoreError,
    LocalRunStore,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.pipeline.stores.authority import OutputCommit
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


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


def test_authority_backed_reads_ignore_conflicting_local_artifact_index(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )

    LocalRunStore(tmp_path / "runs").write_artifact_index(run_uri, {})

    assert set(run_store.read_artifact_index(run_uri)) == {"build.data", "report.text"}
    status = run_store.read_run_status(run_uri)
    assert status is not None
    assert status.status is RunStatus.SUCCEEDED


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
