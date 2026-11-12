"""Physical composition evidence for canonical native preparation reports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_bytes
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.queue.errors import QueueConflictError
from loom.refs import ResourceRef
from loom.serialization import PlainData, ensure_plain_data, stable_json_bytes
from weave.ordered import encode_ordered_config, decode_ordered_config
from weave.errors import ConfigError

PREPARATION_REPORT_SCHEMA_VERSION = 10
SUBMITTED_PREPARATION_REPORT_SCHEMA_VERSION = 11
REPORT_FORMAT = "loom.preparation_report.v2"
_LEGACY_REPORT_FORMAT = "loom.preparation_report.v1"
_COMPOSITION_SCHEMA = "loom.preparation_composition.v2"
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
        or report["schema_version"] not in {PREPARATION_REPORT_SCHEMA_VERSION, SUBMITTED_PREPARATION_REPORT_SCHEMA_VERSION}):
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
            (f"c{i}" for i, prior in enumerate(logical)
             if _equal(prior, composition)
             and all(encode_ordered_config(prior[key]) == encode_ordered_config(composition[key])
                     for key in ("resolved", "redacted", "recipe_manifest"))),
            None,
        )
        if identifier is None:
            identifier = f"c{len(logical)}"
            logical.append(composition)
            manifest = dict(_mapping(composition["manifest"]))
            provenance = dict(_mapping(composition["provenance"]))
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
            compositions[identifier] = {
                "manifest": manifest, "provenance": provenance,
                **{key: encode_ordered_config(composition[key])
                   for key in ("resolved", "redacted", "recipe_manifest")},
            }
        primary[name] = {}
        cast(dict[str, PlainData], primary[name])["evidence_ref"] = ResourceRef(
            uri=path.name,
            resource_type="loom.preparation_composition",
            codec_key="json.v1",
            metadata={
                "document_schema_version": 2,
                "pointer": f"/compositions/{identifier}",
            },
        ).to_dict()
    # Deep tagged trees make indentation far larger than their content.
    # Keep canonical compact bytes and share complete equal configurations once.
    atomic_write_bytes(path, stable_json_bytes({
        "schema": _COMPOSITION_SCHEMA, "schema_version": 2,
        "compositions": compositions,
    }))
    checksum = hash_bytes(path.read_bytes())
    for name in ("composition", "requested_composition"):
        if name in primary:
            _mapping(_mapping(primary[name])["evidence_ref"])["checksum"] = checksum
    return primary


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise QueueConflictError("preparation report closure requires a regular file")
    return path.read_bytes()


def _decoded_mapping(content: bytes) -> dict[str, PlainData]:
    # JSON decoding owns fresh dict/list trees. Validate finite numbers during
    # decoding instead of copying the entire tree solely to normalize it.
    import json
    import math
    from loom.serialization.errors import PlainDataError

    def finite(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise PlainDataError("Invalid non-finite float in preparation evidence")
        return number

    return _mapping(json.loads(content, parse_float=finite, parse_constant=finite))


def load_report(
    reference: ArtifactRef, report_path: str | Path
) -> dict[str, PlainData]:
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
    report = _decoded_mapping(content)
    _require_current_report(report)
    if report.get("report_format") not in {REPORT_FORMAT, _LEGACY_REPORT_FORMAT}:
        raise QueueConflictError(
            "preparation report format is unsupported; regenerate preparation"
        )
    ordered = report["report_format"] == REPORT_FORMAT
    document_version = 2 if ordered else 1
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
        if set(composition) != ({"evidence_ref"} if ordered else _PRIMARY_FIELDS):
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
            or metadata["document_schema_version"] != document_version
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
            companion = _decoded_mapping(companion_bytes)
            if (
                set(companion) != {"schema", "schema_version", "compositions"}
                or companion["schema"] != f"loom.preparation_composition.v{document_version}"
                or type(companion["schema_version"]) is not int
                or companion["schema_version"] != document_version
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
        if identifier in hydrated:
            prior = hydrated[identifier]
            if not ordered and any(not _equal(prior[key], composition[key])
                   for key in ("resolved", "redacted", "recipe_manifest")):
                raise QueueConflictError(
                    "shared preparation composition logical meanings differ"
                )
            # Every reference was checked above. Hydrate shared evidence once,
            # but keep each returned composition independently mutable.
            report[name] = deepcopy(prior)
            continue
        entry = _mapping(entries[identifier])
        if set(entry) != (_LOGICAL_FIELDS if ordered else {"manifest", "provenance"}):
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
            key: (entry if ordered else composition)[key]
            for key in ("resolved", "redacted", "recipe_manifest")
        }
        full.update(manifest=manifest, provenance=provenance)
        hydrated[identifier] = full
        report[name] = full
    if report["report_format"] == REPORT_FORMAT:
        for name in ("composition", "requested_composition"):
            if name not in report:
                continue
            composition = _mapping(report[name])
            for key in ("resolved", "redacted", "recipe_manifest"):
                try:
                    composition[key] = decode_ordered_config(composition[key])
                except ConfigError as exc:
                    raise QueueConflictError(
                        f"preparation ordered configuration {key} is invalid"
                    ) from exc
            if not isinstance(composition["resolved"], dict) or not isinstance(composition["redacted"], dict):
                raise QueueConflictError("preparation ordered configuration must decode to mappings")
            if not isinstance(composition["recipe_manifest"], list):
                raise QueueConflictError("preparation recipe manifest must decode to a sequence")
    return report
