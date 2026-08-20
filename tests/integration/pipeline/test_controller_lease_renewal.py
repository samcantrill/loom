"""Integration coverage for runner-owned controller lease renewal."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
import time
from typing import cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest, RunResult
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    AttemptAllocation,
    AuthorityStoreError,
    LeaseRecord,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.serialization import PlainData


pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


class _ControllerRenewalAuthority(SQLitePerRunAuthorityStore):
    def __init__(self, *, fail_renewal: bool = False) -> None:
        self.clock = _MutableClock("2020-01-01T00:00:00Z")
        super().__init__(clock=self.clock)
        self.fail_renewal = fail_renewal
        self.controller_lease_id: str | None = None
        self.controller_renewals = 0
        self.expected_renewal_time: str | None = None
        self.renewal_observed = Event()
        self.expected_renewal_observed = Event()
        self.expected_stage_renewal_observed = Event()
        self.stage_allocated = Event()

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        lease = super().acquire_controller_lease(
            run_uri,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        self.controller_lease_id = lease.lease_id
        return lease

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        allocation = super().allocate_stage_attempt(
            run_uri,
            stage_name,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        self.stage_allocated.set()
        return allocation

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        is_controller = lease_id == self.controller_lease_id
        if is_controller:
            if self.fail_renewal and not self.stage_allocated.is_set():
                return super().renew_lease(
                    lease_id,
                    owner_id=owner_id,
                    fencing_token=fencing_token,
                    lease_ttl_seconds=lease_ttl_seconds,
                )
            if self.fail_renewal:
                self.controller_renewals += 1
                self.renewal_observed.set()
                raise AuthorityStoreError("controller renewal unavailable")
        renewed = super().renew_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        if is_controller:
            self.controller_renewals += 1
            self.renewal_observed.set()
            if self.clock.value == self.expected_renewal_time:
                self.expected_renewal_observed.set()
        elif self.clock.value == self.expected_renewal_time:
            self.expected_stage_renewal_observed.set()
        return renewed


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


def _release_config(marker_dir: Path) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "controller-renewal",
                "stages": [
                    {
                        "name": "active",
                        "factory": {
                            "_target_": (
                                "tests.support.pipeline_execution_stages.ReleaseStage"
                            )
                        },
                        "config": {"marker_dir": str(marker_dir)},
                        "outputs": {
                            "data": {
                                "artifact_type": "json",
                                "codec_key": "json.v1",
                            }
                        },
                    }
                ],
            }
        },
    )


def _release_after_renewal(
    authority: _ControllerRenewalAuthority, marker_dir: Path
) -> Thread:
    def release() -> None:
        if not authority.renewal_observed.wait(timeout=5):
            return
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "release").write_text("release", encoding="utf-8")

    thread = Thread(target=release, daemon=True)
    thread.start()
    return thread


def test_runner_renews_controller_lease_until_release(tmp_path: Path) -> None:
    authority = _ControllerRenewalAuthority()
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs", authority_store=authority
    )
    runner = PipelineRunner(run_store=run_store)
    runner._controller_lease_renewal_interval_seconds = 0.001
    runner._stage_lease_renewal_interval_seconds = 0.001
    marker_dir = tmp_path / "markers"
    run_uri = path_to_run_uri(tmp_path / "runs" / "healthy")
    results: list[RunResult] = []
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            results.append(
                runner.run(
                    RunRequest(config=_release_config(marker_dir), run_uri=run_uri)
                )
            )
        except BaseException as exc:
            errors.append(exc)

    execution = Thread(target=execute, daemon=True)
    execution.start()
    try:
        assert authority.stage_allocated.wait(timeout=5)
        authority.expected_renewal_time = "2020-01-01T23:59:59Z"
        authority.clock.value = authority.expected_renewal_time
        assert authority.expected_renewal_observed.wait(timeout=5)
        assert authority.expected_stage_renewal_observed.wait(timeout=5)

        authority.clock.value = "2020-01-02T00:00:01Z"
        with pytest.raises(AuthorityStoreError, match="active controller lease"):
            authority.acquire_controller_lease(
                run_uri,
                owner_id="competing-controller",
                lease_ttl_seconds=24 * 60 * 60,
            )
    finally:
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "release").write_text("release", encoding="utf-8")
        execution.join(timeout=5)
    assert not execution.is_alive()
    assert errors == []
    assert len(results) == 1
    renewals_after_run = authority.controller_renewals
    time.sleep(0.02)

    assert results[0].failure is None
    assert renewals_after_run >= 1
    assert authority.controller_renewals == renewals_after_run
    next_controller = authority.acquire_controller_lease(
        run_uri,
        owner_id="next-controller",
        lease_ttl_seconds=24 * 60 * 60,
    )
    assert next_controller.owner_id == "next-controller"


def test_controller_renewal_error_blocks_output_commit(tmp_path: Path) -> None:
    authority = _ControllerRenewalAuthority(fail_renewal=True)
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs", authority_store=authority
    )
    runner = PipelineRunner(run_store=run_store)
    runner._controller_lease_renewal_interval_seconds = 0.001
    marker_dir = tmp_path / "markers"
    release = _release_after_renewal(authority, marker_dir)
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed-renewal")

    with pytest.raises(AuthorityStoreError, match="controller renewal unavailable"):
        runner.run(RunRequest(config=_release_config(marker_dir), run_uri=run_uri))
    release.join(timeout=5)

    snapshot = authority.snapshot(run_uri)
    active = next(stage for stage in snapshot.stages if stage.stage_name == "active")
    assert authority.controller_renewals == 1
    assert active.status is StageStatus.FAILED
    assert active.latest_commit is None
    assert active.artifact_facts == ()
    assert run_store.read_artifact_index(run_uri) == {}
