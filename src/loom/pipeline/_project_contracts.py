"""Native checked-project attachments; opaque payloads never enter configuration."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, cast

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.fingerprints import hash_mapping, validate_digest
from loom.pipeline.stores.run_store import RunPreparedRunStore, RunConfigStore, LocalRunStorePaths
from loom.serialization import PlainData, ensure_plain_data

CONTRACT = "loom.project_contract"
CONTRACTS = "loom.project_contracts"
CAPTURE = "loom.project_contract_capture"
REPORT = "loom.project_report"
EXECUTION = "loom.execution_binding"
RESERVED = frozenset({CONTRACT, CONTRACTS, CAPTURE, REPORT, EXECUTION, "loom.remote_recovery", "loom.recovery_binding"})


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
    _check_node_result(result)
    return result


def _plain_mapping_view(value: PlainData) -> dict[str, PlainData]:
    """Read an already normalized tree without copying its opaque payload."""
    if not isinstance(value, dict):
        raise ValueError("project contract must be a plain mapping")
    return value


def _check_node_result(result: dict[str, PlainData]) -> None:
    if set(result) != {"semantic_key", "payload"}:
        raise ValueError("project node contract fields are invalid")
    key = result["semantic_key"]
    if key is not None:
        key = _plain_mapping_view(key)
        if (
            set(key) != {"version", "digest"}
            or type(key["version"]) is not int
            or key["version"] != 1
        ):
            raise ValueError("project semantic key version is unsupported")
        _digest(key["digest"])


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
    _check_envelope(data)
    return data


def _check_envelope(data: dict[str, PlainData]) -> None:
    if (
        set(data)
        != {"schema_version", "namespace", "semantic_key", "payload", "binding_digest"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("native project contract version or fields are unsupported")
    if not isinstance(data["namespace"], str) or not data["namespace"]:
        raise ValueError("project namespace is invalid")
    _check_node_result({key: data[key] for key in ("semantic_key", "payload")})
    _native_digest(data["binding_digest"])


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


def load_contract_report(
    prepared_runs: RunPreparedRunStore, run_uri: str, *,
    config: RunConfigStore, local_paths: LocalRunStorePaths,
) -> dict[str, PlainData] | None:
    from loom.pipeline.stores import LocalArtifactStore

    prepared = prepared_runs.read_prepared_run(run_uri)
    if prepared is None:
        return None
    prepared_metadata = _plain_mapping_view(prepared["metadata"])
    if CONTRACTS not in prepared_metadata:
        return None
    data = report_entry(prepared_metadata[CONTRACTS])
    ref = ArtifactRef.from_dict(data["report_ref"])
    from loom.preparation import load_preparation_report

    artifact_store = LocalArtifactStore(local_paths.local_artifact_root(run_uri))
    report = load_preparation_report(ref, artifact_store.local_path(ref))
    project = _plain_mapping_view(report["project_preparation"])
    processor = _plain_mapping_view(project["processor"])
    if (
        processor["schema_version"] != 3
        or processor["evidence_namespace"] != data["namespace"]
    ):
        raise ValueError("retained report installation namespace conflicts")
    composition = _plain_mapping_view(report["composition"])
    resolved = config.read_config_snapshot(run_uri, "resolved")
    if resolved is None or composition["resolved"] != json.loads(resolved):
        raise ValueError("retained report captured declaration conflicts")
    contracts = _plain_mapping_view(report["project_contracts"])
    for value in contracts.values():
        checked = _plain_mapping_view(value)
        _check_envelope(checked)
        if checked["namespace"] != data["namespace"]:
            raise ValueError("retained node namespace conflicts")
    return report


def worker_contract_metadata(
    prepared_runs: RunPreparedRunStore, run_uri: str, stage: Any, *,
    config: RunConfigStore, local_paths: LocalRunStorePaths,
) -> dict[str, PlainData]:
    report = load_contract_report(prepared_runs, run_uri,
    config=config,
    local_paths=local_paths)
    if report is None:
        return {}
    metadata = _worker_contract_metadata(report, stage)
    prepared = prepared_runs.read_prepared_run(run_uri)
    if prepared is None:
        raise ValueError("retained prepared run is missing")
    entry = report_entry(_plain_mapping_view(prepared["metadata"])[CONTRACTS])
    from loom.pipeline.stores.shared_artifacts import binding

    reference = ArtifactRef.from_dict(entry["report_ref"])
    if binding(reference.metadata) is not None:
        metadata[REPORT] = entry["report_ref"]
    return metadata


def _worker_contract_metadata(
    report: dict[str, PlainData], stage: Any
) -> dict[str, PlainData]:
    """Select one attachment from the freshly checked report owned by the caller."""
    contracts = _plain_mapping_view(report["project_contracts"])
    attached = _plain_mapping_view(contracts[stage.name])
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
    if REPORT in metadata:
        if CONTRACT not in metadata:
            raise ValueError("worker project report requires a checked attachment")
        ArtifactRef.from_dict(plain_mapping(metadata[REPORT]))
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


def validate_admitted_worker(
    prepared_runs: RunPreparedRunStore, request: Any, stage: Any, *,
    config: RunConfigStore, local_paths: LocalRunStorePaths,
) -> None:
    expected = worker_contract_metadata(prepared_runs, request.run_uri, stage,
    config=config,
    local_paths=local_paths)
    actual = {
        key: request.metadata[key]
        for key in (CONTRACT, CAPTURE, REPORT)
        if key in request.metadata
    }
    if plain_mapping(actual) != expected:
        raise ValueError("worker attachment differs from admitted report")
    if {EXECUTION, "loom.remote_recovery", "loom.recovery_binding"}.intersection(request.metadata):
        raise ValueError(
            "worker execution binding must be supplied by assignment authority"
        )


def prepared_contracts_digest(prepared_runs: RunPreparedRunStore, run_uri: str) -> str | None:
    """Bind required attachment existence and its report ref into native intent."""
    record = prepared_runs.read_prepared_run(run_uri)
    if record is None:
        return None
    metadata = _plain_mapping_view(record["metadata"])
    if CONTRACTS not in metadata:
        return None
    entry = metadata[CONTRACTS]
    report_entry(entry)
    return hash_mapping(entry)
