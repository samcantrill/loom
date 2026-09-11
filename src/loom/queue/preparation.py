"""Finite, durable-value models and shared-storage capture for preparation.

This module deliberately contains no composition or worker imports.  It is the
native boundary between an authored project tree and the coordinator's managed
preparation lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
from typing import cast
from uuid import uuid4

from loom.artifacts import ArtifactRef
from loom.fingerprints import format_digest, hash_mapping, validate_digest
from loom.io.uris import path_to_file_uri
from loom.serialization import PlainData, stable_json_bytes, thaw_plain_data

from .errors import QueueServiceError
from .models import validate_queue_id


_MAX_INCLUDES = 100
_MAX_FILES = 4096
_MAX_BYTES = 64 * 1024 * 1024
PREPARATION_STAGE_TARGET = "loom.preparation.PreparationStage"
PREPARATION_INPUT_CAPABILITY = "preparation-input-v1"
PREPARATION_STAGED_INPUT_CAPABILITY = "preparation-staged-input-v1"
PREPARATION_INPUT_CONTEXT_ENV = "LOOM_PREPARATION_INPUT_CONTEXT"


def _relative(value: object, field: str, *, dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise QueueServiceError(
            f"preparation {field} must be a non-empty relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or (path == PurePosixPath(".") and not dot)
    ):
        raise QueueServiceError(
            f"preparation {field} must be a contained relative path"
        )
    if field == "include" and any(char in value for char in "*?[]"):
        raise QueueServiceError(
            "preparation includes must be explicit paths, not glob expressions"
        )
    return str(path)


@dataclass(frozen=True, slots=True)
class PreparationSource:
    """One protected-root project selection; only ``shared`` is executable here."""

    mode: str
    root: str
    path: str
    include: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in {"shared", "staged"}:
            raise QueueServiceError("preparation source mode is invalid")
        validate_queue_id(self.root, "preparation source root")
        object.__setattr__(self, "path", _relative(self.path, "source path", dot=True))
        if not isinstance(self.include, (tuple, list)):
            raise QueueServiceError("preparation includes must contain explicit paths")
        values = tuple(_relative(item, "include", dot=True) for item in self.include)
        if not values or len(values) > _MAX_INCLUDES:
            raise QueueServiceError("preparation includes must contain 1..100 paths")
        # Repeated and nested selections describe the same closure and intent.
        unique = sorted(set(values))
        normalized = tuple(
            item
            for item in unique
            if not any(
                parent != item and (parent == "." or item.startswith(parent + "/"))
                for parent in unique
            )
        )
        object.__setattr__(self, "include", normalized)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": self.mode,
            "root": self.root,
            "path": self.path,
            "include": list(self.include),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PreparationSource":
        if set(data) != {"mode", "root", "path", "include"} or not isinstance(
            data.get("include"), list
        ):
            raise QueueServiceError("preparation source is invalid")
        return cls(
            cast(str, data["mode"]),
            cast(str, data["root"]),
            cast(str, data["path"]),
            tuple(cast(list[str], data["include"])),
        )


@dataclass(frozen=True, slots=True)
class PrepareRunRequest:
    """Coordinator-owned request for one idempotent preparation operation."""

    operation_id: str
    run_name: str
    source: PreparationSource
    config_path: str
    preparation_profile: str

    def __post_init__(self) -> None:
        from .managed_local_preparation import _validate_run_name

        validate_queue_id(self.operation_id, "operation_id")
        validate_queue_id(self.preparation_profile, "preparation_profile")
        _validate_run_name(self.run_name)
        if not isinstance(self.source, PreparationSource):
            raise QueueServiceError("preparation source is invalid")
        object.__setattr__(
            self, "config_path", _relative(self.config_path, "config_path")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "run_name": self.run_name,
            "source": self.source.to_dict(),
            "config_path": self.config_path,
            "preparation_profile": self.preparation_profile,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PrepareRunRequest":
        if set(data) != {
            "operation_id",
            "run_name",
            "source",
            "config_path",
            "preparation_profile",
        } or not isinstance(data.get("source"), Mapping):
            raise QueueServiceError("prepare request is invalid")
        return cls(
            cast(str, data["operation_id"]),
            cast(str, data["run_name"]),
            PreparationSource.from_dict(cast(Mapping[str, object], data["source"])),
            cast(str, data["config_path"]),
            cast(str, data["preparation_profile"]),
        )

    def intent_digest(self, principal_id: str) -> str:
        if not isinstance(principal_id, str) or not principal_id:
            raise QueueServiceError("preparation principal is invalid")
        value = {"request": self.to_dict(), "principal_id": principal_id}
        return hash_mapping(value)


@dataclass(frozen=True, slots=True)
class SharedInputReceipt:
    """Identity of a completed capture below one protected shared-root alias."""

    manifest_digest: str
    root: str
    path: str

    def __post_init__(self) -> None:
        validate_digest(self.manifest_digest, algorithms={"sha256"})
        validate_queue_id(self.root, "preparation source root")
        object.__setattr__(self, "path", _relative(self.path, "snapshot path"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": "shared",
            "manifest_digest": self.manifest_digest,
            "reference": {
                "schema_version": 1,
                "kind": "loom.shared-preparation-input",
                "root": self.root,
                "path": self.path,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SharedInputReceipt":
        reference = data.get("reference")
        if (
            set(data) != {"mode", "manifest_digest", "reference"}
            or data.get("mode") != "shared"
            or not isinstance(reference, Mapping)
            or set(reference) != {"schema_version", "kind", "root", "path"}
            or type(reference.get("schema_version")) is not int
            or reference.get("schema_version") != 1
            or reference.get("kind") != "loom.shared-preparation-input"
        ):
            raise QueueServiceError("preparation shared input receipt is invalid")
        return cls(
            cast(str, data["manifest_digest"]),
            cast(str, reference["root"]),
            cast(str, reference["path"]),
        )


@dataclass(frozen=True, slots=True)
class StagedInputReceipt:
    """Identity of a completed archive capture for one preparation operation."""

    manifest_digest: str
    reference: ArtifactRef

    def __post_init__(self) -> None:
        validate_digest(self.manifest_digest, algorithms={"sha256"})
        if not isinstance(self.reference, ArtifactRef):
            raise QueueServiceError("preparation staged input reference is invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": "staged",
            "manifest_digest": self.manifest_digest,
            "reference": cast(PlainData, self.reference.to_dict()),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "StagedInputReceipt":
        reference = data.get("reference")
        if (
            set(data) != {"mode", "manifest_digest", "reference"}
            or data.get("mode") != "staged"
            or not isinstance(reference, Mapping)
        ):
            raise QueueServiceError("preparation staged input receipt is invalid")
        try:
            normalized = thaw_plain_data(reference)
            if not isinstance(normalized, dict):
                raise ValueError("preparation staged input reference is not a mapping")
            artifact = ArtifactRef.from_dict(normalized)
        except Exception as exc:
            raise QueueServiceError(
                "preparation staged input receipt is invalid"
            ) from exc
        return cls(cast(str, data["manifest_digest"]), artifact)


PreparationInputReceipt = SharedInputReceipt | StagedInputReceipt


@dataclass(frozen=True, slots=True)
class _CapturedSource:
    project: Path
    files: Mapping[str, os.stat_result]
    contents: Mapping[str, bytes]
    manifest: Mapping[str, PlainData]
    digest: str


def input_receipt_from_dict(data: Mapping[str, object]) -> PreparationInputReceipt:
    """Decode exactly one persisted shared or staged preparation input receipt."""
    mode = data.get("mode")
    if mode == "shared":
        return SharedInputReceipt.from_dict(data)
    if mode == "staged":
        return StagedInputReceipt.from_dict(data)
    raise QueueServiceError("preparation input receipt is invalid")


@dataclass(frozen=True, slots=True)
class PreparationChildInput:
    """Finite shared input for the fixed preparation stage, never a generic path binding."""

    operation_id: str
    preparation_profile: str
    config_path: str
    input_receipt: PreparationInputReceipt
    profile_descriptor: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        from types import MappingProxyType
        from ._remote_stage_execution import ResidentProfileDescriptor

        validate_queue_id(self.operation_id, "preparation operation_id")
        validate_queue_id(self.preparation_profile, "preparation_profile")
        object.__setattr__(
            self, "config_path", _relative(self.config_path, "config_path")
        )
        if not isinstance(self.input_receipt, (SharedInputReceipt, StagedInputReceipt)):
            raise QueueServiceError("preparation child input receipt is invalid")
        descriptor = ResidentProfileDescriptor.from_dict(self.profile_descriptor)
        object.__setattr__(
            self, "profile_descriptor", MappingProxyType(descriptor.to_dict())
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": 1,
            "operation_id": self.operation_id,
            "preparation_profile": self.preparation_profile,
            "config_path": self.config_path,
            "input_receipt": self.input_receipt.to_dict(),
            "profile_descriptor": dict(self.profile_descriptor),
        }

    @classmethod
    def from_dict(cls, value: object) -> "PreparationChildInput":
        if (
            not isinstance(value, Mapping)
            or set(value)
            != {
                "schema_version",
                "operation_id",
                "preparation_profile",
                "config_path",
                "input_receipt",
                "profile_descriptor",
            }
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1
            or not isinstance(value.get("input_receipt"), Mapping)
        ):
            raise QueueServiceError("preparation child input is invalid")
        return cls(
            cast(str, value["operation_id"]),
            cast(str, value["preparation_profile"]),
            cast(str, value["config_path"]),
            input_receipt_from_dict(value["input_receipt"]),
            cast(Mapping[str, PlainData], value["profile_descriptor"]),
        )


def _capture_selected_source(
    request: PrepareRunRequest, source_root: Path
) -> _CapturedSource:
    """Read the existing finite selection once and build its native manifest."""
    project = _contained_path(source_root.absolute(), request.source.path)
    _require_directory(project)
    files = _selected_files(project, request.source.include)
    if request.config_path not in files:
        raise QueueServiceError("preparation config_path is not included")
    manifest: list[PlainData] = []
    contents: dict[str, bytes] = {}
    total = 0
    for relative, details in sorted(files.items()):
        data = _read_regular_file(
            project, relative, _MAX_BYTES - total, expected=details
        )
        total += len(data)
        contents[relative] = data
        manifest.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    encoded: dict[str, PlainData] = {"schema_version": 1, "files": manifest}
    return _CapturedSource(project, files, contents, encoded, hash_mapping(encoded))


def _verify_source_unchanged(
    request: PrepareRunRequest, captured: _CapturedSource
) -> None:
    """Refuse publication when the selected authoring closure changed mid-capture."""
    try:
        if _file_identities(
            _selected_files(captured.project, request.source.include)
        ) != _file_identities(captured.files):
            raise QueueServiceError("preparation source_changed")
        for relative, original in captured.contents.items():
            if (
                _read_regular_file(
                    captured.project,
                    relative,
                    len(original),
                    expected=captured.files[relative],
                )
                != original
            ):
                raise QueueServiceError("preparation source_changed")
    except (OSError, QueueServiceError) as exc:
        raise QueueServiceError("preparation source_changed") from exc


def capture_shared_input(
    request: PrepareRunRequest,
    *,
    source_root: Path,
    snapshot_root: Path,
    owner_id: str | None = None,
) -> SharedInputReceipt:
    """Publish a bounded, verified capture before returning its shared reference.

    Captured files live in ``files/`` alongside ``manifest.json``. This keeps an
    authored file named manifest.json distinct from Loom's capture evidence.
    Detected byte, identity or selection changes fail without a ready receipt;
    a mutable authoring directory is not an atomic revision snapshot.
    """
    if request.source.mode != "shared":
        raise QueueServiceError("staged preparation input is unsupported")
    staging: Path | None = None
    try:
        capture = _capture_selected_source(request, source_root)
        digest = capture.digest
        # IDs keep their native syntax; directory names are bounded independently.
        operation_key = _capture_operation_key(request.operation_id, owner_id)
        relative = f"{operation_key}-{digest.removeprefix('sha256:')}"
        snapshot_root = snapshot_root.absolute()
        snapshot_root.mkdir(parents=True, exist_ok=True)
        _require_directory(snapshot_root)
        destination = snapshot_root / relative
        if destination.exists() or destination.is_symlink():
            _verify_capture(destination, digest)
            return SharedInputReceipt(digest, request.source.root, relative)
        staging = snapshot_root / f".{operation_key}.tmp-{uuid4().hex}"
        staging.mkdir()
        captured = staging / "files"
        captured.mkdir()
        for rel, data in capture.contents.items():
            output = captured / rel
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_durable(output, data)
        _verify_source_unchanged(request, capture)
        _write_durable(staging / "manifest.json", stable_json_bytes(capture.manifest))
        _verify_capture(staging, digest)
        for directory, _, _ in os.walk(staging, topdown=False):
            _sync_directory(Path(directory))
        try:
            staging.rename(destination)
        except FileExistsError:
            # Concurrent recovery can only reuse the exact complete capture.
            _verify_capture(destination, digest)
            shutil.rmtree(staging)
        staging = None
        _sync_directory(snapshot_root)
        return SharedInputReceipt(digest, request.source.root, relative)
    except OSError as exc:
        raise QueueServiceError("preparation source_unavailable") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def capture_staged_input(
    request: PrepareRunRequest,
    *,
    source_root: Path,
    artifact_root: Path,
    owner_id: str | None = None,
) -> StagedInputReceipt:
    """Commit one bounded preparation archive after verifying its source closure.

    The returned reference identifies a regular tar archive below the coordinator's
    protected artifact root.  It becomes visible only after the finite source
    selection has been reread, so an authoring change cannot publish a ready
    staged receipt.
    """
    if request.source.mode != "staged":
        raise QueueServiceError("shared preparation input is not a staged capture")
    staging: Path | None = None
    try:
        capture = _capture_selected_source(request, source_root)
        digest = capture.digest
        operation_key = _capture_operation_key(request.operation_id, owner_id)
        relative = f"{operation_key}-{digest.removeprefix('sha256:')}.tar"
        artifact_root = artifact_root.absolute()
        artifact_root.mkdir(parents=True, exist_ok=True)
        _require_directory(artifact_root)
        destination = artifact_root / relative
        if destination.exists() or destination.is_symlink():
            _verify_staged_archive(destination, digest, artifact_root)
            return _staged_archive_receipt(destination, digest, operation_key)
        staging = artifact_root / f".{operation_key}.tmp-{uuid4().hex}.tar"
        _write_staged_archive(staging, capture.manifest, capture.contents)
        _require_staged_archive_within_transfer_limit(staging)
        _verify_source_unchanged(request, capture)
        try:
            staging.rename(destination)
        except FileExistsError:
            _verify_staged_archive(destination, digest, artifact_root)
            staging.unlink()
        staging = None
        _sync_directory(artifact_root)
        return _staged_archive_receipt(destination, digest, operation_key)
    except OSError as exc:
        raise QueueServiceError("preparation source_unavailable") from exc
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def discard_staged_input_temporaries(
    request: PrepareRunRequest, *, artifact_root: Path, owner_id: str
) -> None:
    """Remove only interrupted archive writes owned by this operation."""
    if not artifact_root.exists():
        return
    _require_directory(artifact_root)
    prefix = f".{_capture_operation_key(request.operation_id, owner_id)}.tmp-"
    for candidate in artifact_root.iterdir():
        suffix = candidate.name.removeprefix(prefix)
        if (
            candidate.name.startswith(prefix)
            and suffix.endswith(".tar")
            and len(suffix.removesuffix(".tar")) == 32
            and all(char in "0123456789abcdef" for char in suffix.removesuffix(".tar"))
        ):
            details = candidate.lstat()
            if stat.S_ISREG(details.st_mode):
                candidate.unlink()
    _sync_directory(artifact_root)


def resolve_staged_input(
    receipt: StagedInputReceipt, *, archive_path: Path, workspace_root: Path
) -> Path:
    """Extract and verify a relayed archive below one assignment workspace.

    A complete replay only verifies the existing immutable extraction. Failed
    extraction removes its private temporary directory and never exposes it as a
    preparation input.
    """
    if not isinstance(receipt, StagedInputReceipt):
        raise QueueServiceError("preparation staged input receipt is invalid")
    try:
        _require_staged_archive_within_transfer_limit(archive_path)
        _verify_archive_checksum(archive_path, receipt.reference.checksum)
        workspace_root = workspace_root.absolute()
        _require_directory(workspace_root)
        name = "preparation-input-" + receipt.manifest_digest.removeprefix("sha256:")
        destination = workspace_root / name
        if destination.exists() or destination.is_symlink():
            return _verify_capture(destination, receipt.manifest_digest)
        _discard_extraction_temporaries(workspace_root, name)
        staging = workspace_root / f".{name}.tmp-{uuid4().hex}"
        staging.mkdir()
        try:
            _unpack_staged_archive(archive_path, staging, receipt.manifest_digest)
            try:
                staging.rename(destination)
            except FileExistsError:
                verified = _verify_capture(destination, receipt.manifest_digest)
                shutil.rmtree(staging)
                return verified
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _sync_directory(workspace_root)
        return _verify_capture(destination, receipt.manifest_digest)
    except OSError as exc:
        raise QueueServiceError("preparation staged archive is unavailable") from exc


def _staged_archive_receipt(
    path: Path, manifest_digest: str, operation_key: str
) -> StagedInputReceipt:
    return StagedInputReceipt(
        manifest_digest,
        ArtifactRef(
            artifact_id=f"preparation-inputs/{operation_key}",
            uri=path_to_file_uri(path.absolute()),
            artifact_type="bytes",
            codec_key="bytes.v1",
            checksum=_file_checksum(path),
            metadata={
                "manifest_digest": manifest_digest,
                "size_bytes": path.stat().st_size,
            },
        ),
    )


def _write_staged_archive(
    path: Path, manifest: Mapping[str, PlainData], contents: Mapping[str, bytes]
) -> None:
    """Write the deterministic regular-file archive before publication."""
    with tarfile.open(path, "x", format=tarfile.PAX_FORMAT) as archive:
        _add_archive_member(archive, "manifest.json", stable_json_bytes(manifest))
        for relative, data in sorted(contents.items()):
            _add_archive_member(archive, f"files/{relative}", data)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _add_archive_member(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = 0o644
    member.mtime = 0
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    archive.addfile(member, io.BytesIO(data))


def _verify_staged_archive(path: Path, digest: str, artifact_root: Path) -> None:
    """Check an existing published archive before reusing its deterministic name."""
    _require_staged_archive_within_transfer_limit(path)
    staging = artifact_root / f".verify-staged-input-{uuid4().hex}"
    staging.mkdir()
    try:
        _unpack_staged_archive(path, staging, digest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _unpack_staged_archive(archive_path: Path, destination: Path, digest: str) -> Path:
    """Materialize only a bounded regular-file archive into a private directory."""
    _require_directory(destination)
    try:
        with tarfile.open(archive_path, "r:") as archive:
            members = archive.getmembers()
            if not 1 <= len(members) <= _MAX_FILES + 1:
                raise QueueServiceError("preparation staged archive exceeds file limit")
            names: set[str] = set()
            total = 0
            for member in members:
                name = _staged_member_name(member)
                if name in names:
                    raise QueueServiceError(
                        "preparation staged archive has duplicate destination"
                    )
                names.add(name)
                if name == "manifest.json":
                    if member.size > _MAX_BYTES:
                        raise QueueServiceError(
                            "preparation input_limit_exceeded during extraction"
                        )
                else:
                    total += member.size
                    if total > _MAX_BYTES:
                        raise QueueServiceError(
                            "preparation input_limit_exceeded during extraction"
                        )
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise QueueServiceError("preparation staged archive is invalid")
                with source:
                    data = source.read(member.size + 1)
                if len(data) != member.size:
                    raise QueueServiceError("preparation staged archive is incomplete")
                _write_durable(target, data)
    except (OSError, tarfile.TarError) as exc:
        raise QueueServiceError("preparation staged archive is invalid") from exc
    return _verify_capture(destination, digest)


def _staged_member_name(member: tarfile.TarInfo) -> str:
    if not member.isreg():
        raise QueueServiceError(
            "preparation staged archive contains unsupported member"
        )
    if member.size < 0:
        raise QueueServiceError("preparation staged archive is invalid")
    if member.name == "manifest.json":
        return member.name
    if not member.name.startswith("files/"):
        raise QueueServiceError("preparation staged archive has unsafe destination")
    try:
        relative = _relative(member.name.removeprefix("files/"), "captured path")
    except QueueServiceError as exc:
        raise QueueServiceError(
            "preparation staged archive has unsafe destination"
        ) from exc
    if member.name != f"files/{relative}":
        raise QueueServiceError("preparation staged archive has unsafe destination")
    return member.name


def _require_regular_file(path: Path) -> None:
    details = path.lstat()
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise QueueServiceError("preparation staged archive must be a regular file")


def _require_staged_archive_within_transfer_limit(path: Path) -> None:
    _require_regular_file(path)
    if path.stat().st_size > _MAX_BYTES:
        raise QueueServiceError("preparation input_limit_exceeded")


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return format_digest("sha256", digest.hexdigest())


def _verify_archive_checksum(path: Path, checksum: str | None) -> None:
    if checksum is not None and _file_checksum(path) != checksum:
        raise QueueServiceError("preparation staged archive checksum is invalid")


def _discard_extraction_temporaries(workspace_root: Path, name: str) -> None:
    prefix = f".{name}.tmp-"
    for candidate in workspace_root.iterdir():
        suffix = candidate.name.removeprefix(prefix)
        if (
            candidate.name.startswith(prefix)
            and len(suffix) == 32
            and all(char in "0123456789abcdef" for char in suffix)
        ):
            details = candidate.lstat()
            if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                shutil.rmtree(candidate)


def discard_shared_input_temporaries(
    request: PrepareRunRequest, *, snapshot_root: Path, owner_id: str
) -> None:
    """Recover only this coordinator operation's interrupted private copies."""
    if not snapshot_root.exists():
        return
    _require_directory(snapshot_root)
    prefix = f".{_capture_operation_key(request.operation_id, owner_id)}.tmp-"
    for candidate in snapshot_root.iterdir():
        suffix = candidate.name.removeprefix(prefix)
        if (
            candidate.name.startswith(prefix)
            and len(suffix) == 32
            and all(char in "0123456789abcdef" for char in suffix)
        ):
            _require_directory(candidate)
            shutil.rmtree(candidate)
    _sync_directory(snapshot_root)


