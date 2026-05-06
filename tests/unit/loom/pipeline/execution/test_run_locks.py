"""Unit tests for execution run-lock helpers."""

from pathlib import Path

from loom.pipeline.execution.run_locks import (
    acquire_run_lock,
    build_lock_owner,
    release_run_lock,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def test_build_lock_owner_records_runner_identity() -> None:
    assert build_lock_owner(
        component="PipelineRunner",
        run_uri="run1",
        executor="local",
    ) == {
        "component": "PipelineRunner",
        "run_uri": "run1",
        "executor": "local",
    }


def test_acquire_and_release_run_lock(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    lock = acquire_run_lock(
        store,
        run_uri,
        owner=build_lock_owner(
            component="PipelineRunner",
            run_uri=run_uri,
            executor="local",
        ),
    )

    assert store.read_run_lock(run_uri) is not None
    release_run_lock(store, lock)
    assert store.read_run_lock(run_uri) is None


def test_release_run_lock_ignores_missing_active_lock(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    release_run_lock(store, None)

    assert store.read_run_lock(run_uri) is None
