"""Unit tests for the private authority repository foundation."""

from __future__ import annotations

import sqlite3

import pytest

from loom.authority._repository import (
    AUTHORITY_REPOSITORY_COORDINATION_DB_NAME,
    AUTHORITY_REPOSITORY_SCHEMA_VERSION,
    AuthorityRepository,
    AuthorityRepositoryCompatibilityError,
    AuthorityRepositoryCompatibilityFailure,
    AuthorityRepositoryCompatibilityKind,
    AuthorityRepositoryIdentity,
    generate_service_generation,
)
from loom.pipeline.stores import (
    BackendRevision,
    LeaseKind,
    LeaseState,
    TrialReference,
    TrialState,
    WorkspaceIdentity,
    SweepIdentity,
)


pytestmark = pytest.mark.unit


def test_compatibility_failure_serializes_stable_code() -> None:
    failure = AuthorityRepositoryCompatibilityFailure(
        kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER,
        message="newer schema",
        found_version=3,
        detail={"database_path": "/tmp/authority.sqlite3"},
    )

    assert failure.code == "authority_repository_unsupported_newer"
    assert failure.to_dict() == {
        "kind": "unsupported_newer",
        "code": "authority_repository_unsupported_newer",
        "message": "newer schema",
        "found_version": 3,
        "current_version": AUTHORITY_REPOSITORY_SCHEMA_VERSION,
        "detail": {"database_path": "/tmp/authority.sqlite3"},
    }


def test_service_generation_is_opaque_non_empty_token() -> None:
    first = generate_service_generation()
    second = generate_service_generation()

    assert first.startswith("authority-generation-")
    assert second.startswith("authority-generation-")
    assert first != second


def test_repository_requires_valid_database_name(tmp_path) -> None:
    with pytest.raises(ValueError, match="database_name"):
        AuthorityRepository(tmp_path, database_name="nested/authority.sqlite3")


def test_repository_identity_serializes_paths_and_metadata(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    identity = repository.initialize(service_generation="generation-1")

    assert isinstance(identity, AuthorityRepositoryIdentity)
    assert identity.state_dir == tmp_path
    assert identity.database_path == tmp_path / "authority.sqlite3"
    assert identity.schema_version == AUTHORITY_REPOSITORY_SCHEMA_VERSION
    assert identity.service_generation == "generation-1"
    assert identity.to_dict()["state_dir"] == str(tmp_path)
    assert identity.to_dict()["database_path"] == str(tmp_path / "authority.sqlite3")


def test_repository_hard_cuts_pre_coordinator_schema_without_mutation(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")
    database_path = tmp_path / "authority.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "UPDATE repository_metadata SET value = '4' WHERE key = 'schema_version'"
        )

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path).initialize()

    assert (
        exc_info.value.failure.kind
        is AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER
    )
    with sqlite3.connect(database_path) as conn:
        version = conn.execute(
            "SELECT value FROM repository_metadata WHERE key = 'schema_version'"
        ).fetchone()
    assert version == ("4",)


def test_read_identity_fails_for_missing_database(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        repository.read_identity()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.MISSING


def test_repository_persists_workspace_coordination_in_service_state(
    tmp_path,
) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")

    workspace_revision = repository.create_workspace(
        WorkspaceIdentity(
            workspace_id="workspace-1",
            root_uri="file:///workspace",
        )
    )
    repository.create_sweep(
        SweepIdentity(sweep_id="sweep-1", workspace_id="workspace-1")
    )
    trial = TrialReference(
        trial_id="trial-1",
        sweep_id="sweep-1",
        run_uri="file:///runs/trial-1",
        state=TrialState.PENDING,
        revision=BackendRevision(sequence=42, token="trial-rev"),
    )
    trial_revision = repository.record_trial(trial)

    assert workspace_revision.sequence == 1
    assert trial_revision.sequence > workspace_revision.sequence
    assert repository.list_trials("sweep-1") == (trial,)
    assert (tmp_path / AUTHORITY_REPOSITORY_COORDINATION_DB_NAME).exists()

    trial_lease = repository.acquire_trial_lease(
        "sweep-1",
        "trial-1",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert trial_lease.lease.kind is LeaseKind.TRIAL
    assert trial_lease.workspace_id == "workspace-1"
    released = repository.release_coordination_lease(
        trial_lease.lease.lease_id,
        owner_id="worker-1",
        fencing_token=trial_lease.lease.fencing_token,
    )
    assert released.state is LeaseState.RELEASED

    limited = repository.set_counter_limit(
        "workspace-1",
        "active_trials",
        limit=2,
    )
    assert limited.limit == 2
    incremented = repository.increment_counter("workspace-1", "active_trials")
    assert incremented.value == 1
    assert repository.read_counter("workspace-1", "active_trials") == incremented
