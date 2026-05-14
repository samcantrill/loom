"""Unit tests for deterministic sweep planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.sweep import (
    DEFAULT_MAX_GENERATED_TRIALS,
    GridSweepSpec,
    ManualSweepSpec,
    ManualTrialSpec,
    SweepManifestError,
    SweepProtocolError,
    build_trial_id,
    build_trial_run_uri,
    check_existing_sweep_plan,
    parse_sweep_spec,
    plan_sweep,
    read_sweep_manifest,
    read_sweep_plan,
    read_trials_manifest,
    trial_override_expressions,
    write_sweep_plan,
)


def test_grid_plan_is_deterministic_and_writes_manifests(tmp_path: Path) -> None:
    spec = GridSweepSpec(
        sweep_id="sweep-grid",
        sweep_name="grid",
        run_uri_root="file:///tmp/loom/sweeps/sweep-grid",
        grid={
            "pipeline.lr": [0.1, 0.01],
            "pipeline.seed": [1, 2],
        },
        metadata={"owner": "unit"},
    )

    first = plan_sweep(spec, created_at="2026-05-14T00:00:00Z")
    second = plan_sweep(spec, created_at="2026-05-14T00:00:00Z")

    assert [trial.to_dict() for trial in first.trials] == [
        trial.to_dict() for trial in second.trials
    ]
    assert [trial.trial_id for trial in first.trials] == [
        "trial-0001",
        "trial-0002",
        "trial-0003",
        "trial-0004",
    ]
    assert [trial.proposal_overrides for trial in first.trials] == [
        {"pipeline.lr": 0.1, "pipeline.seed": 1},
        {"pipeline.lr": 0.1, "pipeline.seed": 2},
        {"pipeline.lr": 0.01, "pipeline.seed": 1},
        {"pipeline.lr": 0.01, "pipeline.seed": 2},
    ]
    assert first.trials[0].run_uri == "file:///tmp/loom/sweeps/sweep-grid/trial-0001"
    assert first.trials[0].provider_trial_id == "grid-0001"
    assert first.trials[0].metadata["override_expressions"] == [
        "pipeline.lr=0.1",
        "pipeline.seed=1",
    ]

    paths = write_sweep_plan(first, tmp_path)

    assert read_sweep_manifest(paths.sweep_manifest_path) == first.sweep_manifest
    assert read_trials_manifest(
        paths.trials_manifest_path, sweep_id="sweep-grid"
    ) == first.trials_manifest
    assert paths.authored_spec_path.read_text(encoding="utf-8")
    readback = read_sweep_plan(tmp_path)
    assert readback.compatible
    assert readback.sweep_manifest == first.sweep_manifest
    assert readback.trials_manifest == first.trials_manifest


def test_manual_plan_preserves_names_external_ids_and_metadata() -> None:
    spec = ManualSweepSpec(
        sweep_id="sweep-manual",
        run_uri_root="file:///tmp/loom/sweeps/manual",
        trials=(
            ManualTrialSpec(
                name="baseline",
                provider_trial_id="external-17",
                overrides={"pipeline.variant": "baseline"},
                metadata={"source": "external-generator"},
            ),
            ManualTrialSpec(
                name="ablated",
                overrides={"pipeline.variant": "ablated", "pipeline.enabled": False},
            ),
        ),
    )

    plan = plan_sweep(spec, created_at="2026-05-14T00:00:00Z")

    assert [trial.trial_id for trial in plan.trials] == ["trial-0001", "trial-0002"]
    assert plan.trials[0].provider_trial_id == "external-17"
    assert plan.trials[0].metadata["trial_name"] == "baseline"
    assert plan.trials[0].metadata["source"] == "external-generator"
    assert plan.trials[1].provider_trial_id == "manual-0002"
    assert plan.trials[1].metadata["trial_name"] == "ablated"
    assert plan.trials[1].proposal_overrides == {
        "pipeline.variant": "ablated",
        "pipeline.enabled": False,
    }


def test_trial_guard_defaults_to_one_hundred_and_allows_explicit_override() -> None:
    values = list(range(DEFAULT_MAX_GENERATED_TRIALS + 1))
    guarded = GridSweepSpec(
        sweep_id="too-large",
        grid={"pipeline.seed": values},
    )

    with pytest.raises(SweepProtocolError, match="generated trial count 101"):
        plan_sweep(guarded)

    explicit = GridSweepSpec(
        sweep_id="allowed-large",
        grid={"pipeline.seed": values},
        max_generated_trials=DEFAULT_MAX_GENERATED_TRIALS + 1,
    )
    plan = plan_sweep(explicit)

    assert len(plan.trials) == DEFAULT_MAX_GENERATED_TRIALS + 1
    assert plan.trials[-1].trial_id == "trial-0101"


def test_parse_sweep_spec_normalizes_grid_and_manual_payloads() -> None:
    grid = parse_sweep_spec(
        {
            "schema_version": 1,
            "mode": "grid",
            "sweep_id": "grid",
            "grid": {"pipeline.x": [1, 2]},
        }
    )
    manual = parse_sweep_spec(
        {
            "schema_version": 1,
            "mode": "manual",
            "sweep_id": "manual",
            "trials": [{"overrides": {"pipeline.x": 1}}],
        }
    )

    assert isinstance(grid, GridSweepSpec)
    assert isinstance(manual, ManualSweepSpec)


def test_override_paths_use_existing_override_parser() -> None:
    with pytest.raises(SweepProtocolError, match="invalid override path"):
        GridSweepSpec(sweep_id="bad", grid={"pipeline..value": [1]})

    assert trial_override_expressions({"pipeline.name": "abc"}) == (
        'pipeline.name="abc"',
    )


def test_trial_id_and_run_uri_helpers_validate_inputs() -> None:
    assert build_trial_id(0) == "trial-0001"
    assert build_trial_run_uri("file:///tmp/sweep/", "trial-0001") == (
        "file:///tmp/sweep/trial-0001"
    )

    with pytest.raises(SweepProtocolError):
        build_trial_id(-1)
    with pytest.raises(SweepProtocolError):
        build_trial_run_uri("", "trial-0001")


def test_write_sweep_plan_rejects_incompatible_existing_plan(tmp_path: Path) -> None:
    first = plan_sweep(
        GridSweepSpec(
            sweep_id="sweep",
            run_uri_root="file:///tmp/sweep",
            grid={"pipeline.x": [1]},
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    write_sweep_plan(first, tmp_path)

    changed = plan_sweep(
        GridSweepSpec(
            sweep_id="sweep",
            run_uri_root="file:///tmp/sweep",
            grid={"pipeline.x": [1, 2]},
        ),
        created_at="2026-05-14T00:00:00Z",
    )

    check = check_existing_sweep_plan(tmp_path, expected_plan=changed)
    assert not check.compatible
    assert {diagnostic.code for diagnostic in check.diagnostics} == {
        "trial_count_mismatch",
        "trial_plan_mismatch",
    }
    with pytest.raises(SweepManifestError, match="trial_plan_mismatch"):
        write_sweep_plan(changed, tmp_path)