def _capture_operation_key(operation_id: str, owner_id: str | None) -> str:
    identity = operation_id if owner_id is None else owner_id + "\0" + operation_id
    return hashlib.sha256(identity.encode()).hexdigest()


def resolve_shared_input(
    receipt: SharedInputReceipt, *, shared_roots: Mapping[str, Path]
) -> Path:
    """Verify an input using the worker's retained private root mapping.

    The returned directory contains only the selected authored files. Different
    machines may bind the same alias to different mount prefixes. No coordinator
    path is taken from the portable receipt, and missing mappings never fall back
    to the source checkout or to a different delivery mode.
    """
    root = shared_roots.get(receipt.root)
    if root is None:
        raise QueueServiceError(
            "preparation source_unavailable: shared root is not mapped"
        )
    try:
        directory = _contained_path(root.absolute(), receipt.path)
        return _verify_capture(directory, receipt.manifest_digest)
    except OSError as exc:
        raise QueueServiceError(
            "preparation source_unavailable: shared capture cannot be read"
        ) from exc


def _require_directory(path: Path) -> None:
    details = path.lstat()
    if stat.S_ISLNK(details.st_mode):
        raise QueueServiceError("preparation source contains symbolic link")
    if not stat.S_ISDIR(details.st_mode):
        raise QueueServiceError("preparation source_unavailable: directory required")


