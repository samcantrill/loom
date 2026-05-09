"""Integration coverage for SQLite-backed materialization read models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    LocalMaterializationRequest,
    LocalRunStore,
    MaterializedRefKind,
    ReadModelWarningCode,
    path_to_run_uri,
    read_authoritative_run,
    read_completed_run_bundle_metadata,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


pytestmark = pytest.mark.integration


@dataclass(slots=True)
class FrozenClock:
    value: str

    def __call__(self) -> str:
        return self.value


def test_sqlite_authoritative_read_reports_materialization_diagnostics(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_uri = path_to_run_uri(run_root)
    output_path = run_root / "artifacts" / "build" / "out.json"
    clock = FrozenClock("2020-01-01T00:00:00Z")
    store = SQLitePerRunAuthorityStore(run_uri, clock=clock)
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=path_to_run_uri(output_path),
                artifact_type="json",
            )
        },
    )

    snapshot = read_authoritative_run(
        SQLitePerRunAuthorityStore(run_uri, clock=clock),
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
        local_paths=LocalRunStore(),
        local_materialization=LocalMaterializationRequest(
            include_config_snapshots=False,
            include_provenance_docs=False,
            include_stage_logs=True,
            include_worker_handoff=True,
        ),
    )

    assert snapshot.stages[0].latest_commit is not None
    assert snapshot.stages[0].latest_commit.output_names == ("out",)
    assert snapshot.stages[0].artifact_facts[0].artifact.uri == path_to_run_uri(
        output_path
    )
    assert {
        ref.kind for ref in snapshot.materialized_refs
    } >= {
        MaterializedRefKind.ARTIFACT_PAYLOAD,
        MaterializedRefKind.STAGE_LOG,
        MaterializedRefKind.WORKER_HANDOFF,
    }
    assert ReadModelWarningCode.MISSING_MATERIALIZED_REF in {
        warning.code for warning in snapshot.warnings
    }


def test_sqlite_completed_bundle_metadata_uses_backend_revision_not_files(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_uri = path_to_run_uri(run_root)
    output_path = run_root / "artifacts" / "build" / "out.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("payload-not-read", encoding="utf-8")
    (run_root / "status.json").write_text('{"status":"FAILED"}', encoding="utf-8")
    clock = FrozenClock("2020-01-01T00:00:00Z")
    store = SQLitePerRunAuthorityStore(run_uri, clock=clock)
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=path_to_run_uri(output_path),
                artifact_type="json",
            )
        },
    )
    store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.SUCCEEDED,
    )

    bundle = read_completed_run_bundle_metadata(
        SQLitePerRunAuthorityStore(run_uri, clock=clock),
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert bundle.status is RunStatus.SUCCEEDED
    assert bundle.materialized_refs[0].exists is True
    assert bundle.warnings == ()


def test_revision_change_during_verified_read_reports_active_run_warning(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    clock = FrozenClock("2020-01-01T00:00:00Z")
    store = SQLitePerRunAuthorityStore(run_uri, clock=clock)
    store.create_run(run_uri)

    class MutatingSnapshotStore(SQLitePerRunAuthorityStore):
        def __init__(self) -> None:
            super().__init__(run_uri, clock=clock)
            self._snapshots = 0

        def snapshot(self, run_uri: str):
            self._snapshots += 1
            result = super().snapshot(run_uri)
            if self._snapshots == 1:
                super().transition_run(
                    run_uri,
                    from_status=RunStatus.CREATED,
                    to_status=RunStatus.RUNNING,
                )
            return result

    snapshot = read_authoritative_run(
        MutatingSnapshotStore(),
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.warnings[-1].code is ReadModelWarningCode.ACTIVE_RUN_CHANGING
