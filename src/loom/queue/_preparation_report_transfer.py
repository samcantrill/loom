"""Finite primary/companion framing for the registered preparation output."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, cast

from loom.artifacts import ArtifactRef
from loom.preparation import load_preparation_report
from loom.serialization import PlainData, ensure_plain_data
from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from ._remote_stage_execution import _RemoteOutputArtifact


def native_role(fingerprint: Mapping[str, PlainData]) -> bool:
    from ._remote_stage_execution import _preparation_input_from_fingerprint

    binding = _preparation_input_from_fingerprint(fingerprint)
    return binding is not None and binding.action_verification is None


def header(value: object, total: int) -> dict[str, PlainData]:
    from ._remote_stage_execution import _bounded_size, _digest, _identifier

    plain = ensure_plain_data(value)
    if (
        not isinstance(plain, dict)
        or set(plain) != {"schema_version", "primary", "companion"}
        or type(plain["schema_version"]) is not int
        or plain["schema_version"] != 1
    ):
        raise QueueServiceError(
            "preparation report transfer header version or fields are invalid"
        )
    paths, sizes = [], []
    for role in ("primary", "companion"):
        member = plain[role]
        if not isinstance(member, dict) or set(member) != {
            "path",
            "size_bytes",
            "digest",
        }:
            raise QueueServiceError("preparation report transfer member is invalid")
        name = _identifier(member["path"], "preparation member path")
        if Path(name).name != name or ":" in name:
            raise QueueServiceError(
                "preparation transfer member must be a contained filename"
            )
        paths.append(name)
        sizes.append(_bounded_size(member["size_bytes"]))
        _digest(member["digest"])
    if paths[0] == paths[1] or sum(sizes) != _bounded_size(total):
        raise QueueServiceError("preparation transfer member sizes or paths conflict")
    return plain


def frame(reference: ArtifactRef, path: Path) -> tuple[bytes, dict[str, PlainData]]:
    from ._remote_stage_execution import _read_regular_file_bytes, _bounded_size

    full = load_preparation_report(reference, path)
    del full
    primary = _read_regular_file_bytes(path)
    if reference.checksum != "sha256:" + hashlib.sha256(primary).hexdigest():
        raise QueueConflictError("preparation primary changed after SDK validation")
    import json

    physical = json.loads(primary)
    refs = [
        physical[name]["evidence_ref"]
        for name in ("composition", "requested_composition")
        if name in physical
    ]
    companion_path = path.parent / refs[0]["uri"]
    companion = _read_regular_file_bytes(companion_path)
    if any(
        ref["uri"] != companion_path.name
        or ref["checksum"] != "sha256:" + hashlib.sha256(companion).hexdigest()
        for ref in refs
    ):
        raise QueueConflictError("preparation transfer companion identity conflicts")
    data = primary + companion
    _bounded_size(len(data))
    selected = {
        "schema_version": 1,
        "primary": {
            "path": path.name,
            "size_bytes": len(primary),
            "digest": hashlib.sha256(primary).hexdigest(),
        },
        "companion": {
            "path": companion_path.name,
            "size_bytes": len(companion),
            "digest": hashlib.sha256(companion).hexdigest(),
        },
    }
    return data, header(selected, len(data))


def verify_pair(
    reference: ArtifactRef, path: Path, value: Mapping[str, PlainData]
) -> None:
    from ._remote_stage_execution import _read_regular_file_bytes

    primary, companion = (
        cast(dict[str, PlainData], value["primary"]),
        cast(dict[str, PlainData], value["companion"]),
    )
    if path.name != primary["path"]:
        raise QueueConflictError("preparation primary path conflicts with transfer")
    for member in (primary, companion):
        content = _read_regular_file_bytes(path.parent / cast(str, member["path"]))
        if (
            len(content) != member["size_bytes"]
            or hashlib.sha256(content).hexdigest() != member["digest"]
        ):
            raise QueueConflictError("preparation published member identity conflicts")
    load_preparation_report(reference, path)
    import json

    physical = json.loads(path.read_bytes())
    for name in ("composition", "requested_composition"):
        if name in physical:
            ref = physical[name]["evidence_ref"]
            if ref["uri"] != companion["path"] or ref["checksum"] != "sha256:" + cast(
                str, companion["digest"]
            ):
                raise QueueConflictError(
                    "preparation framed companion binding conflicts"
                )


def publish(
    item: _RemoteOutputArtifact,
    transport_path: Path,
    *,
    target_root: Path | None = None,
) -> ArtifactRef:
    from ._remote_stage_execution import _read_regular_file_bytes
    from ._managed_local import _publish_regular_file_tree, ManagedLocalError
    from loom.pipeline.stores.atomic import atomic_write_bytes

    value = item.preparation_report_transfer
    if value is None:
        raise QueueConflictError("preparation pair transfer header is missing")
    data = _read_regular_file_bytes(transport_path)
    if len(data) != item.size_bytes or hashlib.sha256(data).hexdigest() != item.digest:
        raise QueueConflictError("preparation complete transfer integrity conflicts")
    selected = header(value, len(data))
    primary = cast(dict[str, PlainData], selected["primary"])
    companion = cast(dict[str, PlainData], selected["companion"])
    offset = cast(int, primary["size_bytes"])
    target = target_root or transport_path.parent / "report-publication"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".preparation-pair-", dir=target.parent
    ) as staging:
        source = Path(staging)
        for member, content in ((primary, data[:offset]), (companion, data[offset:])):
            if (
                len(content) != member["size_bytes"]
                or hashlib.sha256(content).hexdigest() != member["digest"]
            ):
                raise QueueConflictError(
                    "preparation framed member integrity conflicts"
                )
            atomic_write_bytes(source / cast(str, member["path"]), content)
        # local_ref verifies the SDK-owned canonical binding before publication.
        item.local_ref(source / cast(str, primary["path"]))
        try:
            _publish_regular_file_tree(
                source_root=source,
                target_root=target,
                aliases={},
                field="preparation report pair",
            )
        except ManagedLocalError as exc:
            raise QueueConflictError(
                "preparation report pair publication conflicts"
            ) from exc
    return item.local_ref(target / cast(str, primary["path"]))
