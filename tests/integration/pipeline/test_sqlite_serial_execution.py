"""SQLite-backed serial execution write-path integration tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution.authority_adapter import (
    create_authority_backed_serial_run_store,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    AuthorityStoreError,
    LocalMaterializationRequest,
    LocalRunStore,
    PerRunAuthorityStore,
    read_authoritative_run,
    path_to_run_uri,
)
from loom.pipeline.stores.authority import OutputCommit
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.pipeline_execution_configs import local_execution_config

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


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


def _store(
    tmp_path: Path,
    authority: PerRunAuthorityStore | None = None,
):
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority
        or SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z"),
    )


def test_sqlite_backed_serial_run_writes_authoritative_success_facts(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )

    assert result.status is RunStatus.SUCCEEDED
    snapshot = read_authoritative_run(
        authority,
        run_uri,
        options=AuthoritativeReadOptions(
            include_materialized_refs=True,
            verify_materialization=True,
        ),
        local_paths=run_store,
        local_materialization=LocalMaterializationRequest(),
    )
    assert snapshot.status is RunStatus.SUCCEEDED
    assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
        "build": StageStatus.SUCCEEDED,
        "report": StageStatus.SUCCEEDED,
    }
    assert all(stage.latest_commit is not None for stage in snapshot.stages)
    assert {
        f"{stage.stage_name}.{fact.artifact_name}"
        for stage in snapshot.stages
        for fact in stage.artifact_facts
    } == {"build.data", "report.text"}
    assert all(stage.active_lease is None for stage in snapshot.stages)
    assert not (tmp_path / "runs" / "run1" / "run.lock").exists()
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "outputs.json").is_file()
    assert any(ref.kind.value == "config" for ref in snapshot.materialized_refs)
    assert any(ref.kind.value == "provenance" for ref in snapshot.materialized_refs)


def test_sqlite_backed_reads_ignore_conflicting_local_live_state(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=run_store).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )

    LocalRunStore(tmp_path / "runs").write_artifact_index(run_uri, {})

    assert set(run_store.read_artifact_index(run_uri)) == {"build.data", "report.text"}
    assert run_store.read_run_status(run_uri).status is RunStatus.SUCCEEDED  # type: ignore[union-attr]
    snapshot = authority.snapshot(run_uri)
    assert snapshot.status is RunStatus.SUCCEEDED
    assert snapshot.stages[0].artifact_facts


def test_sqlite_backed_commit_failure_does_not_publish_active_outputs(
    tmp_path: Path,
) -> None:
    authority = CommitFailingAuthority(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
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
