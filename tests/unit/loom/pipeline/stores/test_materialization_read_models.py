"""Unit tests for authoritative materialization read helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_text
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    BackendRevision,
    LocalMaterializationRequest,
    LocalRunStore,
    MaterializationReadModelError,
    MaterializedRef,
    MaterializedRefKind,
    ReadModelWarningCode,
    path_to_run_uri,
    read_authoritative_run,
    read_completed_run_bundle_metadata,
)
from loom.pipeline.stores.schema_policy import (
    AuthoritySchemaCheck,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
)
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


pytestmark = pytest.mark.unit


def _committed_store(
    run_uri: str,
    output_path: Path,
    *,
    checksum: str | None = None,
) -> InMemoryPerRunAuthorityStore:
    store = InMemoryPerRunAuthorityStore()
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
                checksum=checksum,
            )
        },
    )
    return store


def test_authoritative_read_derives_payload_refs_without_loading_payloads(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    output_path = run_root / "artifacts" / "build" / "out.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("{not-json-but-not-read}", encoding="utf-8")
    run_uri = path_to_run_uri(run_root)
    store = _committed_store(run_uri, output_path)

    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    latest_commit = snapshot.stages[0].latest_commit
    assert latest_commit is not None
    assert snapshot.materialized_refs == (
        MaterializedRef(
            kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
            uri=path_to_run_uri(output_path),
            exists=True,
            metadata={
                "artifact_name": "out",
                "artifact_id": "build/out",
                "artifact_type": "json",
                "commit_id": latest_commit.commit_id,
            },
        ),
    )
    assert latest_commit.materialized_refs == (
        snapshot.materialized_refs[0],
    )
    assert snapshot.warnings == ()


def test_missing_materialized_refs_warn_or_raise_in_strict_mode(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    output_path = run_root / "artifacts" / "build" / "missing.json"
    run_uri = path_to_run_uri(run_root)
    store = _committed_store(run_uri, output_path)

    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.materialized_refs[0].exists is False
    assert [warning.code for warning in snapshot.warnings] == [
        ReadModelWarningCode.MISSING_MATERIALIZED_REF
    ]

    with pytest.raises(MaterializationReadModelError) as exc_info:
        read_authoritative_run(
            store,
            run_uri,
            options=AuthoritativeReadOptions(
                verify_materialization=True,
                strict=True,
            ),
        )

    assert exc_info.value.warnings[0].code is ReadModelWarningCode.MISSING_MATERIALIZED_REF


def test_corrupt_materialized_refs_warn_or_raise_in_strict_mode(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    output_path = run_root / "artifacts" / "build" / "out.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("actual-payload", encoding="utf-8")
    run_uri = path_to_run_uri(run_root)
    expected_checksum = hash_text("expected-payload")
    store = _committed_store(run_uri, output_path, checksum=expected_checksum)

    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    warning = snapshot.warnings[0]
    assert warning.code is ReadModelWarningCode.CORRUPT_MATERIALIZED_REF
    assert warning.detail["reason"] == "checksum_mismatch"
    assert warning.detail["expected_checksum"] == expected_checksum
    assert warning.detail["actual_checksum"] == hash_text("actual-payload")
    assert snapshot.materialized_refs[0].exists is True

    with pytest.raises(MaterializationReadModelError) as exc_info:
        read_authoritative_run(
            store,
            run_uri,
            options=AuthoritativeReadOptions(
                verify_materialization=True,
                strict=True,
            ),
        )

    assert (
        exc_info.value.warnings[0].code
        is ReadModelWarningCode.CORRUPT_MATERIALIZED_REF
    )


def test_local_materialization_helpers_classify_expected_refs(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_uri = path_to_run_uri(run_root)
    log_path = run_root / "stages" / "build" / "logs" / "stdout.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("log", encoding="utf-8")
    store = _committed_store(run_uri, run_root / "artifacts" / "build" / "out.json")

    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
        local_paths=LocalRunStore(),
        local_materialization=LocalMaterializationRequest(
            include_config_snapshots=False,
            include_provenance_docs=False,
            include_stage_logs=True,
            include_worker_handoff=False,
        ),
    )

    refs = {
        (ref.kind, ref.metadata.get("stream")): ref for ref in snapshot.materialized_refs
    }
    assert refs[(MaterializedRefKind.STAGE_LOG, "stdout")].exists is True
    assert refs[(MaterializedRefKind.STAGE_LOG, "stderr")].exists is False
    assert ReadModelWarningCode.MISSING_MATERIALIZED_REF in {
        warning.code for warning in snapshot.warnings
    }


def test_completed_bundle_metadata_is_payload_free_and_completed_run_checked(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = _committed_store(run_uri, tmp_path / "run" / "artifacts" / "build" / "out.json")
    store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.SUCCEEDED,
    )

    bundle = read_completed_run_bundle_metadata(store, run_uri)

    assert bundle.status is RunStatus.SUCCEEDED
    assert bundle.artifact_facts[0].artifact_name == "out"
    assert bundle.materialized_refs[0].kind is MaterializedRefKind.ARTIFACT_PAYLOAD
    assert "artifact_facts" in bundle.to_dict()


def test_completed_bundle_metadata_warns_for_active_run(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = _committed_store(run_uri, tmp_path / "run" / "artifacts" / "build" / "out.json")

    bundle = read_completed_run_bundle_metadata(store, run_uri)

    assert bundle.warnings[-1].code is ReadModelWarningCode.ACTIVE_RUN_CHANGING


def test_projection_revision_and_schema_failures_are_warnings(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    store = _committed_store(run_uri, tmp_path / "run" / "artifacts" / "build" / "out.json")
    stale_revision = BackendRevision(sequence=1, token="rev-1")

    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=AuthoritativeReadOptions(projection_revision=stale_revision),
    )

    assert ReadModelWarningCode.STALE_PROJECTION in {
        warning.code for warning in snapshot.warnings
    }


def test_schema_failure_can_be_reported_without_becoming_state_truth(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "run")
    base = _committed_store(run_uri, tmp_path / "run" / "artifacts" / "build" / "out.json")

    class WarningOnlySchemaStore(InMemoryPerRunAuthorityStore):
        def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
            assert run_uri
            return AuthoritySchemaCheck(
                found_version=2,
                failure=AuthoritySchemaFailure(
                    kind=AuthoritySchemaFailureKind.UNSUPPORTED_NEWER,
                    message="newer schema",
                    found_version=2,
                ),
            )

    warning_store = WarningOnlySchemaStore()
    warning_store._runs = base._runs  # type: ignore[attr-defined]
    warning_store._revision = base._revision  # type: ignore[attr-defined]

    snapshot = read_authoritative_run(warning_store, run_uri)

    assert snapshot.warnings[0].code is ReadModelWarningCode.UNSUPPORTED_SCHEMA


def test_legacy_status_files_do_not_override_backend_truth(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_uri = path_to_run_uri(run_root)
    store = _committed_store(run_uri, run_root / "artifacts" / "build" / "out.json")
    (run_root / "status.json").parent.mkdir(parents=True, exist_ok=True)
    (run_root / "status.json").write_text('{"status":"FAILED"}', encoding="utf-8")

    snapshot = read_authoritative_run(store, run_uri)

    assert snapshot.status is RunStatus.CREATED
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
