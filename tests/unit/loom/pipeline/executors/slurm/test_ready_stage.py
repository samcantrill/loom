from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import (
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    SlurmReadyStageRequest,
)


def test_submission_start_permit_is_atomic_across_bootstrap_incarnations(tmp_path) -> None:
    """Only one concurrent bootstrap can receive the authored-root permit."""

    runner = FakeSlurmCommandRunner()
    profile = SlurmReadyStageProfile(
        profile_id="training",
        fingerprint="profile-v1",
        partition="gpu",
        max_outstanding=1,
        bootstrap_argv=("loom-bootstrap",),
        runner=runner,
    )
    request = SlurmReadyStageRequest(
        operation_id="operation-1",
        stage_work_id="work-1",
        run_uri="runs/example",
        attempt_id="attempt-1",
        profile_id="training",
        placement_fingerprint="placement-1",
        directives=(),
        script="#!/usr/bin/env bash\n",
        digest="digest-1",
    )
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, tmp_path / "bootstrap.sh")

    with ThreadPoolExecutor(max_workers=2) as executor:
        permits = list(executor.map(lambda _: store.consume_start("operation-1"), range(2)))

    assert permits.count(True) == 1
    assert permits.count(False) == 1
    assert store.read("operation-1").start_consumed is True
