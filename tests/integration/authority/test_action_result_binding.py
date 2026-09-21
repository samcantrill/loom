"""Consumer projections preserve native producer facts through both authorities."""

from dataclasses import replace
import sqlite3

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
)
from loom.pipeline.stores.read_models import (
    ActionResultBinding,
    AuthoritativeRunSnapshot,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.integration.authority.test_coordinator_authority_api import (
    _authority_factory,
)


pytestmark = pytest.mark.integration


def _producer(tmp_path):
    uri = (tmp_path / "original").as_uri()
    store = SQLitePerRunAuthorityStore(uri)
    store.create_run(uri)
    attempt = store.allocate_stage_attempt(
        uri, "original", owner_id="worker", lease_ttl_seconds=300
    )
    assert attempt.lease is not None
    committed = store.record_output_commit(
        uri,
        "original",
        attempt_id=attempt.attempt.attempt_id,
        fencing_token=attempt.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="original/out", uri=uri + "/out", artifact_type="text"
            )
        },
    )
    binding = ActionResultBinding(
        claim_id="claim-a",
        execution_key="sha256:" + "a" * 64,
        commit=committed.commit,
        artifact_facts=committed.artifact_facts,
        verification={
            "schema_version": 1,
            "candidate_digest": "sha256:" + "b" * 64,
            "verdict": "verified",
        },
    )
    return store, binding


def _consumer(tmp_path, backend):
    uri = (tmp_path / "consumer").as_uri()
    if backend == "embedded":
        authority = SQLitePerRunAuthorityStore(uri)
        authority.create_run(uri, status=RunStatus.PLANNED)
        database = tmp_path / "consumer" / ".loom" / "authority.sqlite3"
        tables = "attempts", "commits"
    else:
        repository, factory = _authority_factory(tmp_path)
        repository.admit_run(uri)
        authority = factory(uri)
        database = repository.database_path
        tables = "stage_attempts", "output_commits"
    authority.bind_coordinator_admission(
        uri,
        CoordinatorAdmissionRequest(
            operation_id="admit-consumer",
            coordinator_id="coordinator",
            run_uri=uri,
            intent_digest="intent",
        ),
    )
    return uri, authority, database, tables


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_binding_projects_original_commit_without_new_attempt_or_commit(
    tmp_path, backend
):
    producer, binding = _producer(tmp_path)
    before = producer.open_run(binding.commit.run_uri)
    uri, authority, database, tables = _consumer(tmp_path, backend)
    revision = authority.bind_action_result(
        uri,
        "renamed-consumer",
        binding,
        expected_revision=authority.open_run(uri).revision,
    )
    assert authority.bind_action_result(uri, "renamed-consumer", binding) == revision
    snapshot = authority.open_run(uri)
    (stage,) = snapshot.stages
    assert stage.stage_name == "renamed-consumer"
    assert stage.status is StageStatus.SUCCEEDED
    assert stage.attempts == ()
    assert stage.latest_commit == binding.commit
    assert stage.artifact_facts == binding.artifact_facts
    assert stage.result_binding == binding
    assert AuthoritativeRunSnapshot.from_dict(snapshot.to_dict()) == snapshot
    with sqlite3.connect(database) as conn:
        for table in tables:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert producer.open_run(binding.commit.run_uri) == before
    with pytest.raises(ValueError, match="binding conflicts"):
        authority.bind_action_result(
            uri, "renamed-consumer", replace(binding, claim_id="different")
        )


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_binding_cannot_cross_cancellation_barrier(tmp_path, backend):
    _, binding = _producer(tmp_path)
    uri, authority, _, _ = _consumer(tmp_path, backend)
    authority.install_cancellation_epoch(
        uri,
        CancellationEpochRequest(
            operation_id="cancel-consumer",
            coordinator_id="coordinator",
            run_uri=uri,
            stage_names=("consumer",),
        ),
    )
    with pytest.raises(ValueError, match="cancellation epoch"):
        authority.bind_action_result(uri, "consumer", binding)


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_new_downstream_attempt_binds_the_original_reused_upstream_commit(
    tmp_path, backend
):
    from loom.pipeline.stores.authority import PreparedAttemptRequest

    _, binding = _producer(tmp_path)
    uri, authority, _, _ = _consumer(tmp_path, backend)
    authority.bind_action_result(uri, "reused", binding)
    receipt = authority.ensure_prepared_attempt(
        uri,
        PreparedAttemptRequest(
            operation_id="prepare-downstream",
            request_digest="downstream-digest",
            admission_id="admit-consumer",
            stage_name="new-prediction",
            readiness_generation="downstream-ready",
            expected_revision=authority.open_run(uri).revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan",
            bound_inputs={},
            upstream_commits={"reused": binding.commit.commit_id},
        ),
    )
    authority.bind_prepared_attempt(
        uri,
        assignment_id="downstream-assignment",
        attempt_id=receipt.attempt.attempt_id,
    )
    assert (
        authority.grant_prepared_attempt(
            uri,
            assignment_id="downstream-assignment",
            attempt_id=receipt.attempt.attempt_id,
        ).attempt_id
        == receipt.attempt.attempt_id
    )
