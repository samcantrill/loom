"""Contract tests for sweep manifest models and compatibility diagnostics."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.sweep import (
    TRIALS_MANIFEST_FILE_NAME,
    SWEEP_MANIFEST_FILE_NAME,
    SWEEP_MANIFEST_SCHEMA_VERSION,
    SWEEP_SPEC_SCHEMA_VERSION,
    TRIALS_MANIFEST_SCHEMA_VERSION,
    SweepManifest,
    SweepManifestCompatibilityDiagnostic,
    SweepProviderIdentity,
    TrialsManifest,
    check_sweep_manifest_payload,
    check_trials_manifest_payload,
    plan_sweep,
)

pytestmark = pytest.mark.contract


_PROVIDER = SweepProviderIdentity(
    provider_name="provider",
    provider_type="integration",
    version="1",
    metadata={"scope": "tests"},
)


def _sweep_payload() -> dict[str, object]:
    return {
        "schema_version": SWEEP_MANIFEST_SCHEMA_VERSION,
        "sweep_id": "sweep-1",
        "sweep_name": "contract-sweep",
        "provider": _PROVIDER.to_dict(),
        "created_at": "2020-01-01T00:00:00Z",
        "trial_count": 2,
        "trials_manifest": TRIALS_MANIFEST_FILE_NAME,
        "metadata": {"namespace": "contract"},
    }


def _trials_payload() -> dict[str, object]:
    return {
        "schema_version": TRIALS_MANIFEST_SCHEMA_VERSION,
        "sweep_id": "sweep-1",
        "trials": [
            {
                "trial_id": "trial-1",
                "trial_index": 0,
                "sweep_id": "sweep-1",
                "run_uri": "file:///runs/trial-1",
                "provider_trial_id": "provider-1",
                "proposal_overrides": {"a": 1},
                "metadata": {"origin": "tests"},
            },
            {
                "trial_id": "trial-2",
                "trial_index": 1,
                "sweep_id": "sweep-1",
                "run_uri": "file:///runs/trial-2",
                "provider_trial_id": None,
                "proposal_overrides": {"a": 2},
                "metadata": {},
            },
        ],
        "generated_at": "2020-01-01T00:00:01Z",
        "metadata": {},
    }


def test_sweep_manifest_contract_round_trips() -> None:
    manifest = SweepManifest.from_dict(_sweep_payload())

    assert manifest.to_dict() == _sweep_payload()

    payload = _trials_payload()
    trials = TrialsManifest.from_dict(payload)
    assert trials.to_dict() == payload


def test_sweep_manifest_compatibility_reports_unsupported_version() -> None:
    payload = _sweep_payload()
    payload["schema_version"] = SWEEP_MANIFEST_SCHEMA_VERSION + 1

    manifest, diagnostics = check_sweep_manifest_payload(payload, sweep_dir="/tmp")

    assert manifest is None
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert isinstance(diagnostic, SweepManifestCompatibilityDiagnostic)
    assert diagnostic.code == "unsupported_sweep_schema_version"
    assert diagnostic.manifest_name == SWEEP_MANIFEST_FILE_NAME
    assert diagnostic.sweep_dir == "/tmp"


def test_trials_manifest_compatibility_reports_schema_and_sweep_id_mismatch() -> None:
    payload = _trials_payload()
    payload["schema_version"] = TRIALS_MANIFEST_SCHEMA_VERSION + 1
    trials, diagnostics = check_trials_manifest_payload(
        payload, sweep_dir="/tmp", sweep_id="sweep-1"
    )
    assert trials is None
    assert diagnostics[0].code == "unsupported_trials_schema_version"
    payload = _trials_payload()
    _, diagnostics = check_trials_manifest_payload(
        _trials_payload(),
        sweep_dir="/tmp",
        sweep_id="other-sweep",
    )
    assert diagnostics[0].code == "sweep_id_mismatch"
    assert diagnostics[0].detail["sweep_id"] == "other-sweep"

    malformed_payload = _trials_payload()
    malformed_payload["trials"] = [{"trial_id": ""}]
    _, diagnostics = check_trials_manifest_payload(
        malformed_payload,
        sweep_dir="/tmp",
        sweep_id="sweep-1",
    )
    assert diagnostics[0].code == "malformed_trials_manifest"
    assert diagnostics[0].detail["sweep_id"] == "sweep-1"
    assert "trial_id" not in diagnostics[0].detail


def test_planned_grid_manifests_preserve_phase_one_schema_shape() -> None:
    plan = plan_sweep(
        {
            "schema_version": SWEEP_SPEC_SCHEMA_VERSION,
            "mode": "grid",
            "sweep_id": "contract-grid",
            "run_uri_root": "file:///tmp/contract-grid",
            "grid": {"pipeline.x": [1, 2]},
        },
        created_at="2026-05-14T00:00:00Z",
    )

    sweep_payload = plan.sweep_manifest.to_dict()
    trials_payload = plan.trials_manifest.to_dict()
    provider_payload = cast(dict[str, object], sweep_payload["provider"])
    trial_payloads = cast(list[dict[str, object]], trials_payload["trials"])

    assert sweep_payload["schema_version"] == SWEEP_MANIFEST_SCHEMA_VERSION
    assert trials_payload["schema_version"] == TRIALS_MANIFEST_SCHEMA_VERSION
    assert provider_payload["provider_type"] == "loom.grid"
    assert trial_payloads[0]["trial_id"] == "trial-0001"
    assert trial_payloads[0]["run_uri"] == "file:///tmp/contract-grid/trial-0001"