def _contained_path(root: Path, relative: str) -> Path:
    """Build a path only through real directory components below ``root``."""
    _require_directory(root)
    current = root
    for part in PurePosixPath(relative).parts:
        if part == ".":
            continue
        current = current / part
        if current.is_symlink():
            raise QueueServiceError("preparation source contains symbolic link")
    return current


def _selected_files(
    project: Path, includes: tuple[str, ...]
) -> dict[str, os.stat_result]:
    files: dict[str, os.stat_result] = {}
    pending = [_contained_path(project, include) for include in includes]
    while pending:
        path = pending.pop()
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise QueueServiceError("preparation source contains symbolic link")
        if stat.S_ISDIR(details.st_mode):
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    else:
                        _select_file(
                            project,
                            Path(entry.path),
                            entry.stat(follow_symlinks=False),
                            files,
                        )
        else:
            _select_file(project, path, details, files)
    if sum(item.st_size for item in files.values()) > _MAX_BYTES:
        raise QueueServiceError("preparation input_limit_exceeded")
    return files


def _select_file(
    project: Path, path: Path, details: os.stat_result, files: dict[str, os.stat_result]
) -> None:
    if stat.S_ISLNK(details.st_mode):
        raise QueueServiceError("preparation source contains symbolic link")
    if not stat.S_ISREG(details.st_mode):
        raise QueueServiceError("preparation source contains unsupported file")
    relative = path.relative_to(project).as_posix()
    files[relative] = details
    if len(files) > _MAX_FILES or details.st_size > _MAX_BYTES:
        raise QueueServiceError("preparation input_limit_exceeded")


