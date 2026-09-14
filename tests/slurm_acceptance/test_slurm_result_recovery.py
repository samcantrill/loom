"""Opt-in audit of a site-owned unified Slurm outage qualification receipt.

The site performs the journey with its approved service controls and installed
profiles. This audit does not submit jobs, provision services, or convert local
fixtures into physical evidence. Missing receipt means missing qualification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slurm, pytest.mark.slow]


def test_site_unified_run_finish_during_outage_receipt() -> None:
    if os.environ.get("LOOM_RUN_SLURM_ACCEPTANCE") != "1":
        pytest.skip("real Slurm qualification is opt-in")
    path = os.environ.get("LOOM_SLURM_RESULT_QUALIFICATION_RECEIPT")
    if not path:
        pytest.skip(
            "missing site-owned unified run/outage result qualification receipt"
        )
    receipt = json.loads(Path(path).read_text())
    assert receipt["schema_version"] == 1
    assert receipt["run_operation_id"] and receipt["run_uri"]
    assert receipt["site"] and receipt["profile_configuration_fingerprint"]
    assert receipt["permitted_service_host"] and receipt["installed_worker_environment"]
    assert receipt["grant_endpoint_reachable"] is True
    assert receipt["result_storage"] == {
        "shared_visibility_after_compute_exit": True,
        "file_and_directory_fsync": True,
        "atomic_manifest_replace": True,
        "cross_mount_advisory_lock": True,
        "finite_quota_no_unacknowledged_eviction": True,
    }
    assert receipt["same_coordinator_id_before_after"] is True
    assert receipt["same_agent_and_root_before_after"] is True
    assert receipt["job_submission_count"] == 1
    assert receipt["authority_commit_count"] == 1
    assert receipt["original_output_predecessor_preserved"] is True
    assert receipt["lost_ack_replay_same_commit"] is True
    assert receipt["compute_exit_before_service_restart"] is True
    assert receipt["output_digest_before_after_matches"] is True
    assert receipt["cleanup_after_final_ack"] is True
    assert receipt["separate_positive_containment"] is True
    assert receipt["sqlite_storage_qualification"]
    if receipt["container_runtime"] is not None:
        assert receipt["container_result_mount_writable"] is True
        assert receipt["container_worker_evidence_preserved"] is True
    # Require archived evidence for each physical claim rather than accepting
    # an unaccompanied success flag. Paths are site-owned audit inputs.
    for name in (
        "run_and_inspect",
        "service_outage",
        "scheduler",
        "shared_publication",
        "authority_commit_replay",
        "cleanup_and_containment",
        "site_storage_policy",
    ):
        artifact = Path(receipt["evidence"][name])
        assert artifact.is_file() and artifact.stat().st_size > 0, name
