"""Unit coverage for local-daemon control ownership."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from shutil import copyfile
import sqlite3
from types import SimpleNamespace
from typing import Any, cast

import pytest

import loom.queue.local_daemon_execution as local_daemon_execution
from loom.queue import (
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    QueueConflictError,
    QueueServiceError,
    QueueStorageError,
)
from loom.queue.agent_sessions import AgentPolicyConfig, TransportPrincipalPolicy


def _config(tmp_path: Path) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        agent_policy=AgentPolicyConfig(
            principals=(
                TransportPrincipalPolicy(
                    "operator-credential",
                    "operator",
                    "operator",
                    actions=("scheduling_reload",),
                ),
            )
        ),
    )


def test_initialize_start_restart_preserves_owner_and_rotates_epoch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first_status = first.start()
    first.stop()

    second = LocalDaemon(config)
    second_status = second.start()
    second.stop()

    assert second_status.coordinator_id == first_status.coordinator_id
    assert second_status.coordinator_epoch != first_status.coordinator_epoch


def test_scheduling_reload_is_local_atomic_and_durable(tmp_path: Path) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        agent_policy=AgentPolicyConfig(
            revision="policy-2",
            principals=config.agent_policy.principals,
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    request = CoordinatorSchedulingReload(
        operation_id="reload-scheduling-1",
        expected_scheduling_epoch=before.scheduling_epoch,
        reason="site policy changed",
    )
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    try:
        receipt = operator.reload_scheduling(request)
        assert receipt["state"] == "applied"
        assert receipt["scheduling_epoch"] != before.scheduling_epoch
        assert operator.reload_scheduling(request) == receipt
        status = operator.status()
        assert status.scheduling_epoch == receipt["scheduling_epoch"]
        assert any(
            item.get("owner") == "coordinator-scheduling"
            and item.get("state") == "applied"
            for item in status.controls
        )
    finally:
        daemon.stop()

    with pytest.raises(QueueConflictError, match="changed without reload"):
        LocalDaemon(config).start()
    restarted = LocalDaemon(replacement)
    restarted.start()
    restarted.stop()


def test_scheduling_reload_without_trusted_loader_fails_without_swap(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    before = daemon.start()
    try:
        receipt = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-scheduling-1",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="no protected loader",
            )
        )
        assert receipt == {
            "operation_id": "reload-scheduling-1",
            "state": "failed",
            "code": "reload_rejected",
            "scheduling_epoch": before.scheduling_epoch,
        }
        assert daemon.config is config
    finally:
        daemon.stop()


def test_start_is_open_only_and_second_owner_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(QueueServiceError, match="missing"):
        LocalDaemon(config).start()

    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    try:
        with pytest.raises(QueueServiceError, match="already locked"):
            LocalDaemon(config).start()
    finally:
        first.stop()


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_start_rejects_missing_expected_owner_store_without_retaining_locks(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    store_path = getattr(config, owner_store)
    store_path.unlink()

    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    assert not store_path.exists()


@pytest.mark.parametrize(
    "store_path",
    ("control_database", "execution_database", "agent_journal"),
)
def test_start_rejects_current_schema_owner_substitution(
    tmp_path: Path, store_path: str
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    target = getattr(config, store_path)
    target.unlink()
    copyfile(getattr(donor, store_path), target)
    target.chmod(0o600)

    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()


def test_live_control_loss_never_recreates_control_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        config.control_database.unlink()
        with pytest.raises(QueueStorageError, match="control state is unavailable"):
            daemon.status()
        assert not config.control_database.exists()
    finally:
        daemon.stop()


def test_live_control_substitution_rejects_cached_coordinator_identity(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        config.control_database.unlink()
        copyfile(donor.control_database, config.control_database)
        with pytest.raises(QueueStorageError, match="control identity is invalid"):
            daemon.status()
    finally:
        daemon.stop()


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_live_owner_substitution_degrades_status_and_blocks_scheduling(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        target = getattr(config, owner_store)
        target.unlink()
        copyfile(getattr(donor, owner_store), target)
        target.chmod(0o600)

        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "owner_status_unavailable"
        with pytest.raises(QueueServiceError, match="owner state is unavailable"):
            daemon.reconcile_once()
    finally:
        daemon.stop()


def test_failed_execution_construction_releases_daemon_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)

    class _Failure:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("construction failed")

    monkeypatch.setattr(local_daemon_execution, "LocalDaemonExecution", _Failure)
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()

    monkeypatch.undo()
    restarted = LocalDaemon(config)
    restarted.start()
    restarted.stop()


def test_slurm_cancellation_fanout_uses_only_exact_known_handles() -> None:
    """An epoch request is not mistaken for scheduler containment."""

    known = SimpleNamespace(
        state="accepted",
        assignment=SimpleNamespace(
            operation_id="known",
            profile_id="profile-a",
            profile_configuration_fingerprint="config-a",
        ),
    )
    unknown = SimpleNamespace(
        state="submitting",
        assignment=SimpleNamespace(
            operation_id="unknown",
            profile_id="profile-a",
            profile_configuration_fingerprint="config-a",
        ),
    )

    class _Assignments:
        def list_run_unreleased(self, run_uri: str) -> tuple[object, ...]:
            assert run_uri == "run://example"
            return (known, unknown)

    calls: list[tuple[str, object]] = []

    class _Submissions:
        def find(self, operation_id: str) -> object:
            return (
                SimpleNamespace(job_id="1234")
                if operation_id == "known"
                else SimpleNamespace(job_id=None)
            )

        def request_cancel(self, operation_id: str, profile: object) -> object:
            calls.append((operation_id, profile))
            return SimpleNamespace(cancel_requested=True)

    execution = object.__new__(local_daemon_execution.LocalDaemonExecution)
    subject = cast(Any, execution)
    subject.slurm_assignments = _Assignments()
    subject.slurm_submissions = _Submissions()
    subject._slurm_profile = lambda profile_id, fingerprint: (
        f"resolved:{profile_id}:{fingerprint}"
    )

    assert execution._fan_out_slurm_cancellation("run://example") is True
    assert calls == [("known", "resolved:profile-a:config-a")]


def test_slurm_grant_and_start_are_blocked_by_the_durable_cancel_request(
    tmp_path: Path,
) -> None:
    control_database = tmp_path / "control.sqlite"
    with sqlite3.connect(control_database) as conn:
        conn.execute(
            "CREATE TABLE managed_admissions ("
            "run_uri TEXT PRIMARY KEY, cancellation_operation_id TEXT)"
        )
        conn.execute(
            "INSERT INTO managed_admissions VALUES ('run://cancelled', 'cancel-1')"
        )
        conn.commit()

    record = SimpleNamespace(
        input_ready=True,
        fence=None,
        state="accepted",
        assignment=SimpleNamespace(
            run_uri="run://cancelled",
            operation_id="slurm-operation-1",
            attempt_id="attempt-1",
        ),
    )
    execution = object.__new__(local_daemon_execution.LocalDaemonExecution)
    subject = cast(Any, execution)
    subject.config = SimpleNamespace(control_database=control_database)
    subject._slurm_authorized_record = lambda *args, **kwargs: record
    subject._remote_authority = lambda run_uri: pytest.fail(
        "cancellation must block authority grant"
    )
    subject.slurm_submissions = SimpleNamespace(
        consume_start=lambda operation_id: pytest.fail(
            "cancellation must block authored-root start"
        )
    )

    with pytest.raises(QueueConflictError, match="run is cancelling"):
        execution.slurm_grant(
            principal_id="slurm-principal",
            credential_id="slurm-credential",
            assignment_id="assignment-1",
            incarnation="bootstrap-1",
        )

    record.fence = "fence-1"
    record.state = "granted"
    assert (
        execution.slurm_start_permit(
            principal_id="slurm-principal",
            credential_id="slurm-credential",
            assignment_id="assignment-1",
            incarnation="bootstrap-1",
            fence="fence-1",
        )
        is False
    )


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_live_owner_loss_degrades_service_and_blocks_scheduling(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        store_path = getattr(config, owner_store)
        store_path.unlink()

        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "owner_status_unavailable"
        assert not status.scheduling_ready
        with pytest.raises(QueueServiceError, match="owner state is unavailable"):
            daemon.reconcile_once()
        assert not store_path.exists()
    finally:
        daemon.stop()


def test_schema_mismatch_requires_fresh_root_without_migration(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("PRAGMA user_version = 0")

    with pytest.raises(QueueStorageError, match="fresh roots"):
        LocalDaemon(config).start()


def test_scoped_view_rejects_client_principal_for_operator_action(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        operator = daemon.operator_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            operator.status()
    finally:
        daemon.stop()
