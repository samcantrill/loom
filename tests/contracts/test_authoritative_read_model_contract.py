"""Contract tests for backend-neutral authoritative materialization reads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_text
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    MaterializedRefKind,
    PerRunAuthorityStore,
    ReadModelWarningCode,
    path_to_run_uri,
    read_authoritative_run,
    read_completed_run_bundle_metadata,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


pytestmark = pytest.mark.contract


@dataclass(frozen=True, slots=True)
class ReadModelCase:
    store: PerRunAuthorityStore
    run_uri: str
    output_path: Path


@pytest.fixture(params=["in-memory", "sqlite"])
def read_model_case(request: pytest.FixtureRequest, tmp_path: Path) -> ReadModelCase:
    run_root = tmp_path / request.param / "run"
    run_uri = path_to_run_uri(run_root)
    output_path = run_root / "artifacts" / "build" / "out.json"
    if request.param == "in-memory":
        store: PerRunAuthorityStore = InMemoryPerRunAuthorityStore()
    else:
        store = SQLitePerRunAuthorityStore(
            run_uri,
            clock=lambda: "2020-01-01T00:00:00Z",
        )
    return ReadModelCase(store=store, run_uri=run_uri, output_path=output_path)


def _submitted_record(run_uri: str) -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="subprocess",
        mode="local",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1.json",
        summary_counts={"submitted": 1},
    )


def _populate(
    case: ReadModelCase,
    *,
    materialize_output: bool,
    checksum: str | None = None,
) -> None:
    case.store.create_run(case.run_uri)
    case.store.write_submitted_operation(case.run_uri, _submitted_record(case.run_uri))
    allocation = case.store.allocate_stage_attempt(
        case.run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    if materialize_output:
        case.output_path.parent.mkdir(parents=True, exist_ok=True)
        case.output_path.write_text("payload-not-read", encoding="utf-8")
    case.store.record_output_commit(
        case.run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=path_to_run_uri(case.output_path),
                artifact_type="json",
                checksum=checksum,
            )
        },
    )


def test_authoritative_read_contract_carries_backend_facts_and_materialized_refs(
    read_model_case: ReadModelCase,
) -> None:
    _populate(read_model_case, materialize_output=True)
    read_model_case.store.transition_run(
        read_model_case.run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.SUCCEEDED,
    )

    snapshot = read_authoritative_run(
        read_model_case.store,
        read_model_case.run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.status is RunStatus.SUCCEEDED
    assert snapshot.schema_version == 1
    assert snapshot.revision.sequence >= 1
    assert snapshot.submitted_operations[0].submission_id == "sub-1"
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].attempts[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit is not None
    assert snapshot.stages[0].artifact_facts[0].artifact_name == "out"
    assert snapshot.materialized_refs[0].kind is MaterializedRefKind.ARTIFACT_PAYLOAD
    assert snapshot.materialized_refs[0].exists is True
    assert snapshot.warnings == ()

    bundle = read_completed_run_bundle_metadata(
        read_model_case.store,
        read_model_case.run_uri,
    )
    assert bundle.artifact_facts[0] == snapshot.stages[0].artifact_facts[0]
    assert bundle.materialized_refs[0].kind is MaterializedRefKind.ARTIFACT_PAYLOAD


def test_authoritative_read_contract_warns_for_missing_materialization(
    read_model_case: ReadModelCase,
) -> None:
    _populate(read_model_case, materialize_output=False)

    snapshot = read_authoritative_run(
        read_model_case.store,
        read_model_case.run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.materialized_refs[0].exists is False
    assert snapshot.warnings[0].code is ReadModelWarningCode.MISSING_MATERIALIZED_REF


def test_authoritative_read_contract_warns_for_corrupt_materialization(
    read_model_case: ReadModelCase,
) -> None:
    _populate(
        read_model_case,
        materialize_output=True,
        checksum=hash_text("expected-payload"),
    )

    snapshot = read_authoritative_run(
        read_model_case.store,
        read_model_case.run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.materialized_refs[0].exists is True
    assert snapshot.warnings[0].code is ReadModelWarningCode.CORRUPT_MATERIALIZED_REF
    assert snapshot.warnings[0].detail["reason"] == "checksum_mismatch"
