"""Contract tests for v10 offline evidence manifests."""

import pytest

from loom.pipeline.offline_evidence import (
    OFFLINE_EVIDENCE_KIND,
    OFFLINE_EVIDENCE_SCHEMA_VERSION,
    OfflineEvidenceError,
    OfflineEvidenceManifest,
)
from loom.state_sources import offline_evidence_source


pytestmark = pytest.mark.contract


def _manifest_payload() -> dict[str, object]:
    return {
        "schema_version": OFFLINE_EVIDENCE_SCHEMA_VERSION,
        "kind": OFFLINE_EVIDENCE_KIND,
        "run_uri": "file:///tmp/loom/run1",
        "generated_at": "2020-01-01T00:00:00Z",
        "manifest_status": "complete",
        "state_source": offline_evidence_source(),
        "run_status": {
            "schema_version": 1,
            "run_uri": "file:///tmp/loom/run1",
            "status": "SUCCEEDED",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:01Z",
            "started_at": "2020-01-01T00:00:00Z",
            "finished_at": "2020-01-01T00:00:01Z",
            "message": None,
            "metadata": {},
        },
        "plan": {"schema_version": 1, "kind": "loom.execution_plan"},
        "runtime": {"schema_version": 1, "executor": "local"},
        "config": {"composition_manifest": None, "recipe_manifest": [], "snapshots": {}},
        "provenance": {"documents": {}},
        "stages": [],
        "events": [],
        "artifact_index": {},
        "diagnostics": [],
    }


def test_offline_evidence_manifest_contract_round_trips() -> None:
    payload = _manifest_payload()

    manifest = OfflineEvidenceManifest.from_dict(payload)

    assert manifest.to_dict() == payload
    assert manifest.complete
    assert manifest.state_source["authoritative"] is False


def test_offline_evidence_manifest_contract_rejects_unknown_fields() -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True

    with pytest.raises(OfflineEvidenceError, match="unknown field"):
        OfflineEvidenceManifest.from_dict(payload)


def test_offline_evidence_manifest_contract_rejects_authoritative_source() -> None:
    payload = _manifest_payload()
    payload["state_source"] = {
        "label": "authoritative_service_truth",
        "description": "wrong",
        "authoritative": True,
        "policy": "online_authority",
        "details": {},
    }

    with pytest.raises(OfflineEvidenceError, match="non-authoritative"):
        OfflineEvidenceManifest.from_dict(payload)