def _identity(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _file_identities(files: Mapping[str, os.stat_result]) -> dict[str, tuple[int, ...]]:
    return {name: _identity(details) for name, details in files.items()}


def _read_regular_file(
    root: Path, relative: str, limit: int, *, expected: os.stat_result | None = None
) -> bytes:
    try:
        # Open each component relative to an already-open directory. A concurrent
        # authoring edit cannot redirect a later open through a symbolic link.
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = PurePosixPath(relative).parts
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise QueueServiceError("preparation source contains unsupported file")
            if expected is not None and _identity(before) != _identity(expected):
                raise QueueServiceError("preparation source_changed")
            if before.st_size > limit:
                raise QueueServiceError("preparation input_limit_exceeded")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(data) != before.st_size or _identity(before) != _identity(after):
                raise QueueServiceError("preparation source_changed")
            return data
    except OSError as exc:
        if expected is not None and exc.errno in {
            errno.ENOENT,
            errno.ENOTDIR,
            errno.ELOOP,
        }:
            raise QueueServiceError("preparation source_changed") from exc
        raise


def _write_durable(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_capture(directory: Path, digest: str) -> Path:
    """Validate manifest and exact selected bytes at the shared storage boundary."""
    _require_directory(directory)
    try:
        actual = json.loads(_read_regular_file(directory, "manifest.json", _MAX_BYTES))
    except (OSError, ValueError) as exc:
        raise QueueServiceError("preparation capture is incomplete or invalid") from exc
    if (
        not isinstance(actual, Mapping)
        or set(actual) != {"schema_version", "files"}
        or type(actual.get("schema_version")) is not int
        or actual.get("schema_version") != 1
        or hash_mapping(actual) != digest
    ):
        raise QueueServiceError("preparation capture is invalid")
    entries = actual.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_FILES:
        raise QueueServiceError("preparation capture is invalid")
    captured = directory / "files"
    _require_directory(captured)
    expected: list[str] = []
    total = 0
    for entry in entries:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"path", "size_bytes", "sha256"}
            or not isinstance(entry.get("path"), str)
            or type(entry.get("size_bytes")) is not int
            or not isinstance(entry.get("sha256"), str)
        ):
            raise QueueServiceError("preparation capture is invalid")
        relative = _relative(entry["path"], "captured path")
        size = cast(int, entry["size_bytes"])
        if relative != entry["path"] or size < 0 or size > _MAX_BYTES - total:
            raise QueueServiceError("preparation capture is invalid")
        try:
            data = _read_regular_file(captured, relative, size)
        except (OSError, QueueServiceError) as exc:
            raise QueueServiceError("preparation capture is invalid") from exc
        total += len(data)
        if len(data) != size or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise QueueServiceError("preparation capture is invalid")
        expected.append(relative)
    if expected != sorted(set(expected)) or set(
        _selected_files(captured, (".",))
    ) != set(expected):
        raise QueueServiceError("preparation capture is invalid")
    return captured


__all__ = [
    "PrepareRunRequest",
    "PreparationSource",
    "PreparationChildInput",
    "PreparationInputReceipt",
    "SharedInputReceipt",
    "StagedInputReceipt",
    "capture_shared_input",
    "capture_staged_input",
    "discard_shared_input_temporaries",
    "discard_staged_input_temporaries",
    "input_receipt_from_dict",
    "resolve_shared_input",
    "resolve_staged_input",
]
