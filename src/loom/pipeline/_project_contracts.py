"""Native checked-project attachments; opaque payloads never enter configuration."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, cast

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.fingerprints import hash_mapping, validate_digest
from loom.serialization import PlainData, ensure_plain_data

CONTRACT = "loom.project_contract"
CONTRACTS = "loom.project_contracts"
CAPTURE = "loom.project_contract_capture"
EXECUTION = "loom.execution_binding"
RESERVED = frozenset({CONTRACT, CONTRACTS, CAPTURE, EXECUTION, "loom.remote_recovery", "loom.recovery_binding"})


def reject_overrides(metadata: Mapping[str, object] | None) -> None:
    if RESERVED.intersection(metadata or {}):
        raise ValueError("native project metadata is reserved")


def plain_mapping(value: object) -> dict[str, PlainData]:
    plain = ensure_plain_data(value, path="project contract")
    if not isinstance(plain, dict):
        raise ValueError("project contract must be a plain mapping")
    return plain


def _digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("project contract digest is invalid")


def _native_digest(value: object) -> None:
    from loom.errors import FingerprintError

    try:
        validate_digest(value)
    except FingerprintError as exc:
        raise ValueError("native project binding digest is invalid") from exc


def node_result(value: object) -> dict[str, PlainData]:
    result = plain_mapping(value)
    if set(result) != {"semantic_key", "payload"}:
        raise ValueError("project node contract fields are invalid")
    key = result["semantic_key"]
    if key is not None:
        key = plain_mapping(key)
        if (
            set(key) != {"version", "digest"}
            or type(key["version"]) is not int
            or key["version"] != 1
        ):
            raise ValueError("project semantic key version is unsupported")
        _digest(key["digest"])
    return result


def declaration(stage: Any) -> dict[str, PlainData]:
    """Normalize the original factory/config/input/output declaration once."""
    return {
        "factory_target": stage.target_path,
        "factory_init": dict(stage.factory.init),
        "stage_config": dict(stage.stage_config),
        "declared_inputs": dict(stage.inputs),
        "declared_outputs": {
            name: {
                "artifact_type": output.artifact_type,
                "codec_key": output.codec_key,
                "schema_version": output.schema_version,
                "metadata": dict(output.metadata),
            }
            for name, output in stage.outputs.items()
        },
    }


def capture_digest(report: Mapping[str, PlainData]) -> str:
    return hash_mapping(
        {
            key: report[key]
            for key in (
                "operation_id",
                "input_manifest_digest",
                "invocation",
                "profile_descriptor",
            )
        }
    )


def envelope(
    namespace: str,
    result: object,
    *,
    capture: str,
    node: str,
    original: Mapping[str, PlainData],
) -> dict[str, PlainData]:
    fields: dict[str, PlainData] = {
        "schema_version": 1,
        "namespace": namespace,
        **node_result(result),
    }
    return {
        **fields,
        "binding_digest": hash_mapping(
            {
                "capture_digest": capture,
                "node_id": node,
                "declaration": dict(original),
                "attachment": fields,
            }
        ),
    }


def validate_envelope(value: object) -> dict[str, PlainData]:
    data = plain_mapping(value)
    if (
        set(data)
        != {"schema_version", "namespace", "semantic_key", "payload", "binding_digest"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("native project contract version or fields are unsupported")
    if not isinstance(data["namespace"], str) or not data["namespace"]:
        raise ValueError("project namespace is invalid")
    node_result({key: data[key] for key in ("semantic_key", "payload")})
    _native_digest(data["binding_digest"])
    return data


def report_entry(value: object) -> dict[str, PlainData]:
    entry = plain_mapping(value)
    data = plain_mapping(entry.get("data"))
    if (
        set(entry) != {"kind", "data"}
        or entry["kind"] != "project_contracts"
        or set(data) != {"schema_version", "namespace", "report_ref"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("prepared project report reference is invalid")
    if not isinstance(data["namespace"], str) or not data["namespace"]:
        raise ValueError("prepared project namespace is invalid")
    try:
        ref = ArtifactRef.from_dict(data["report_ref"])
    except ArtifactValidationError as exc:
        raise ValueError("prepared project report reference is invalid") from exc
    if (
        ref.checksum is None
        or ref.producer_stage != "prepare"
        or ref.artifact_type != "json"
        or ref.codec_key != "json.v1"
    ):
        raise ValueError(
            "prepared project reference must name a native preparation report"
        )
    return data


def load_contract_report(store: Any, run_uri: str) -> dict[str, PlainData] | None:
    from loom.pipeline.stores import LocalArtifactStore

    prepared = store.read_prepared_run(run_uri)
    if prepared is None or CONTRACTS not in prepared["metadata"]:
        return None
    data = report_entry(prepared["metadata"][CONTRACTS])
    ref = ArtifactRef.from_dict(data["report_ref"])
    report = plain_mapping(
        LocalArtifactStore(store.local_artifact_root(run_uri)).load(ref)
    )
    project = plain_mapping(report["project_preparation"])
    processor = plain_mapping(project["processor"])
    if (
        processor["schema_version"] != 3
        or processor["evidence_namespace"] != data["namespace"]
    ):
        raise ValueError("retained report installation namespace conflicts")
    composition = plain_mapping(report["composition"])
    if composition["resolved"] != json.loads(
        store.read_config_snapshot(run_uri, "resolved")
    ):
        raise ValueError("retained report captured declaration conflicts")
    contracts = plain_mapping(report["project_contracts"])
    for value in contracts.values():
        if validate_envelope(value)["namespace"] != data["namespace"]:
            raise ValueError("retained node namespace conflicts")
    return report


def worker_contract_metadata(
    store: Any, run_uri: str, stage: Any
) -> dict[str, PlainData]:
    report = load_contract_report(store, run_uri)
    if report is None:
        return {}
    contracts = plain_mapping(report["project_contracts"])
    attached = validate_envelope(contracts[stage.name])
    capture = capture_digest(report)
    expected = envelope(
        cast(str, attached["namespace"]),
        {key: attached[key] for key in ("semantic_key", "payload")},
        capture=capture,
        node=stage.name,
        original=declaration(stage),
    )
    if attached != expected:
        raise ValueError("retained project node binding conflicts")
    return {CONTRACT: attached, CAPTURE: capture}


def validate_worker_metadata(
    metadata: Mapping[str, PlainData], *, node: str, attempt: int, fingerprint: Any
) -> None:
    if CONTRACTS in metadata:
        raise ValueError("a worker cannot receive whole-graph contracts")
    if (CONTRACT in metadata) != (CAPTURE in metadata):
        raise ValueError("worker project capture or attachment is missing")
    if CONTRACT in metadata:
        attached = validate_envelope(metadata[CONTRACT])
        capture = metadata[CAPTURE]
        _native_digest(capture)
        payload = fingerprint.payload.to_dict()
        original = {
            key: payload[key]
            for key in (
                "factory_target",
                "factory_init",
                "stage_config",
                "declared_inputs",
                "declared_outputs",
            )
        }
        if attached != envelope(
            cast(str, attached["namespace"]),
            {key: attached[key] for key in ("semantic_key", "payload")},
            capture=cast(str, capture),
            node=node,
            original=original,
        ):
            raise ValueError("worker project declaration binding conflicts")
    if EXECUTION in metadata:
        binding = plain_mapping(metadata[EXECUTION])
        if (
            set(binding)
            != {
                "schema_version",
                "origin_run_id",
                "origin_node_id",
                "attempt",
                "environment_fingerprint",
                "run_state_root",
            }
            or type(binding["schema_version"]) is not int
            or binding["schema_version"] != 1
        ):
            raise ValueError("execution binding version or fields are invalid")
        if (
            binding["origin_node_id"] != node
            or type(binding["attempt"]) is not int
            or binding["attempt"] != attempt
        ):
            raise ValueError("execution binding attempt or node conflicts")
        for key in ("origin_run_id", "origin_node_id", "environment_fingerprint"):
            if not isinstance(binding[key], str) or not binding[key]:
                raise ValueError("execution binding identity is invalid")
        root = binding["run_state_root"]
        if root is not None:
            from pathlib import Path

            if not isinstance(root, str) or not Path(root).is_absolute():
                raise ValueError("execution binding state root is invalid")


def validate_admitted_worker(store: Any, request: Any, stage: Any) -> None:
    expected = worker_contract_metadata(store, request.run_uri, stage)
    actual = {
        key: request.metadata[key]
        for key in (CONTRACT, CAPTURE)
        if key in request.metadata
    }
    if plain_mapping(actual) != expected:
        raise ValueError("worker attachment differs from admitted report")
    if {EXECUTION, "loom.remote_recovery", "loom.recovery_binding"}.intersection(request.metadata):
        raise ValueError(
            "worker execution binding must be supplied by assignment authority"
        )


def prepared_contracts_digest(store: Any, run_uri: str) -> str | None:
    """Bind required attachment existence and its report ref into native intent."""
    record = store.read_prepared_run(run_uri)
    if record is None or CONTRACTS not in record["metadata"]:
        return None
    entry = record["metadata"][CONTRACTS]
    report_entry(entry)
    return hash_mapping(entry)
