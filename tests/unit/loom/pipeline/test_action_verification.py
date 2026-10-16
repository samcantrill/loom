"""Installed projects own reason vocabulary, while native code owns the wire."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
import sys

import pytest

from loom.fingerprints import hash_mapping
from loom.pipeline._action_verification import action_verification_response
from loom.pipeline._project_contracts import envelope
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.preparation import PreparationChildInput, SharedInputReceipt
from loom.preparation import (
    _decode_action_verification_report,
    _run_action_verification,
    _verify_project_candidate,
)
from loom.queue.errors import QueueConflictError
from loom.serialization import thaw_plain_data


def _candidate():
    revision = {"sequence": 1, "token": "revision"}
    result = {
        "commit": {
            "commit_id": "original",
            "run_uri": "file:///runs/original",
            "stage_name": "producer",
            "attempt_id": "producer-1",
            "committed_at": "2026-09-16T00:00:00Z",
            "revision": revision,
            "output_names": [],
            "materialized_refs": [],
            "supersedes_commit_id": None,
        },
        "artifact_facts": [],
    }
    candidate = {
        "schema_version": 1,
        "namespace": "text-project",
        "semantic_key": {"version": 1, "digest": "a" * 64},
        "execution_key": "sha256:" + "b" * 64,
        "producer": {
            "run_uri": "file:///runs/original",
            "node_id": "producer",
            "attempt_id": "producer-1",
            "assignment_id": "assignment",
            "fencing_token": "fence",
        },
        "result": result,
        "output_contracts": {},
        "installation": {},
        "access": {"mode": "read_only"},
    }
    candidate["candidate_digest"] = hash_mapping(candidate)
    return candidate


def _binding():
    candidate = _candidate()
    contract = envelope(
        "text-project",
        {"semantic_key": candidate["semantic_key"], "payload": {}},
        capture="sha256:" + "c" * 64,
        node="consumer",
        original={},
    )
    return PreparationChildInput(
        "verify-one",
        "profile",
        "pipeline.yaml",
        SharedInputReceipt("sha256:" + "d" * 64, "projects", "capture"),
        ResidentProfileDescriptor(
            "profile", "1", "project", "environment", "executor"
        ).to_dict(),
        local_scope={"agent_id": "agent", "binding_fingerprint": "e" * 64},
        project_preparation={
            "processor": {
                "schema_version": 3,
                "callable": "installed_verifier:inspect",
                "evidence_namespace": "text-project",
                "target_prefix": "text-",
            },
            "target_run_uri": "file:///runs/consumer",
        },
        action_verification={
            "node_id": "consumer",
            "contract": contract,
            "candidate": candidate,
        },
    )


@pytest.mark.parametrize(
    "code", ["line_count_mismatch", "project_added_reason_123", "z" * 64]
)
def test_project_reason_vocabulary_is_opaque(code):
    candidate = {
        "candidate_digest": "sha256:" + "a" * 64,
        "output_contracts": {"out": {}},
    }
    reply = {
        "schema_version": 1,
        "candidate_digest": candidate["candidate_digest"],
        "verdict": "rejected",
        "reason": {"code": code, "output_port": "out"},
    }
    assert action_verification_response(reply, candidate) == reply


@pytest.mark.parametrize(
    "change",
    [
        {"candidate_digest": "wrong"},
        {"artifact": {"uri": "/replacement"}},
        {"schema_version": True},
        {"verdict": "retry"},
        {"reason": {"code": "contains secret text", "output_port": None}},
        {"reason": {"code": "has_newline\n", "output_port": None}},
        {"reason": {"code": "é", "output_port": None}},
        {"reason": {"code": "a" * 65, "output_port": None}},
        {"reason": {"code": "valid", "output_port": "unknown"}},
        {"reason": {"code": "valid", "output_port": None, "message": "secret"}},
    ],
)
def test_callback_cannot_inject_data_or_lifecycle_instructions(change):
    candidate = {
        "candidate_digest": "sha256:" + "a" * 64,
        "output_contracts": {"out": {}},
    }
    reply = {
        "schema_version": 1,
        "candidate_digest": candidate["candidate_digest"],
        "verdict": "rejected",
        "reason": {"code": "valid", "output_port": None},
        **change,
    }
    with pytest.raises(ValueError):
        action_verification_response(reply, candidate)


def test_verifier_child_replays_checked_request_and_sanitizes_crash(
    monkeypatch, capsys
):
    binding = _binding()
    assert binding.to_dict()["schema_version"] == 10
    assert PreparationChildInput.from_dict(binding.to_dict()) == binding
    seen = []

    def verify(request):
        seen.append(deepcopy(request))
        return {
            "schema_version": 1,
            "candidate_digest": request["candidate"]["candidate_digest"],
            "verdict": "verified",
        }

    monkeypatch.setitem(
        sys.modules, "installed_verifier", SimpleNamespace(inspect=verify)
    )
    report = _run_action_verification(binding)
    assert _decode_action_verification_report(report, binding) == report
    assert seen[0]["operation"] == "verify_result"
    assert seen[0]["node_id"] == "consumer"
    assert seen[0]["candidate"]["producer"]["node_id"] == "producer"

    def crash(_request):
        raise RuntimeError("private project exception text")

    monkeypatch.setitem(
        sys.modules, "installed_verifier", SimpleNamespace(inspect=crash)
    )
    failed = _run_action_verification(binding)
    assert failed["failure_code"] == "action_verification_invalid"
    assert failed["verification"] is None
    assert "private project exception text" not in str(failed)
    assert "RuntimeError: private project exception text" in capsys.readouterr().err


def _materialized_report(root, operation):
    from loom._preparation_report import save_composition_evidence
    from loom.pipeline.stores import LocalArtifactStore

    store = LocalArtifactStore(root)
    companion = store.local_artifact_path(
        stage_name="prepare", name="report", codec_key="json.v1"
    ).with_suffix(".composition.json")
    primary = save_composition_evidence(
        {
            "schema_version": 10,
            "operation_id": operation,
            "composition": {
                "resolved": {},
                "redacted": {},
                "recipe_manifest": [],
                "manifest": {"metadata": {"operation": operation}},
                "provenance": {"metadata": {"operation": operation}},
            },
        },
        companion,
    )
    materialized = store.save(
        primary,
        stage_name="prepare",
        name="report",
        artifact_type="json",
        codec_key="json.v1",
    )
    original = replace(
        materialized, uri=f"loom-shared://reports/{operation}/report.json"
    )
    return original, materialized, companion


def test_current_child_carries_action_request_once_and_rejects_retired_input():
    from loom.queue.errors import QueueServiceError
    from loom.serialization import thaw_plain_data

    binding = _binding()
    encoded = binding.to_dict()
    assert encoded["schema_version"] == 10
    assert encoded["purpose"] == {
        "kind": "verify_result", "binding": thaw_plain_data(binding.project_preparation),
        "request": thaw_plain_data(binding.action_verification),
    }
    assert "action_verification" not in encoded
    assert PreparationChildInput.from_dict(encoded) == binding
    assert binding.local_scope is not None
    retired = {**encoded, "schema_version": 9,
               "local_scope": dict(binding.local_scope),
               "project_preparation": thaw_plain_data(binding.project_preparation),
               "action_verification": thaw_plain_data(binding.action_verification)}
    retired.pop("scope")
    retired.pop("purpose")
    with pytest.raises(QueueServiceError, match="unsupported"):
        PreparationChildInput.from_dict(retired)


@pytest.mark.parametrize(
    "role,fault",
    [
        (None, None),
        ("producer", "missing"),
        ("desired", "missing"),
        ("producer", "changed"),
        ("desired", "changed"),
        ("producer", "grant"),
        ("desired", "grant"),
        (None, "swapped"),
    ],
)
def test_result_verifier_checks_both_relocated_report_closures_before_callback(
    tmp_path,
    monkeypatch,
    role,
    fault,
):
    reports = {
        label: _materialized_report(tmp_path / label, label)
        for label in ("producer", "desired")
    }
    binding = _binding()
    requested = cast(dict[str, Any], thaw_plain_data(binding.action_verification))
    candidate = requested["candidate"]
    candidate["access"]["project_reports"] = {
        label: refs[0].to_dict() for label, refs in reports.items()
    }
    candidate["candidate_digest"] = hash_mapping(
        {key: value for key, value in candidate.items() if key != "candidate_digest"}
    )
    binding = replace(binding, action_verification=requested)
    materialized = {label: refs[1].to_dict() for label, refs in reports.items()}
    seen = []

    def verify(request):
        seen.append(request)
        assert (
            request["candidate"]["access"]["project_reports"]
            == candidate["access"]["project_reports"]
        )
        assert request["artifact_access"]["project_reports"] == materialized
        return {
            "schema_version": 1,
            "candidate_digest": candidate["candidate_digest"],
            "verdict": "verified",
        }

    monkeypatch.setitem(
        sys.modules, "installed_verifier", SimpleNamespace(inspect=verify)
    )
    if fault == "missing":
        reports[role][2].unlink()
    elif fault == "changed":
        reports[role][2].write_bytes(b"changed companion")
    elif fault == "grant":
        del materialized[role]
    elif fault == "swapped":
        materialized["producer"], materialized["desired"] = (
            materialized["desired"],
            materialized["producer"],
        )
    if fault is not None:
        with pytest.raises(QueueConflictError):
            _run_action_verification(binding, project_reports=materialized)
        assert seen == []
    else:
        report = _run_action_verification(binding, project_reports=materialized)
        verification = report["verification"]
        assert isinstance(verification, dict)
        assert verification["verdict"] == "verified"
        assert len(seen) == 1


@pytest.mark.parametrize("fault", [None, "missing", "changed", "grant"])
def test_candidate_verifier_checks_relocated_report_closure_before_callback(
    tmp_path,
    monkeypatch,
    fault,
):
    original, materialized, companion = _materialized_report(tmp_path, "original")
    candidate = {
        "artifact_binding": {
            "access": "read_only",
            "project_report": original.to_dict(),
        }
    }
    binding = replace(_binding(), action_verification=None, candidate=candidate)
    seen = []

    def verify(request):
        seen.append(request)
        assert request["candidate"] == candidate
        assert request["artifact_access"]["project_report"] == materialized.to_dict()
        return {
            "schema_version": 1,
            "candidate_digest": hash_mapping(candidate),
            "verdict": "verified",
        }

    monkeypatch.setitem(
        sys.modules, "installed_verifier", SimpleNamespace(inspect=verify)
    )
    if fault == "missing":
        companion.unlink()
    elif fault == "changed":
        companion.write_bytes(b"changed companion")
    supplied = None if fault == "grant" else materialized.to_dict()
    if fault is not None:
        with pytest.raises(QueueConflictError):
            _verify_project_candidate(binding, {}, None, None, project_report=supplied)
        assert seen == []
    else:
        result = _verify_project_candidate(
            binding, {}, None, None, project_report=supplied
        )
        assert result["verdict"] == "verified"
        assert len(seen) == 1
