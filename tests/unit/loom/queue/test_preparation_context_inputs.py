"""Preparation consumers read the primaries published by native input relay."""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.io.uris import uri_to_path
from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.stores import LocalArtifactStore
from loom.queue._remote_stage_execution import (
    _RemoteArtifact,
    _ResidentAssignmentWorkspace,
    _preparation_worker_context,
)
from loom.queue.preparation import (
    LOCAL_PREPARATION_SCOPE,
    PREPARATION_STAGE_TARGET,
    PreparationChildInput,
)
from loom.serialization import thaw_plain_data
from tests.unit.loom.pipeline.test_action_verification import (
    _binding,
    _materialized_report,
)
from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request
from tests.unit.loom.queue.test_staged_preparation_inputs import _receipt


def _relay(tmp_path, profile, binding, references):
    request = _request(profile)
    items = []
    contents = {"input-1": b"input"}
    for i, (name, ref) in enumerate(references.items()):
        item, path = _RemoteArtifact.from_local_ref(
            transfer_id=f"extra-{i}", logical_name=name, ref=ref
        )
        items.append(item)
        contents[item.transfer_id] = path.read_bytes()
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    prepared = StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(
            fingerprint.payload,
            factory_target=PREPARATION_STAGE_TARGET,
            stage_config=binding.to_dict(),
            fingerprint_fields=(
                {LOCAL_PREPARATION_SCOPE: dict(binding.local_scope)}
                if binding.local_scope
                else {}
            ),
        ),
        inputs_summary=fingerprint.inputs_summary,
    )
    request = replace(
        request, fingerprint=prepared.to_dict(), inputs=(*request.inputs, *items)
    )
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    for name, content in contents.items():
        workspace.stage_input(name, content)
    return _preparation_worker_context(request, profile.launch_profile, workspace.root)


@pytest.mark.parametrize("role", ["candidate", "result", "project_report"])
def test_verification_context_reads_relayed_primary(tmp_path, role):
    profile = _profile(tmp_path)
    binding = replace(
        _binding(),
        profile_descriptor=profile.descriptor.to_dict(),
        local_scope={
            "agent_id": "agent",
            "binding_fingerprint": profile.launch_profile.fingerprint,
        },
    )
    _, reference, _ = _materialized_report(tmp_path / "published", "evidence")
    if role == "candidate":
        binding = replace(
            binding,
            action_verification=None,
            candidate={
                "artifact_binding": {
                    "access": "read_only",
                    "project_report": reference.to_dict(),
                },
            },
        )
        name = "candidate_project_report"
    else:
        request = cast(dict[str, Any], thaw_plain_data(binding.action_verification))
        candidate = request["candidate"]
        if role == "result":
            candidate["result"]["commit"]["output_names"] = ["value"]
            candidate["result"]["artifact_facts"] = [
                {
                    "artifact_name": "value",
                    "artifact": reference.to_dict(),
                    "commit_id": "original",
                    "revision": {"sequence": 1, "token": "revision"},
                }
            ]
            candidate["output_contracts"] = {"value": {}}
            name = "action_result_value"
        else:
            candidate["access"]["project_reports"] = {"producer": reference.to_dict()}
            name = "action_project_report_producer"
        candidate["candidate_digest"] = hash_mapping(
            {k: v for k, v in candidate.items() if k != "candidate_digest"}
        )
        binding = replace(binding, action_verification=request)
    context = cast(
        dict[str, Any], _relay(tmp_path, profile, binding, {name: reference})
    )
    purpose = context["purpose"]
    wire = (
        purpose["candidate_project_report"]
        if role == "candidate"
        else purpose["artifacts"]["value"]
        if role == "result"
        else purpose["project_reports"]["producer"]
    )
    materialized = ArtifactRef.from_dict(wire)
    LocalArtifactStore(tmp_path).validate(materialized)
    assert (
        uri_to_path(materialized.uri).read_bytes()
        == uri_to_path(reference.uri).read_bytes()
    )
    assert replace(materialized, uri=reference.uri) == reference


def test_staged_preparation_extracts_relayed_archive_primary(tmp_path):
    profile = _profile(tmp_path)
    receipt = _receipt(tmp_path)
    binding = PreparationChildInput(
        "prepare-staged-001",
        "profile",
        "configs/experiment.yaml",
        receipt,
        profile.descriptor.to_dict(),
    )
    context = cast(
        dict[str, Any],
        _relay(tmp_path, profile, binding, {"preparation_archive": receipt.reference}),
    )
    assert context["input"]["kind"] == "staged"
    assert (
        Path(context["input"]["directory"]) / "configs/experiment.yaml"
    ).read_bytes() == b"pipeline: {}\n"
