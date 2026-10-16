"""Physical composition evidence for canonical native preparation reports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_bytes
from loom.pipeline.stores.atomic import atomic_write_json
from loom.queue.errors import QueueConflictError
from loom.refs import ResourceRef
from loom.serialization import PlainData, ensure_plain_data, stable_json_bytes

PREPARATION_REPORT_SCHEMA_VERSION = 10
REPORT_FORMAT = "loom.preparation_report.v1"
_COMPOSITION_SCHEMA = "loom.preparation_composition.v1"
_LOGICAL_FIELDS = {"resolved", "redacted", "recipe_manifest", "manifest", "provenance"}
_PRIMARY_FIELDS = {"resolved", "redacted", "recipe_manifest", "evidence_ref"}


def _mapping(value: object) -> dict[str, PlainData]:
    if not isinstance(value, dict):
        raise QueueConflictError("preparation composition evidence must be a mapping")
    return cast(dict[str, PlainData], value)


def _equal(left: PlainData, right: PlainData) -> bool:
    # Python equality conflates false/zero; native logical evidence does not.
    return stable_json_bytes(left) == stable_json_bytes(right)


def _require_current_report(report: dict[str, PlainData]) -> None:
    if (type(report.get("schema_version")) is not int
        or report["schema_version"] != PREPARATION_REPORT_SCHEMA_VERSION):
        raise QueueConflictError(
            "preparation report schema is unsupported; regenerate preparation"
        )


def save_composition_evidence(
    report: dict[str, PlainData], companion_path: Path
) -> dict[str, PlainData]:
    """Write the complete companion before exposing its primary report reference."""
    primary = _mapping(ensure_plain_data(report, path="preparation report"))
    _require_current_report(primary)
    primary["report_format"] = REPORT_FORMAT
    compositions: dict[str, PlainData] = {}
    logical: list[dict[str, PlainData]] = []
    path = companion_path
    for name in ("composition", "requested_composition"):
        if name not in primary:
            continue
        composition = _mapping(primary[name])
        if set(composition) != _LOGICAL_FIELDS:
            raise QueueConflictError(
                "preparation logical composition fields are invalid"
            )
        identifier = next(
            (f"c{i}" for i, prior in enumerate(logical) if _equal(prior, composition)),
            None,
        )
        if identifier is None:
            identifier = f"c{len(logical)}"
            logical.append(deepcopy(composition))
            manifest = deepcopy(_mapping(composition["manifest"]))
            provenance = deepcopy(_mapping(composition["provenance"]))
            definition = _mapping(manifest.get("metadata", {}))
            metadata = _mapping(provenance.get("metadata", {}))
            fields = [
                key
                for key in metadata
                if key != "loom_invocation"
                and key in definition
                and _equal(metadata[key], definition[key])
            ]
            if fields:
                provenance["metadata"] = {
                    key: value for key, value in metadata.items() if key not in fields
                }
                provenance["metadata_ref"] = {
                    "pointer": f"/compositions/{identifier}/manifest/metadata",
                    "fields": cast(list[PlainData], fields),
                }
            compositions[identifier] = {"manifest": manifest, "provenance": provenance}
        primary[name] = {
            key: composition[key] for key in ("resolved", "redacted", "recipe_manifest")
        }
        cast(dict[str, PlainData], primary[name])["evidence_ref"] = ResourceRef(
            uri=path.name,
            resource_type="loom.preparation_composition",
            codec_key="json.v1",
            metadata={
                "document_schema_version": 1,
                "pointer": f"/compositions/{identifier}",
            },
        ).to_dict()
    atomic_write_json(
        path,
        {
            "schema": _COMPOSITION_SCHEMA,
            "schema_version": 1,
            "compositions": compositions,
        },
    )
    checksum = hash_bytes(path.read_bytes())
    for name in ("composition", "requested_composition"):
        if name in primary:
            _mapping(_mapping(primary[name])["evidence_ref"])["checksum"] = checksum
    return primary


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise QueueConflictError("preparation report closure requires a regular file")
    return path.read_bytes()


def load_report(
    reference: ArtifactRef, report_path: str | Path
) -> dict[str, PlainData]:
    import json

    path = Path(report_path)
    content = _regular_bytes(path)
    if (
        reference.codec_key != "json.v1"
        or reference.artifact_type != "json"
        or reference.checksum != hash_bytes(content)
    ):
        raise QueueConflictError(
            "preparation primary report identity or checksum conflicts"
        )
    report = _mapping(ensure_plain_data(json.loads(content), path="preparation report"))
    _require_current_report(report)
    if report.get("report_format") != REPORT_FORMAT:
        raise QueueConflictError(
            "preparation report format is unsupported; regenerate preparation"
        )
    hydrated: dict[str, dict[str, PlainData]] = {}
    companion_path: Path | None = None
    companion_checksum: str | None = None
    entries: dict[str, PlainData] | None = None
    for name in ("composition", "requested_composition"):
        if name not in report:
            if name == "composition":
                raise QueueConflictError("preparation composition evidence is missing")
            continue
        composition = _mapping(report[name])
        if set(composition) != _PRIMARY_FIELDS:
            raise QueueConflictError(
                "preparation primary composition fields are invalid"
            )
        raw = _mapping(composition["evidence_ref"])
        ref = ResourceRef.from_dict(raw)
        if (
            set(raw) != set(ref.to_dict())
            or raw != ref.to_dict()
            or ref.resource_type != "loom.preparation_composition"
            or ref.codec_key != "json.v1"
            or ref.schema_version != 1
            or ref.checksum is None
        ):
            raise QueueConflictError(
                "preparation composition reference grammar is invalid"
            )
        if (
            not ref.uri
            or Path(ref.uri).name != ref.uri
            or ref.uri in {".", ".."}
            or "\\" in ref.uri
            or ":" in ref.uri
            or "\x00" in ref.uri
        ):
            raise QueueConflictError(
                "preparation composition reference must be a contained filename"
            )
        metadata = _mapping(raw["metadata"])
        pointer = metadata.get("pointer")
        if (
            set(metadata) != {"document_schema_version", "pointer"}
            or type(metadata["document_schema_version"]) is not int
            or metadata["document_schema_version"] != 1
            or not isinstance(pointer, str)
        ):
            raise QueueConflictError(
                "preparation composition reference projection is invalid"
            )
        parts = pointer.split("/")
        if (
            len(parts) != 3
            or parts[:2] != ["", "compositions"]
            or not parts[2]
            or any(c in parts[2] for c in "~/\\")
        ):
            raise QueueConflictError("preparation composition pointer is invalid")
        identifier = parts[2]
        selected_path = path.parent / ref.uri
        if companion_path is None:
            companion_path, companion_checksum = selected_path, ref.checksum
            companion_bytes = _regular_bytes(selected_path)
            if hash_bytes(companion_bytes) != ref.checksum:
                raise QueueConflictError("preparation composition checksum conflicts")
            companion = _mapping(
                ensure_plain_data(
                    json.loads(companion_bytes), path="preparation composition"
                )
            )
            if (
                set(companion) != {"schema", "schema_version", "compositions"}
                or companion["schema"] != _COMPOSITION_SCHEMA
                or type(companion["schema_version"]) is not int
                or companion["schema_version"] != 1
            ):
                raise QueueConflictError(
                    "preparation composition schema is unsupported"
                )
            entries = _mapping(companion["compositions"])
        elif selected_path != companion_path or ref.checksum != companion_checksum:
            raise QueueConflictError(
                "preparation report requires one complete companion"
            )
        assert entries is not None
        if identifier not in entries:
            raise QueueConflictError("preparation addressed composition is missing")
        entry = deepcopy(_mapping(entries[identifier]))
        if set(entry) != {"manifest", "provenance"}:
            raise QueueConflictError("preparation composition entry fields are invalid")
        manifest = _mapping(entry["manifest"])
        provenance = _mapping(entry["provenance"])
        if "metadata_ref" in provenance:
            projection = _mapping(provenance.pop("metadata_ref"))
            fields = projection.get("fields")
            if (
                set(projection) != {"pointer", "fields"}
                or projection["pointer"]
                != f"/compositions/{identifier}/manifest/metadata"
                or not isinstance(fields, list)
                or any(not isinstance(field, str) for field in fields)
                or len(fields) != len(set(fields))
                or "loom_invocation" in fields
            ):
                raise QueueConflictError("preparation metadata projection is invalid")
            definition = _mapping(manifest.get("metadata"))
            inline = _mapping(provenance.get("metadata"))
            if set(inline).intersection(fields) or not set(fields) <= set(definition):
                raise QueueConflictError(
                    "preparation metadata projection overlaps or names missing fields"
                )
            provenance["metadata"] = {
                **inline,
                **{
                    cast(str, field): deepcopy(definition[cast(str, field)])
                    for field in fields
                },
            }
        full = {
            key: deepcopy(composition[key])
            for key in ("resolved", "redacted", "recipe_manifest")
        }
        full.update(manifest=manifest, provenance=provenance)
        if identifier in hydrated and not _equal(hydrated[identifier], full):
            raise QueueConflictError(
                "shared preparation composition logical meanings differ"
            )
        hydrated[identifier] = full
        report[name] = full
    return report
