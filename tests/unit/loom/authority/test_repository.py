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


def test_repository_migrates_complete_v3_output_commits_without_data_loss(
    tmp_path,
) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")
    run_uri = "file:///runs/migration-r1"
    repository.admit_run(run_uri)
    allocation = repository.allocate_stage_attempt(
        run_uri, "build", owner_id="worker-1", lease_ttl_seconds=30
    )
    assert allocation.lease is not None
    commit = repository.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        owner_id="worker-1",
        fencing_token=allocation.lease.fencing_token,
        outputs={},
    )
    database_path = tmp_path / "authority.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_output_commits_stage")
        conn.execute("ALTER TABLE output_commits RENAME TO output_commits_v4")
        conn.execute(
            """
            CREATE TABLE output_commits (
                commit_id TEXT PRIMARY KEY,
                run_uri TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                revision_sequence INTEGER NOT NULL,
                output_names_json TEXT NOT NULL,
                materialized_refs_json TEXT NOT NULL,
                UNIQUE (run_uri, stage_name)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO output_commits (
                commit_id, run_uri, stage_name, attempt_id, committed_at,
                revision_sequence, output_names_json, materialized_refs_json
            )
            SELECT commit_id, run_uri, stage_name, attempt_id, committed_at,
                   revision_sequence, output_names_json, materialized_refs_json
            FROM output_commits_v4
            """
        )
        conn.execute("DROP TABLE output_commits_v4")
        conn.execute(
            "UPDATE repository_metadata SET value = '3' WHERE key = 'schema_version'"
        )

    identity = AuthorityRepository(tmp_path).initialize(
        service_generation="generation-ignored"
    )
    migrated = AuthorityRepository(tmp_path)

    assert identity.schema_version == AUTHORITY_REPOSITORY_SCHEMA_VERSION
    assert migrated.list_output_commits(run_uri) == (commit,)
    assert migrated.open_run(run_uri).stages[0].latest_commit == commit.commit


def test_repository_rejects_incomplete_v3_without_partial_migration(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    repository.initialize(service_generation="generation-1")
    database_path = tmp_path / "authority.sqlite3"
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE artifact_facts")
        conn.execute(
            "UPDATE repository_metadata SET value = '3' WHERE key = 'schema_version'"
        )

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path).initialize()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.CORRUPT
    with sqlite3.connect(database_path) as conn:
        version = conn.execute(
            "SELECT value FROM repository_metadata WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert version == ("3",)
    assert "output_commits_v3" not in tables
    assert "artifact_facts" not in tables


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
