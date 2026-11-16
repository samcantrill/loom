"""Terminal observation persistence and migration do not invent scheduler facts."""

from contextlib import closing
import sqlite3

import pytest

from loom.queue._slurm_terminal_recovery import parse_terminal_recovery, probe_request
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.queue.slurm_ready_stage import _upgrade_terminal_observation_schema, SQLiteSlurmStageAssignments
from tests.unit.loom.queue.test_slurm_admission import ReservationFixture


@pytest.mark.parametrize("value", [True, -1, float("inf"), "120", None])
def test_grace_requires_finite_nonnegative_duration(value):
    with pytest.raises(QueueConfigError):
        parse_terminal_recovery({"terminal_result_grace_seconds": value})


def test_disabled_policy_retains_schema_selection():
    from dataclasses import replace
    from pathlib import Path
    from loom.queue.local_daemon import LocalDaemonConfig

    policy = parse_terminal_recovery({"terminal_result_grace_seconds": 120, "enabled": False})
    config = LocalDaemonConfig(Path("/coordinator"), None, Path("/runs"), None, cpu_capacity=0, slurm_terminal_recovery=policy)
    assert not config.slurm_terminal_recovery.enabled
    assert config.slurm_schema_version == 7
    assert replace(config, slurm_terminal_recovery=parse_terminal_recovery({"terminal_result_grace_seconds": 120})).slurm_schema_version == 7
    with pytest.raises(QueueConfigError, match="boolean"):
        parse_terminal_recovery({"terminal_result_grace_seconds": 120, "enabled": "false"})


def test_terminal_observation_and_probe_survive_reopen_without_resetting_grace(tmp_path):
    fixture = ReservationFixture(tmp_path, schema_version=7)
    assignment, arguments = fixture.candidate("retained", 1)
    fixture.store.reserve(assignment, **arguments)
    identity = {"accounting": {"job_id": "123", "db_index": "99"}, "scheduler_state": "TIMEOUT",
                "result": {"assignment": {"assignment_id": "retained"}, "coordinator_id": "coordinator",
                           "fence": "fence-1", "incarnation": "bootstrap"}}
    observation = fixture.store.observe_terminal_once("retained", identity, "2030-01-01T00:00:00+00:00")
    reopened = fixture.reopen()
    assert reopened.observe_terminal_once("retained", identity, "2030-01-01T01:00:00+00:00") == observation
    probe = {"request": probe_request(observation), "state": "missing"}
    reopened.record_terminal_probe("retained", probe)
    assert fixture.reopen().read("retained").terminal_observation == {**observation, "probe": probe}
    with pytest.raises(QueueConflictError, match="identity conflicts"):
        reopened.observe_terminal_once("retained", {**identity, "result": {**identity["result"], "fence": "other"}}, "2030-01-01T02:00:00+00:00")
    with pytest.raises(QueueConflictError, match="probe conflicts"):
        reopened.record_terminal_probe("retained", {**probe, "request": {}})
    assert fixture.reopen().read("retained").terminal_observation["probe"] == probe


def test_migration_preserves_retained_assignment_without_inventing_observation(tmp_path):
    fixture = ReservationFixture(tmp_path, schema_version=6)
    assignment, arguments = fixture.candidate("retained", 1)
    fixture.store.reserve(assignment, **arguments)
    with closing(sqlite3.connect(fixture.path)) as conn:
        conn.row_factory = sqlite3.Row
        before = dict(conn.execute("SELECT * FROM slurm_stage_assignments").fetchone())
        conn.execute("BEGIN IMMEDIATE")
        _upgrade_terminal_observation_schema(conn)
        conn.commit()
        after = dict(conn.execute("SELECT * FROM slurm_stage_assignments").fetchone())
    assert {key: after[key] for key in before} == before
    assert after["terminal_observation_json"] is None
    store = SQLiteSlurmStageAssignments(fixture.path, fixture.transfers, schema_version=7, sqlite_policy=fixture.policy, _allow_initialize=False)
    assert store.read("retained").terminal_observation is None
    assert store.reserved_gpu_count() == 1
