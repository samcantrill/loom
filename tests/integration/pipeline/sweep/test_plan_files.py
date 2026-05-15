"""Plan-only filesystem integration tests for deterministic sweeps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom.pipeline.sweep import (
    SWEEP_SPEC_SCHEMA_VERSION,
    SweepManifestError,
    check_existing_sweep_plan,
    plan_sweep_from_file,
    read_sweep_plan,
    write_sweep_plan,
)


pytestmark = pytest.mark.integration


def test_plan_sweep_from_authored_spec_file_writes_and_reads_manifests(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "authored-sweep.json"
    sweep_dir = tmp_path / "planned"
    authored_payload = {
        "schema_version": SWEEP_SPEC_SCHEMA_VERSION,
        "mode": "grid",
        "sweep_id": "file-grid",
        "run_uri_root": "file:///tmp/file-grid",
        "grid": {"pipeline.lr": [0.1], "pipeline.seed": [1, 2]},
    }
    spec_path.write_text(json.dumps(authored_payload), encoding="utf-8")

    plan = plan_sweep_from_file(spec_path, created_at="2026-05-14T00:00:00Z")
    paths = write_sweep_plan(plan, sweep_dir, authored_spec_payload=authored_payload)
    readback = read_sweep_plan(sweep_dir)

    assert readback.compatible
    assert readback.sweep_manifest == plan.sweep_manifest
    assert readback.trials_manifest == plan.trials_manifest
    assert json.loads(paths.authored_spec_path.read_text(encoding="utf-8")) == authored_payload


def test_incompatible_existing_plan_returns_diagnostics_and_is_not_overwritten(
    tmp_path: Path,
) -> None:
    sweep_dir = tmp_path / "planned"
    first = plan_sweep_from_file(
        _write_spec(
            tmp_path,
            "first.json",
            {"pipeline.x": [1]},
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    write_sweep_plan(first, sweep_dir)
    before = (sweep_dir / "trials.json").read_text(encoding="utf-8")

    changed = plan_sweep_from_file(
        _write_spec(
            tmp_path,
            "changed.json",
            {"pipeline.x": [1, 2]},
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    check = check_existing_sweep_plan(sweep_dir, expected_plan=changed)

    assert {diagnostic.code for diagnostic in check.diagnostics} == {
        "trial_count_mismatch",
        "trial_plan_mismatch",
    }
    with pytest.raises(SweepManifestError):
        write_sweep_plan(changed, sweep_dir)
    assert (sweep_dir / "trials.json").read_text(encoding="utf-8") == before


def _write_spec(tmp_path: Path, name: str, grid: dict[str, list[int]]) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "schema_version": SWEEP_SPEC_SCHEMA_VERSION,
                "mode": "grid",
                "sweep_id": "compatible",
                "run_uri_root": "file:///tmp/compatible",
                "grid": grid,
            }
        ),
        encoding="utf-8",
    )
    return path
