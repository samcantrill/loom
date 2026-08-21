"""Unit tests for private authority repository run lifecycle behavior."""

from __future__ import annotations

import pytest

from loom.pipeline.status import RunStatus
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.stores.read_models import BackendRevision, LeaseState
from loom.authority._repository import (
    AUTHORITY_REPOSITORY_SCHEMA_VERSION,
    AuthorityRepositoryError,
    initialize_authority_repository,
)


pytestmark = pytest.mark.unit

RUN_URI = "file:///runs/unit-r1"


def test_repository_schema_version_includes_output_supersession() -> None:
    assert AUTHORITY_REPOSITORY_SCHEMA_VERSION == 4


def test_admit_run_rejects_duplicate_and_returns_revision(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )

    revision = repository.admit_run(RUN_URI, metadata={"source": "unit"})

    assert revision.sequence == 1
    snapshot = repository.open_run(RUN_URI)
    assert snapshot.status is RunStatus.CREATED
    assert snapshot.revision == revision
    assert snapshot.stages == ()

    with pytest.raises(AuthorityRepositoryError, match="run already exists"):
        repository.admit_run(RUN_URI)


def test_transition_run_rejects_stale_status_and_revision(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    initial = repository.admit_run(RUN_URI)

    transition = repository.transition_run(
        RUN_URI,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
        expected_revision=initial,
    )

    assert transition.previous_status is RunStatus.CREATED
    assert transition.status is RunStatus.RUNNING
    assert transition.revision.sequence > initial.sequence

    with pytest.raises(AuthorityRepositoryError, match="stale run transition"):
        repository.transition_run(
            RUN_URI,
            from_status=RunStatus.CREATED,
            to_status=RunStatus.SUCCEEDED,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale run revision"):
        repository.transition_run(
            RUN_URI,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
            expected_revision=initial,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale run revision"):
        repository.transition_run(
            RUN_URI,
            from_status=RunStatus.RUNNING,
            to_status=RunStatus.SUCCEEDED,
            expected_revision=BackendRevision(sequence=999, token="missing"),
        )


def test_append_event_retries_by_id_before_revision_validation(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    initial = repository.admit_run(RUN_URI)
    event = PipelineEvent(
        event_id="event-1",
        scope=EventScope.run(),
        event_type="run.started",
        timestamp="2020-01-01T00:00:00Z",
    )

    record = repository.append_audit_event(RUN_URI, event, expected_revision=initial)
    assert (
        repository.append_audit_event(RUN_URI, event, expected_revision=initial)
        == record
    )
    with pytest.raises(AuthorityRepositoryError, match="conflicts"):
        repository.append_audit_event(
            RUN_URI,
            PipelineEvent(
                event_id="event-1",
                scope=EventScope.run(),
                event_type="run.failed",
                timestamp="2020-01-01T00:00:00Z",
            ),
            expected_revision=initial,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale run revision"):
        repository.append_audit_event(
            RUN_URI,
            PipelineEvent(
                event_id="event-2",
                scope=EventScope.run(),
                event_type="run.finished",
                timestamp="2020-01-01T00:00:00Z",
            ),
            expected_revision=initial,
        )


def test_controller_lease_rejects_active_conflict_and_bad_fence(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    revision = repository.admit_run(RUN_URI)

    lease = repository.acquire_controller_lease(
        RUN_URI,
        owner_id="controller-1",
        lease_ttl_seconds=30,
        expected_revision=revision,
    )

    assert lease.kind.value == "controller"
    assert lease.state is LeaseState.ACTIVE
    assert lease.run_uri == RUN_URI

    with pytest.raises(AuthorityRepositoryError, match="active controller lease"):
        repository.acquire_controller_lease(
            RUN_URI,
            owner_id="controller-2",
            lease_ttl_seconds=30,
        )
    with pytest.raises(AuthorityRepositoryError, match="stale or foreign"):
        repository.renew_controller_lease(
            RUN_URI,
            lease.lease_id,
            owner_id="controller-2",
            fencing_token=lease.fencing_token,
            lease_ttl_seconds=30,
        )

    renewed = repository.renew_controller_lease(
        RUN_URI,
        lease.lease_id,
        owner_id="controller-1",
        fencing_token=lease.fencing_token,
        lease_ttl_seconds=60,
    )
    released = repository.release_controller_lease(
        RUN_URI,
        renewed.lease_id,
        owner_id="controller-1",
        fencing_token=renewed.fencing_token,
    )

    assert released.state is LeaseState.RELEASED
