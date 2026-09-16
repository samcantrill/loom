"""Native action-candidate and installed-verifier boundary codecs."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import cast

from loom.fingerprints import hash_mapping, validate_digest
from loom.pipeline._project_contracts import plain_mapping, validate_envelope
from loom.pipeline.stores.read_models import ArtifactFactRecord, OutputCommitRecord
from loom.serialization import PlainData


def action_candidate(value: object) -> dict[str, PlainData]:
    candidate = plain_mapping(value)
    if set(candidate) != {"schema_version", "candidate_digest", "namespace", "semantic_key", "execution_key", "producer", "result", "output_contracts", "installation", "access"} or type(candidate["schema_version"]) is not int or candidate["schema_version"] != 1:
        raise ValueError("invalid action candidate fields")
    if candidate["candidate_digest"] != hash_mapping({key: item for key, item in candidate.items() if key != "candidate_digest"}):
        raise ValueError("action candidate digest conflicts")
    validate_digest(candidate["execution_key"], algorithms={"sha256"})
    producer = plain_mapping(candidate["producer"])
    if set(producer) != {"run_uri", "node_id", "attempt_id", "assignment_id", "fencing_token"} or any(not isinstance(item, str) or not item for item in producer.values()):
        raise ValueError("invalid original action producer")
    result = plain_mapping(candidate["result"])
    if set(result) != {"commit", "artifact_facts"} or not isinstance(result["artifact_facts"], list):
        raise ValueError("invalid action result facts")
    commit = OutputCommitRecord.from_dict(result["commit"])
    facts = tuple(ArtifactFactRecord.from_dict(item) for item in result["artifact_facts"])
    if (producer["run_uri"], producer["node_id"], producer["attempt_id"]) != (commit.run_uri, commit.stage_name, commit.attempt_id):
        raise ValueError("action candidate original commit conflicts")
    outputs = plain_mapping(candidate["output_contracts"])
    if set(outputs) != set(commit.output_names) or {fact.artifact_name for fact in facts} != set(outputs) or len(facts) != len(outputs) or any(fact.commit_id != commit.commit_id for fact in facts):
        raise ValueError("action candidate output closure conflicts")
    plain_mapping(candidate["installation"])
    plain_mapping(candidate["access"])
    return candidate


def action_verification_request(value: object) -> dict[str, PlainData]:
    request = plain_mapping(value)
    if set(request) != {"node_id", "contract", "candidate"} or not isinstance(request["node_id"], str) or not request["node_id"]:
        raise ValueError("invalid action verification request")
    contract = validate_envelope(request["contract"])
    candidate = action_candidate(request["candidate"])
    if contract["semantic_key"] is None or contract["semantic_key"] != candidate["semantic_key"] or contract["namespace"] != candidate["namespace"]:
        raise ValueError("action candidate checked contract conflicts")
    return request


def action_verification_response(value: object, candidate: Mapping[str, PlainData]) -> dict[str, PlainData]:
    """Accept only a candidate-bound verdict and opaque bounded project reason."""
    response = plain_mapping(value)
    base = {"schema_version", "candidate_digest", "verdict"}
    if type(response.get("schema_version")) is not int or response["schema_version"] != 1 or response.get("candidate_digest") != candidate["candidate_digest"]:
        raise ValueError("action verification candidate identity conflicts")
    if response.get("verdict") == "verified" and set(response) == base:
        return response
    if response.get("verdict") != "rejected" or set(response) != base | {"reason"}:
        raise ValueError("invalid action verification verdict")
    reason = plain_mapping(response["reason"])
    if set(reason) != {"code", "output_port"} or not isinstance(reason["code"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason["code"], flags=re.ASCII) is None:
        raise ValueError("invalid action verification reason")
    port = reason["output_port"]
    if port is not None and (not isinstance(port, str) or port not in cast(Mapping[str, PlainData], candidate["output_contracts"])):
        raise ValueError("action verification output port conflicts")
    return response
