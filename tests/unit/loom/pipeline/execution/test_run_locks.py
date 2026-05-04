"""Unit tests for execution run-lock helpers."""

from pathlib import Path

from loom.pipeline.execution.run_locks import (
    acquire_run_lock,
    build_lock_owner,
    release_run_lock,
)
from loom.pipeline.stores import LocalRunStore


def test_build_lock_owner_records_runner_identity() -> None:
    assert build_lock_owner(
        component="PipelineRunner",
        run_id="run1",
        executor="local",
    ) == {
        "component": "PipelineRunner",
        "run_id": "run1",
        "executor": "local",
    }


def test_acquire_and_release_run_lock(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    store.create_run("run1")

    lock = acquire_run_lock(
        store,
        "run1",
        owner=build_lock_owner(
            component="PipelineRunner",
            run_id="run1",
            executor="local",
        ),
    )

    assert store.read_run_lock("run1") is not None
    release_run_lock(store, lock)
    assert store.read_run_lock("run1") is None


def test_release_run_lock_ignores_missing_active_lock(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    store.create_run("run1")

    release_run_lock(store, None)

    assert store.read_run_lock("run1") is None
