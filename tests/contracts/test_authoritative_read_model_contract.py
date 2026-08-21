"""Contract tests for backend-neutral authoritative materialization reads."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_text
from loom.pipeline.reliability import (
    FailureClassification,
    ReliabilityPolicy,
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    RetryPolicy,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import (
    AUTHORITY_SCHEMA_VERSION,
    AuthoritativeReadOptions,
    MaterializedRefKind,
    PerRunAuthorityStore,
    ReadModelWarningCode,
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
    path_to_run_uri,
    read_authoritative_run,
    read_completed_run_bundle_metadata,
)
from loom.pipeline.stores.service_authority import (
    LocalAuthorityService,
    create_service_authority_store,
)
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


pytestmark = pytest.mark.contract


@dataclass(frozen=True, slots=True)
class ReadModelCase:
    store: PerRunAuthorityStore
    run_uri: str
    output_path: Path


@pytest.fixture(params=["in-memory", "service"])
def read_model_case(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[ReadModelCase]:
    run_root = tmp_path / request.param / "run"
    run_uri = path_to_run_uri(run_root)
    output_path = run_root / "artifacts" / "build" / "out.json"
    if request.param == "in-memory":
        yield ReadModelCase(
            store=InMemoryPerRunAuthorityStore(),
            run_uri=run_uri,
            output_path=output_path,
        )
        return
    with LocalAuthorityService.start() as service:
        yield ReadModelCase(
            store=create_service_authority_store(service.config()),
            run_uri=run_uri,
            output_path=output_path,
        )


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


def _reliability_status(run_uri: str) -> ReliabilityStatusDetail:
    return ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=RunStatus.RUNNING,
        stage_id="build",
        stage_status=StageStatus.FAILED,
        attempt=1,
        created_at="2020-01-01T00:00:00Z",
    )


def _write_reliability_facts(case: ReadModelCase) -> None:
    status = _reliability_status(case.run_uri)
    failure = FailureClassification(
        reason_code="runtime_error",
        status=status,
        retriable=True,
    )
    case.store.write_reliability_policy_fact(
        case.run_uri,
        ReliabilityPolicyFact(
            run_uri=case.run_uri,
            scope=ReliabilityPolicyScope.STAGE,
            stage_name="build",
            recorded_at="2020-01-01T00:00:00Z",
            policy=ReliabilityPolicy(retry=RetryPolicy(enabled=True, max_attempts=2)),
        ),
    )
    case.store.write_reliability_status_detail(case.run_uri, status)
    case.store.write_stage_attempt_transaction(
        case.run_uri,
        StageAttemptTransaction(
            transaction_id="tx-1",
            run_uri=case.run_uri,
            stage_id="build",
            attempt=1,
            status=status,
        ),
    )
    case.store.write_retry_decision(
        case.run_uri,
        RetryDecisionRecord(
            decision_id="retry-1",
            transaction_id="tx-1",
            should_retry=True,
            next_attempt=2,
            decision_reason="policy_allows_retry",
            policy_max_attempts=2,
            attempt_count=1,
            status=status,
            failure=failure,
        ),
    )
    case.store.write_timeout_outcome(
        case.run_uri,
        TimeoutOutcomeRecord(
            outcome_id="timeout-1",
            transaction_id="tx-1",
            timed_out=False,
            duration_seconds=1,
            reason_code="completed",
            status=status,
            causal_decision_id="retry-1",
        ),
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
        to_status=RunStatus.RUNNING,
    )
    read_model_case.store.transition_run(
        read_model_case.run_uri,
        from_status=RunStatus.RUNNING,
        to_status=RunStatus.SUCCEEDED,
    )

    snapshot = read_authoritative_run(
        read_model_case.store,
        read_model_case.run_uri,
        options=AuthoritativeReadOptions(verify_materialization=True),
    )

    assert snapshot.status is RunStatus.SUCCEEDED
    assert snapshot.schema_version == AUTHORITY_SCHEMA_VERSION
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


def test_authoritative_read_contract_carries_reliability_facts(
    read_model_case: ReadModelCase,
) -> None:
    _populate(read_model_case, materialize_output=True)
    _write_reliability_facts(read_model_case)

    snapshot = read_authoritative_run(read_model_case.store, read_model_case.run_uri)
    stage = snapshot.stages[0]

    assert stage.reliability_policy_facts[0].stage_name == "build"
    assert stage.reliability_status_details[0].stage_id == "build"
    assert stage.reliability_transactions[0].transaction_id == "tx-1"
    assert stage.retry_decisions[0].decision_id == "retry-1"
    assert stage.timeout_outcomes[0].outcome_id == "timeout-1"
    assert snapshot.reliability_policy_facts == ()
    assert read_model_case.store.read_transaction_chain(
        read_model_case.run_uri,
        "tx-1",
    ) == stage.reliability_transactions


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
