"""Installed projects own reason vocabulary, while native code owns the wire."""

from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest

from loom.fingerprints import hash_mapping
from loom.pipeline._action_verification import action_verification_response
from loom.pipeline._project_contracts import envelope
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.preparation import PreparationChildInput, SharedInputReceipt
from loom.preparation import _decode_action_verification_report, _run_action_verification


def _candidate():
    revision = {"sequence": 1, "token": "revision"}
    result = {"commit": {"commit_id": "original", "run_uri": "file:///runs/original",
                          "stage_name": "producer", "attempt_id": "producer-1",
                          "committed_at": "2026-09-16T00:00:00Z", "revision": revision,
                          "output_names": [], "materialized_refs": [], "supersedes_commit_id": None},
              "artifact_facts": []}
    candidate = {"schema_version": 1, "namespace": "text-project", "semantic_key": {"version": 1, "digest": "a" * 64},
                 "execution_key": "sha256:" + "b" * 64,
                 "producer": {"run_uri": "file:///runs/original", "node_id": "producer", "attempt_id": "producer-1", "assignment_id": "assignment", "fencing_token": "fence"},
                 "result": result, "output_contracts": {}, "installation": {}, "access": {"mode": "read_only"}}
    candidate["candidate_digest"] = hash_mapping(candidate)
    return candidate


def _binding():
    candidate = _candidate()
    contract = envelope("text-project", {"semantic_key": candidate["semantic_key"], "payload": {}},
                        capture="sha256:" + "c" * 64, node="consumer", original={})
    return PreparationChildInput(
        "verify-one", "profile", "pipeline.yaml", SharedInputReceipt("sha256:" + "d" * 64, "projects", "capture"),
        ResidentProfileDescriptor("profile", "1", "project", "environment", "executor").to_dict(),
        local_scope={"agent_id": "agent", "binding_fingerprint": "e" * 64},
        project_preparation={"processor": {"schema_version": 3, "callable": "installed_verifier:inspect", "evidence_namespace": "text-project", "target_prefix": "text-"}, "target_run_uri": "file:///runs/consumer"},
        action_verification={"node_id": "consumer", "contract": contract, "candidate": candidate},
    )


@pytest.mark.parametrize("code", ["line_count_mismatch", "project_added_reason_123", "z" * 64])
def test_project_reason_vocabulary_is_opaque(code):
    candidate = {"candidate_digest": "sha256:" + "a" * 64, "output_contracts": {"out": {}}}
    reply = {"schema_version": 1, "candidate_digest": candidate["candidate_digest"], "verdict": "rejected", "reason": {"code": code, "output_port": "out"}}
    assert action_verification_response(reply, candidate) == reply


@pytest.mark.parametrize("change", [
    {"candidate_digest": "wrong"}, {"artifact": {"uri": "/replacement"}},
    {"schema_version": True}, {"verdict": "retry"},
    {"reason": {"code": "contains secret text", "output_port": None}},
    {"reason": {"code": "has_newline\n", "output_port": None}},
    {"reason": {"code": "é", "output_port": None}},
    {"reason": {"code": "a" * 65, "output_port": None}},
    {"reason": {"code": "valid", "output_port": "unknown"}},
    {"reason": {"code": "valid", "output_port": None, "message": "secret"}},
])
def test_callback_cannot_inject_data_or_lifecycle_instructions(change):
    candidate = {"candidate_digest": "sha256:" + "a" * 64, "output_contracts": {"out": {}}}
    reply = {"schema_version": 1, "candidate_digest": candidate["candidate_digest"], "verdict": "rejected", "reason": {"code": "valid", "output_port": None}, **change}
    with pytest.raises(ValueError):
        action_verification_response(reply, candidate)


def test_verifier_child_replays_checked_request_and_sanitizes_crash(monkeypatch):
    binding = _binding()
    assert binding.to_dict()["schema_version"] == 9
    assert PreparationChildInput.from_dict(binding.to_dict()) == binding
    seen = []

    def verify(request):
        seen.append(deepcopy(request))
        return {"schema_version": 1, "candidate_digest": request["candidate"]["candidate_digest"], "verdict": "verified"}

    monkeypatch.setitem(sys.modules, "installed_verifier", SimpleNamespace(inspect=verify))
    report = _run_action_verification(binding)
    assert _decode_action_verification_report(report, binding) == report
    assert seen[0]["operation"] == "verify_result"
    assert seen[0]["node_id"] == "consumer"
    assert seen[0]["candidate"]["producer"]["node_id"] == "producer"

    def crash(_request):
        raise RuntimeError("private project exception text")

    monkeypatch.setitem(sys.modules, "installed_verifier", SimpleNamespace(inspect=crash))
    failed = _run_action_verification(binding)
    assert failed["failure_code"] == "action_verification_invalid"
    assert failed["verification"] is None
    assert "private project exception text" not in str(failed)
