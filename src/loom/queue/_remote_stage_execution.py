"""Private, path-free data contracts for remote managed-stage execution.

The coordinator retains authoritative run and source-path identities. A remote
agent receives only immutable semantic data and derives every local path from
its protected root and the assigned identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from typing import cast

from loom.artifacts import ArtifactRef
from loom.io.uris import uri_to_path
from loom.pipeline.execution.models import (
    ExecutionFailure,
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    StageWorkerRequest,
    StageWorkerResult,
)
from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.status import StageStatus
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
)
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    thaw_plain_data,
)

from .errors import QueueConflictError, QueueServiceError


REMOTE_EXECUTION_SCHEMA_VERSION = 2
REMOTE_EXECUTION_CAPABILITY = "remote-stage-execution-v2"
REGULAR_FILE_RELAY_CAPABILITY = "regular-file-relay-v1"
MAX_TRANSFER_BYTES = 64 * 1024 * 1024
TRANSFER_CHUNK_BYTES = 32 * 1024


def _identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or len(value) > 160
    ):
        raise QueueServiceError(f"{field} is invalid")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@+"
    if any(char not in allowed for char in value):
        raise QueueServiceError(f"{field} is invalid")
    return value


def _digest(value: object, field: str = "digest") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise QueueServiceError(f"{field} is invalid")
    return value


def _opaque_identity(value: object, field: str) -> str:
    """Validate a semantic identity that is never interpreted as a path."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
        or value.startswith(("file:", "http:", "https:", "/", "\\"))
    ):
        raise QueueServiceError(f"{field} is invalid")
    return value


def _bounded_size(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_TRANSFER_BYTES
    ):
        raise QueueServiceError("transfer size is outside the configured bound")
    return value


@dataclass(frozen=True, slots=True)
class ResidentProfileDescriptor:
    """Safe part of one protected agent-local resident execution profile."""

    profile_id: str
    revision: str
    project_fingerprint: str
    environment_fingerprint: str
    executor_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "revision",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
        ):
            _identifier(getattr(self, name), name)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "profile_id": self.profile_id,
            "revision": self.revision,
            "project_fingerprint": self.project_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "executor_fingerprint": self.executor_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidentProfileDescriptor":
        if not isinstance(value, Mapping) or set(value) != {
            "profile_id",
            "revision",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
        }:
            raise QueueServiceError("resident profile descriptor is invalid")
        return cls(
            cast(str, value["profile_id"]),
            cast(str, value["revision"]),
            cast(str, value["project_fingerprint"]),
            cast(str, value["environment_fingerprint"]),
            cast(str, value["executor_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class GpuDeviceDescriptor:
    """Safe configured GPU identity carried across the agent protocol."""

    device_id: str
    model: str
    vram_bytes: int
    allocation_mode: str = "exclusive"
    provider: str = "exclusive"
    granularity: int = 1
    share_numerator: int = 1
    share_denominator: int = 1
    share_granularity_numerator: int = 1
    share_granularity_denominator: int = 1
    features: tuple[str, ...] = ()
    healthy: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.device_id, "device_id"),
            (self.model, "model"),
            (self.provider, "provider"),
        ):
            _identifier(value, f"GPU {name}")
        if self.allocation_mode not in {
            "exclusive",
            "vram_share",
            "provider_fraction",
        }:
            raise QueueServiceError("GPU allocation mode is unsupported")
        if self.allocation_mode == "exclusive" and self.provider != "exclusive":
            raise QueueServiceError("exclusive GPU provider must be exclusive")
        for value, name in (
            (self.vram_bytes, "vram_bytes"),
            (self.granularity, "granularity"),
            (self.share_numerator, "share_numerator"),
            (self.share_denominator, "share_denominator"),
            (self.share_granularity_numerator, "share_granularity_numerator"),
            (self.share_granularity_denominator, "share_granularity_denominator"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise QueueServiceError(f"GPU {name} must be a positive integer")
        if self.allocation_mode == "exclusive" and self.granularity != 1:
            raise QueueServiceError("exclusive GPU granularity must be one device")
        if self.allocation_mode == "vram_share" and (
            self.vram_bytes % self.granularity
        ):
            raise QueueServiceError("GPU VRAM capacity must be a granularity multiple")
        if self.allocation_mode == "provider_fraction":
            capacity = ExactQuantity(self.share_numerator, self.share_denominator)
            granularity = ExactQuantity(
                self.share_granularity_numerator,
                self.share_granularity_denominator,
            )
            if capacity.fraction % granularity.fraction:
                raise QueueServiceError(
                    "GPU share capacity must be a granularity multiple"
                )
            object.__setattr__(self, "share_numerator", capacity.numerator)
            object.__setattr__(self, "share_denominator", capacity.denominator)
            object.__setattr__(
                self, "share_granularity_numerator", granularity.numerator
            )
            object.__setattr__(
                self, "share_granularity_denominator", granularity.denominator
            )
        features = tuple(self.features)
        if any(not isinstance(value, str) or not value for value in features) or len(
            set(features)
        ) != len(features):
            raise QueueServiceError("GPU features are invalid")
        if not isinstance(self.healthy, bool):
            raise QueueServiceError("GPU health is invalid")
        object.__setattr__(self, "features", tuple(sorted(features)))

    @property
    def unit(self) -> str:
        return {
            "exclusive": "count",
            "vram_share": "B",
            "provider_fraction": "share",
        }[self.allocation_mode]

    @property
    def capacity(self) -> ExactQuantity:
        if self.allocation_mode == "exclusive":
            return ExactQuantity(1)
        if self.allocation_mode == "vram_share":
            return ExactQuantity(self.vram_bytes)
        return ExactQuantity(self.share_numerator, self.share_denominator)

    @property
    def capacity_granularity(self) -> ExactQuantity:
        if self.allocation_mode == "exclusive":
            return ExactQuantity(1)
        if self.allocation_mode == "vram_share":
            return ExactQuantity(self.granularity)
        return ExactQuantity(
            self.share_granularity_numerator,
            self.share_granularity_denominator,
        )

    def capacity_atom(self, local_capacity_key: str | None = None) -> CapacityAtom:
        return CapacityAtom(
            "gpu",
            local_capacity_key or self.device_id,
            self.capacity,
            self.unit,
            self.capacity_granularity,
        )

    def to_dict(self, *, device_id: str | None = None) -> dict[str, PlainData]:
        return {
            "id": device_id or self.device_id,
            "model": self.model,
            "vram_bytes": self.vram_bytes,
            "allocation_mode": self.allocation_mode,
            "provider": self.provider,
            "granularity": self.granularity,
            "share_numerator": self.share_numerator,
            "share_denominator": self.share_denominator,
            "share_granularity_numerator": self.share_granularity_numerator,
            "share_granularity_denominator": self.share_granularity_denominator,
            "features": list(self.features),
            "healthy": self.healthy,
        }

    @classmethod
    def from_dict(cls, value: object) -> "GpuDeviceDescriptor":
        expected = {
            "id",
            "model",
            "vram_bytes",
            "allocation_mode",
            "provider",
            "granularity",
            "share_numerator",
            "share_denominator",
            "share_granularity_numerator",
            "share_granularity_denominator",
            "features",
            "healthy",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise QueueServiceError("GPU device descriptor is invalid")
        features = value["features"]
        if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
            raise QueueServiceError("GPU device features are invalid")
        return cls(
            device_id=cast(str, value["id"]),
            model=cast(str, value["model"]),
            vram_bytes=cast(int, value["vram_bytes"]),
            allocation_mode=cast(str, value["allocation_mode"]),
            provider=cast(str, value["provider"]),
            granularity=cast(int, value["granularity"]),
            share_numerator=cast(int, value["share_numerator"]),
            share_denominator=cast(int, value["share_denominator"]),
            share_granularity_numerator=cast(int, value["share_granularity_numerator"]),
            share_granularity_denominator=cast(
                int, value["share_granularity_denominator"]
            ),
            features=tuple(cast(Sequence[str], features)),
            healthy=cast(bool, value["healthy"]),
        )


@dataclass(frozen=True, slots=True)
class ResidentGpuDevice:
    """One safe remote GPU descriptor plus its agent-private binding."""

    descriptor: GpuDeviceDescriptor
    binding_value: str

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, GpuDeviceDescriptor):
            raise QueueServiceError("resident GPU descriptor is invalid")
        if self.descriptor.allocation_mode != "exclusive":
            raise QueueServiceError(
                "resident GPU sharing requires an enforceable provider adapter"
            )
        _identifier(self.binding_value, "resident GPU binding_value")
        if "," in self.binding_value:
            raise QueueServiceError("resident GPU binding value is invalid")


@dataclass(frozen=True, slots=True)
class ResidentExecutionProfile:
    """Protected local profile; its paths never enter protocol values."""

    descriptor: ResidentProfileDescriptor
    project_root: Path
    python_executable: Path
    cpu_capacity: int = 1
    memory_capacity_bytes: int = 0
    gpu_devices: tuple[ResidentGpuDevice, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ResidentProfileDescriptor):
            raise QueueServiceError("resident execution descriptor is invalid")
        project_root = Path(self.project_root).resolve()
        # Preserve the executable entry path: virtual-environment Python
        # launchers are commonly symlinks whose spelling selects the venv.
        executable = Path(os.path.abspath(self.python_executable))
        if not project_root.is_dir():
            raise QueueServiceError("resident project root is unavailable")
        if not executable.is_file():
            raise QueueServiceError("resident Python executable is unavailable")
        for value, name, positive in (
            (self.cpu_capacity, "cpu_capacity", True),
            (self.memory_capacity_bytes, "memory_capacity_bytes", False),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (1 if positive else 0)
            ):
                raise QueueServiceError(f"resident {name} is invalid")
        gpu_devices = tuple(self.gpu_devices)
        if any(not isinstance(item, ResidentGpuDevice) for item in gpu_devices) or len(
            {item.descriptor.device_id for item in gpu_devices}
        ) != len(gpu_devices):
            raise QueueServiceError("resident GPU devices are invalid")
        object.__setattr__(self, "project_root", project_root)
        object.__setattr__(self, "python_executable", executable)
        object.__setattr__(self, "gpu_devices", gpu_devices)

    def capacity_atoms(self, agent_id: str) -> tuple[CapacityAtom, ...]:
        _identifier(agent_id, "agent_id")
        atoms = [
            CapacityAtom(
                "cpu",
                f"{agent_id}:cpu",
                ExactQuantity(self.cpu_capacity),
                "count",
                ExactQuantity(1),
            )
        ]
        if self.memory_capacity_bytes:
            atoms.append(
                CapacityAtom(
                    "memory",
                    f"{agent_id}:memory",
                    ExactQuantity(self.memory_capacity_bytes),
                    "B",
                    ExactQuantity(1),
                )
            )
        atoms.extend(
            device.descriptor.capacity_atom(f"{agent_id}:{device.descriptor.device_id}")
            for device in self.gpu_devices
        )
        return tuple(atoms)


@dataclass(frozen=True, slots=True)
class _RemoteArtifact:
    """Immutable regular-file input without its coordinator URI or path."""

    transfer_id: str
    logical_name: str
    digest: str
    size_bytes: int
    artifact_id: str
    artifact_type: str
    codec_key: str | None = None
    artifact_schema_version: int = 1
    fingerprint: str | None = None
    producer_stage: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in (
            (self.transfer_id, "transfer_id"),
            (self.logical_name, "logical_name"),
            (self.artifact_type, "artifact_type"),
        ):
            _identifier(value, name)
        _opaque_identity(self.artifact_id, "artifact_id")
        _digest(self.digest)
        _bounded_size(self.size_bytes)
        if self.codec_key is not None:
            _identifier(self.codec_key, "codec_key")
        if (
            isinstance(self.artifact_schema_version, bool)
            or not isinstance(self.artifact_schema_version, int)
            or self.artifact_schema_version < 1
        ):
            raise QueueServiceError("artifact schema version is invalid")
        if self.fingerprint is not None and not isinstance(self.fingerprint, str):
            raise QueueServiceError("artifact fingerprint is invalid")
        if self.producer_stage is not None:
            _identifier(self.producer_stage, "producer_stage")
        if self.created_at is not None and not isinstance(self.created_at, str):
            raise QueueServiceError("artifact created_at is invalid")
        metadata = freeze_plain_data(self.metadata, path="remote artifact metadata")
        if not isinstance(metadata, Mapping):
            raise QueueServiceError("remote artifact metadata is invalid")
        _reject_path_bearing_data(metadata, "artifact metadata")
        object.__setattr__(self, "metadata", metadata)

    @classmethod
    def from_local_ref(
        cls, *, transfer_id: str, logical_name: str, ref: ArtifactRef
    ) -> tuple["_RemoteArtifact", Path]:
        try:
            source = uri_to_path(ref.uri)
            if source.is_symlink():
                raise QueueConflictError("remote transfer source is a link")
            path = source.resolve(strict=True)
            data = _read_regular_file_bytes(path)
        except (OSError, QueueConflictError) as exc:
            raise QueueServiceError(
                "remote execution supports local regular-file inputs only"
            ) from exc
        digest = hashlib.sha256(data).hexdigest()
        if ref.checksum is not None and ref.checksum != f"sha256:{digest}":
            raise QueueConflictError("remote input checksum conflicts with its bytes")
        return (
            cls(
                transfer_id=transfer_id,
                logical_name=logical_name,
                digest=digest,
                size_bytes=len(data),
                artifact_id=ref.artifact_id,
                artifact_type=ref.artifact_type,
                codec_key=ref.codec_key,
                artifact_schema_version=ref.schema_version,
                fingerprint=ref.fingerprint,
                producer_stage=ref.producer_stage,
                created_at=ref.created_at,
                metadata=ref.metadata,
            ),
            path,
        )

    def local_ref(self, path: Path) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.artifact_id,
            uri=path.resolve().as_uri(),
            artifact_type=self.artifact_type,
            codec_key=self.codec_key,
            schema_version=self.artifact_schema_version,
            checksum=f"sha256:{self.digest}",
            fingerprint=self.fingerprint,
            producer_stage=self.producer_stage,
            created_at=self.created_at,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "transfer_id": self.transfer_id,
            "logical_name": self.logical_name,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "artifact_schema_version": self.artifact_schema_version,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "metadata": thaw_plain_data(self.metadata, path="remote artifact metadata"),
        }

    @classmethod
    def from_dict(cls, value: object) -> "_RemoteArtifact":
        expected = {
            "transfer_id",
            "logical_name",
            "digest",
            "size_bytes",
            "artifact_id",
            "artifact_type",
            "codec_key",
            "artifact_schema_version",
            "fingerprint",
            "producer_stage",
            "created_at",
            "metadata",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise QueueServiceError("remote artifact is invalid")
        return cls(
            transfer_id=cast(str, value["transfer_id"]),
            logical_name=cast(str, value["logical_name"]),
            digest=cast(str, value["digest"]),
            size_bytes=cast(int, value["size_bytes"]),
            artifact_id=cast(str, value["artifact_id"]),
            artifact_type=cast(str, value["artifact_type"]),
            codec_key=cast(str | None, value["codec_key"]),
            artifact_schema_version=cast(int, value["artifact_schema_version"]),
            fingerprint=cast(str | None, value["fingerprint"]),
            producer_stage=cast(str | None, value["producer_stage"]),
            created_at=cast(str | None, value["created_at"]),
            metadata=cast(Mapping[str, PlainData], value["metadata"]),
        )


def _claim_to_dict(claim: ResourceClaim) -> dict[str, PlainData]:
    return {
        "resource_kind": claim.resource_kind,
        "contract": claim.contract.to_dict(),
        "atoms": [atom.to_dict() for atom in claim.atoms],
        "provider_data_version": claim.provider_data_version,
        "provider_data": thaw_plain_data(
            claim.provider_data, path="remote claim provider data"
        ),
        "fingerprint": claim.fingerprint,
    }


def _claim_from_dict(value: object) -> ResourceClaim:
    if not isinstance(value, Mapping) or set(value) != {
        "resource_kind",
        "contract",
        "atoms",
        "provider_data_version",
        "provider_data",
        "fingerprint",
    }:
        raise QueueServiceError("remote resource claim is invalid")
    raw_atoms = value["atoms"]
    if not isinstance(raw_atoms, Sequence) or isinstance(raw_atoms, (str, bytes)):
        raise QueueServiceError("remote resource claim is invalid")
    atoms: list[CapacityAtom] = []
    for item in raw_atoms:
        if not isinstance(item, Mapping) or set(item) != {
            "owner_resource_kind",
            "local_capacity_key",
            "amount",
            "unit",
            "granularity",
        }:
            raise QueueServiceError("remote resource claim atom is invalid")
        atoms.append(
            CapacityAtom(
                cast(str, item["owner_resource_kind"]),
                cast(str, item["local_capacity_key"]),
                ExactQuantity.from_dict(item["amount"]),
                cast(str, item["unit"]),
                ExactQuantity.from_dict(item["granularity"]),
            )
        )
    claim = ResourceClaim(
        resource_kind=cast(str, value["resource_kind"]),
        contract=ResourceClaimContractDescriptor.from_dict(value["contract"]),
        atoms=tuple(atoms),
        provider_data_version=cast(int, value["provider_data_version"]),
        provider_data=cast(Mapping[str, PlainData], value["provider_data"]),
    )
    if value["fingerprint"] != claim.fingerprint:
        raise QueueConflictError("remote resource claim fingerprint conflicts")
    return claim


@dataclass(frozen=True, slots=True)
class _DeliveredExecutionRequest:
    """Hard-cutover semantic request with no run URI, host path, or URL."""

    assignment_id: str
    stage_work_id: str
    stage_name: str
    attempt: int
    attempt_id: str
    offer_id: str
    claim_id: str
    profile: ResidentProfileDescriptor
    prepared_at: str
    executor_name: str
    fingerprint: Mapping[str, PlainData]
    resolved_runtime: Mapping[str, PlainData]
    worker_metadata: Mapping[str, PlainData]
    inputs: tuple[_RemoteArtifact, ...]
    declared_outputs: tuple[str, ...]
    claims: tuple[ResourceClaim, ...]
    schema_version: int = REMOTE_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REMOTE_EXECUTION_SCHEMA_VERSION:
            raise QueueServiceError("remote execution request schema is unsupported")
        for name in (
            "assignment_id",
            "stage_work_id",
            "stage_name",
            "attempt_id",
            "offer_id",
            "claim_id",
            "prepared_at",
            "executor_name",
        ):
            _identifier(getattr(self, name), name)
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise QueueServiceError("attempt is invalid")
        if not isinstance(self.profile, ResidentProfileDescriptor):
            raise QueueServiceError("remote resident profile is invalid")
        fingerprint = freeze_plain_data(self.fingerprint, path="remote fingerprint")
        runtime = freeze_plain_data(self.resolved_runtime, path="remote runtime")
        metadata = freeze_plain_data(
            self.worker_metadata, path="remote worker metadata"
        )
        if (
            not isinstance(fingerprint, Mapping)
            or not isinstance(runtime, Mapping)
            or not isinstance(metadata, Mapping)
            or runtime.get("stage_id") != self.stage_name
        ):
            raise QueueServiceError("remote semantic request is invalid")
        _validate_remote_semantic_data(
            fingerprint=fingerprint,
            resolved_runtime=runtime,
            worker_metadata=metadata,
        )
        try:
            fingerprint_record = StageFingerprintRecord.from_dict(fingerprint)
        except Exception as exc:
            raise QueueServiceError("remote stage fingerprint is invalid") from exc
        if fingerprint_record.payload.stage_name != self.stage_name:
            raise QueueConflictError(
                "remote stage fingerprint identity conflicts with its request"
            )
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "resolved_runtime", runtime)
        object.__setattr__(self, "worker_metadata", metadata)
        inputs = tuple(self.inputs)
        outputs = tuple(
            _identifier(name, "declared output") for name in self.declared_outputs
        )
        claims = tuple(self.claims)
        if (
            any(not isinstance(item, _RemoteArtifact) for item in inputs)
            or len(inputs) > 32
            or len({item.logical_name for item in inputs}) != len(inputs)
        ):
            raise QueueServiceError("remote input logical names must be unique")
        if sum(item.size_bytes for item in inputs) > MAX_TRANSFER_BYTES:
            raise QueueServiceError("remote request inputs exceed the configured bound")
        if len(outputs) > 32 or len(set(outputs)) != len(outputs):
            raise QueueServiceError("remote output names must be unique")
        if set(item.logical_name for item in inputs) != set(
            fingerprint_record.payload.declared_inputs
        ) or set(outputs) != set(fingerprint_record.payload.declared_outputs):
            raise QueueConflictError(
                "remote stage interface conflicts with its fingerprint"
            )
        if (
            any(not isinstance(item, ResourceClaim) for item in claims)
            or not claims
            or len(claims) > 8
            or len({item.resource_kind for item in claims}) != len(claims)
        ):
            raise QueueServiceError("remote request requires exact resource claims")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "declared_outputs", outputs)
        object.__setattr__(self, "claims", claims)

    @classmethod
    def from_worker_request(
        cls,
        *,
        assignment_id: str,
        stage_work_id: str,
        attempt_id: str,
        offer_id: str,
        claim_id: str,
        worker_request: StageWorkerRequest,
        profile: ResidentProfileDescriptor,
        inputs: tuple[_RemoteArtifact, ...],
        declared_outputs: tuple[str, ...],
        claims: tuple[ResourceClaim, ...],
    ) -> "_DeliveredExecutionRequest":
        if not isinstance(worker_request, StageWorkerRequest):
            raise QueueServiceError(
                "delivered work must start from a prepared worker request"
            )
        safe_metadata: dict[str, PlainData] = {}
        if "stage_resources" in worker_request.metadata:
            safe_metadata["stage_resources"] = worker_request.metadata[
                "stage_resources"
            ]
        return cls(
            assignment_id=assignment_id,
            stage_work_id=stage_work_id,
            stage_name=worker_request.stage_name,
            attempt=worker_request.attempt,
            attempt_id=attempt_id,
            offer_id=offer_id,
            claim_id=claim_id,
            profile=profile,
            prepared_at=worker_request.prepared_at,
            executor_name=worker_request.executor_name,
            fingerprint=cast(
                StageFingerprintRecord, worker_request.fingerprint
            ).to_dict(),
            resolved_runtime=worker_request.resolved_runtime,
            worker_metadata=safe_metadata,
            inputs=inputs,
            declared_outputs=declared_outputs,
            claims=claims,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "assignment_id": self.assignment_id,
            "stage_work_id": self.stage_work_id,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "offer_id": self.offer_id,
            "claim_id": self.claim_id,
            "profile": self.profile.to_dict(),
            "prepared_at": self.prepared_at,
            "executor_name": self.executor_name,
            "fingerprint": thaw_plain_data(self.fingerprint, path="remote fingerprint"),
            "resolved_runtime": thaw_plain_data(
                self.resolved_runtime, path="remote runtime"
            ),
            "worker_metadata": thaw_plain_data(
                self.worker_metadata, path="remote worker metadata"
            ),
            "inputs": [item.to_dict() for item in self.inputs],
            "declared_outputs": list(self.declared_outputs),
            "claims": [_claim_to_dict(item) for item in self.claims],
        }

    @classmethod
    def from_dict(cls, value: object) -> "_DeliveredExecutionRequest":
        expected = {
            "schema_version",
            "assignment_id",
            "stage_work_id",
            "stage_name",
            "attempt",
            "attempt_id",
            "offer_id",
            "claim_id",
            "profile",
            "prepared_at",
            "executor_name",
            "fingerprint",
            "resolved_runtime",
            "worker_metadata",
            "inputs",
            "declared_outputs",
            "claims",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise QueueServiceError("remote execution request is invalid")
        for field_name in ("inputs", "declared_outputs", "claims"):
            field_value = value[field_name]
            if not isinstance(field_value, Sequence) or isinstance(
                field_value, (str, bytes)
            ):
                raise QueueServiceError("remote execution request is invalid")
        return cls(
            assignment_id=cast(str, value["assignment_id"]),
            stage_work_id=cast(str, value["stage_work_id"]),
            stage_name=cast(str, value["stage_name"]),
            attempt=cast(int, value["attempt"]),
            attempt_id=cast(str, value["attempt_id"]),
            offer_id=cast(str, value["offer_id"]),
            claim_id=cast(str, value["claim_id"]),
            profile=ResidentProfileDescriptor.from_dict(value["profile"]),
            prepared_at=cast(str, value["prepared_at"]),
            executor_name=cast(str, value["executor_name"]),
            fingerprint=cast(Mapping[str, PlainData], value["fingerprint"]),
            resolved_runtime=cast(Mapping[str, PlainData], value["resolved_runtime"]),
            worker_metadata=cast(Mapping[str, PlainData], value["worker_metadata"]),
            inputs=tuple(_RemoteArtifact.from_dict(item) for item in value["inputs"]),
            declared_outputs=tuple(cast(Sequence[str], value["declared_outputs"])),
            claims=tuple(_claim_from_dict(item) for item in value["claims"]),
            schema_version=cast(int, value["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class _RemoteOutputArtifact:
    transfer_id: str
    logical_name: str
    digest: str
    size_bytes: int
    artifact_id: str
    artifact_type: str
    codec_key: str | None
    artifact_schema_version: int
    fingerprint: str | None
    producer_stage: str | None
    created_at: str | None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in (
            (self.transfer_id, "transfer_id"),
            (self.logical_name, "logical_name"),
            (self.artifact_type, "artifact_type"),
        ):
            _identifier(value, name)
        _opaque_identity(self.artifact_id, "artifact_id")
        _digest(self.digest)
        _bounded_size(self.size_bytes)
        if self.codec_key is not None:
            _identifier(self.codec_key, "codec_key")
        if (
            isinstance(self.artifact_schema_version, bool)
            or not isinstance(self.artifact_schema_version, int)
            or self.artifact_schema_version < 1
        ):
            raise QueueServiceError("artifact schema version is invalid")
        if self.fingerprint is not None and not isinstance(self.fingerprint, str):
            raise QueueServiceError("artifact fingerprint is invalid")
        if self.producer_stage is not None:
            _identifier(self.producer_stage, "producer_stage")
        if self.created_at is not None and not isinstance(self.created_at, str):
            raise QueueServiceError("artifact created_at is invalid")
        metadata = freeze_plain_data(
            self.metadata, path="remote output artifact metadata"
        )
        if not isinstance(metadata, Mapping):
            raise QueueServiceError("remote output artifact metadata is invalid")
        _reject_path_bearing_data(metadata, "output artifact metadata")
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "transfer_id": self.transfer_id,
            "logical_name": self.logical_name,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "artifact_schema_version": self.artifact_schema_version,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "metadata": thaw_plain_data(
                self.metadata, path="remote output artifact metadata"
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> "_RemoteOutputArtifact":
        if not isinstance(value, Mapping) or set(value) != {
            "transfer_id",
            "logical_name",
            "digest",
            "size_bytes",
            "artifact_id",
            "artifact_type",
            "codec_key",
            "artifact_schema_version",
            "fingerprint",
            "producer_stage",
            "created_at",
            "metadata",
        }:
            raise QueueServiceError("remote output artifact is invalid")
        return cls(
            transfer_id=cast(str, value["transfer_id"]),
            logical_name=cast(str, value["logical_name"]),
            digest=cast(str, value["digest"]),
            size_bytes=cast(int, value["size_bytes"]),
            artifact_id=cast(str, value["artifact_id"]),
            artifact_type=cast(str, value["artifact_type"]),
            codec_key=cast(str | None, value["codec_key"]),
            artifact_schema_version=cast(int, value["artifact_schema_version"]),
            fingerprint=cast(str | None, value["fingerprint"]),
            producer_stage=cast(str | None, value["producer_stage"]),
            created_at=cast(str | None, value["created_at"]),
            metadata=cast(Mapping[str, PlainData], value["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class _RemoteExecutionReport:
    """Path-free terminal worker facts; the coordinator restores its run URI."""

    assignment_id: str
    stage_name: str
    attempt: int
    status: StageStatus
    started_at: str
    finished_at: str
    executor_name: str
    outputs: tuple[_RemoteOutputArtifact, ...] = ()
    failure_type: str | None = None
    message: str | None = None
    exception_type: str | None = None
    exit_code: int | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise QueueServiceError("remote result schema is unsupported")
        for value, name in (
            (self.assignment_id, "assignment_id"),
            (self.stage_name, "stage_name"),
            (self.started_at, "started_at"),
            (self.finished_at, "finished_at"),
            (self.executor_name, "executor_name"),
        ):
            _identifier(value, name)
        object.__setattr__(self, "status", StageStatus(self.status))
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise QueueServiceError("remote result attempt is invalid")
        if self.status not in {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }:
            raise QueueServiceError("remote result status is invalid")
        outputs = tuple(self.outputs)
        if any(not isinstance(item, _RemoteOutputArtifact) for item in outputs):
            raise QueueServiceError("remote result outputs are invalid")
        if (
            len({item.logical_name for item in outputs}) != len(outputs)
            or len({item.transfer_id for item in outputs}) != len(outputs)
            or sum(item.size_bytes for item in outputs) > MAX_TRANSFER_BYTES
        ):
            raise QueueServiceError("remote result output manifest is invalid")
        if self.status is not StageStatus.SUCCEEDED and outputs:
            raise QueueServiceError("failed remote result must not expose outputs")
        object.__setattr__(self, "outputs", outputs)
        for value, name in (
            (self.failure_type, "failure_type"),
            (self.exception_type, "exception_type"),
        ):
            if value is not None:
                _identifier(value, name)
        if self.message is not None and (
            not isinstance(self.message, str) or len(self.message) > 1024
        ):
            raise QueueServiceError("remote failure message is invalid")
        if self.status is StageStatus.SUCCEEDED and any(
            value is not None
            for value in (
                self.failure_type,
                self.message,
                self.exception_type,
            )
        ):
            raise QueueServiceError(
                "successful remote result must not carry failure data"
            )
        if self.status is StageStatus.FAILED and (
            self.failure_type is None or self.message is None
        ):
            raise QueueServiceError("failed remote result lacks failure data")
        if self.status is StageStatus.CANCELLED and any(
            value is not None
            for value in (
                self.failure_type,
                self.message,
                self.exception_type,
            )
        ):
            raise QueueServiceError(
                "cancelled remote result must not carry failure data"
            )
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise QueueServiceError("remote result exit code is invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "assignment_id": self.assignment_id,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "executor_name": self.executor_name,
            "outputs": [item.to_dict() for item in self.outputs],
            "failure_type": self.failure_type,
            "message": self.message,
            "exception_type": self.exception_type,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, value: object) -> "_RemoteExecutionReport":
        expected = {
            "schema_version",
            "assignment_id",
            "stage_name",
            "attempt",
            "status",
            "started_at",
            "finished_at",
            "executor_name",
            "outputs",
            "failure_type",
            "message",
            "exception_type",
            "exit_code",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise QueueServiceError("remote execution report is invalid")
        outputs = value["outputs"]
        if not isinstance(outputs, Sequence) or isinstance(outputs, (str, bytes)):
            raise QueueServiceError("remote execution report is invalid")
        return cls(
            assignment_id=cast(str, value["assignment_id"]),
            stage_name=cast(str, value["stage_name"]),
            attempt=cast(int, value["attempt"]),
            status=StageStatus(cast(str, value["status"])),
            started_at=cast(str, value["started_at"]),
            finished_at=cast(str, value["finished_at"]),
            executor_name=cast(str, value["executor_name"]),
            outputs=tuple(_RemoteOutputArtifact.from_dict(item) for item in outputs),
            failure_type=cast(str | None, value["failure_type"]),
            message=cast(str | None, value["message"]),
            exception_type=cast(str | None, value["exception_type"]),
            exit_code=cast(int | None, value["exit_code"]),
            schema_version=cast(int, value["schema_version"]),
        )


class _RemoteAssignmentWorkspace:
    """Agent-owned durable request, byte, start, result, and outbox gate."""

    def __init__(self, agent_root: Path, assignment_id: str) -> None:
        _identifier(assignment_id, "assignment_id")
        root = Path(agent_root).resolve()
        self.root = root / "assignments" / assignment_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self._db = self.root / "remote.sqlite"
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS request (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    value_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    fence TEXT,
                    process_execution_id TEXT,
                    process_id INTEGER,
                    result_json TEXT
                );
                CREATE TABLE IF NOT EXISTS transfers (
                    transfer_id TEXT PRIMARY KEY,
                    logical_name TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    received_bytes INTEGER NOT NULL DEFAULT 0,
                    finalized INTEGER NOT NULL DEFAULT 0,
                    descriptor_json TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0
                );
                """
            )
        self._db.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def assignment_id(self) -> str:
        return self.root.name

    def persist_request(
        self,
        request: _DeliveredExecutionRequest,
        profile: ResidentExecutionProfile,
    ) -> None:
        if request.assignment_id != self.assignment_id:
            raise QueueConflictError("delivered request targets another workspace")
        if request.profile != profile.descriptor:
            raise QueueConflictError(
                "delivered request does not match the resident profile"
            )
        encoded = _canonical_json(request.to_dict())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM request WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                if str(row[0]) != encoded:
                    raise QueueConflictError(
                        "delivered request conflicts with durable request"
                    )
                return
            conn.execute(
                "INSERT INTO request(singleton, value_json, state) "
                "VALUES (1, ?, 'DELIVERED')",
                (encoded,),
            )
            for item in request.inputs:
                conn.execute(
                    "INSERT INTO transfers(transfer_id, logical_name, digest, "
                    "size_bytes, direction) VALUES (?, ?, ?, ?, 'input')",
                    (
                        item.transfer_id,
                        item.logical_name,
                        item.digest,
                        item.size_bytes,
                    ),
                )

    def stage_input_chunk(
        self, transfer_id: str, offset: int, data: bytes, *, final: bool
    ) -> int:
        _identifier(transfer_id, "transfer_id")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or not isinstance(data, bytes)
            or len(data) > TRANSFER_CHUNK_BYTES
        ):
            raise QueueServiceError("remote input chunk is invalid")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT logical_name, digest, size_bytes, received_bytes, finalized "
                "FROM transfers WHERE transfer_id = ? AND direction = 'input'",
                (transfer_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError(
                    "input transfer is not authorized for this assignment"
                )
            target = self.root / "inputs" / str(row["logical_name"])
            part = self.root / "input-staging" / f"{transfer_id}.part"
            received = int(row["received_bytes"])
            if bool(row["finalized"]):
                if offset + len(data) > int(row["size_bytes"]):
                    raise QueueConflictError("input replay exceeds durable content")
                existing = _read_regular_file_bytes(target)[offset : offset + len(data)]
                if existing != data:
                    raise QueueConflictError("input replay conflicts with durable bytes")
                return int(row["size_bytes"])
            if _published_file_matches(
                target,
                size_bytes=int(row["size_bytes"]),
                digest=str(row["digest"]),
            ):
                received = int(row["size_bytes"])
                conn.execute(
                    "UPDATE transfers SET received_bytes = ?, finalized = 1 "
                    "WHERE transfer_id = ?",
                    (received, transfer_id),
                )
                if offset + len(data) > received:
                    raise QueueConflictError("input replay exceeds durable content")
                existing = _read_regular_file_range(target, offset, len(data))
                if existing != data:
                    raise QueueConflictError(
                        "input replay conflicts with durable bytes"
                    )
                conn.commit()
                return received
            received = _append_exact_chunk(part, offset, received, data)
            if received > int(row["size_bytes"]):
                raise QueueConflictError("input transfer exceeds its durable size")
            should_finalize = final or received == int(row["size_bytes"])
            if should_finalize:
                if received != int(row["size_bytes"]):
                    raise QueueConflictError("input transfer finalized at wrong size")
                if _file_digest(part) != str(row["digest"]):
                    raise QueueConflictError(
                        "input transfer bytes do not match durable identity"
                    )
                _publish_staged_file(part, target)
                conn.execute(
                    "UPDATE transfers SET received_bytes = ?, finalized = 1 "
                    "WHERE transfer_id = ?",
                    (received, transfer_id),
                )
            else:
                conn.execute(
                    "UPDATE transfers SET received_bytes = ? WHERE transfer_id = ?",
                    (received, transfer_id),
                )
            conn.commit()
        return received

    def stage_input(self, transfer_id: str, data: bytes) -> None:
        """Small-test convenience; production uses bounded chunks."""
        if len(data) > MAX_TRANSFER_BYTES:
            raise QueueServiceError("remote input bytes exceed the configured bound")
        offset = 0
        if not data:
            self.stage_input_chunk(transfer_id, 0, b"", final=True)
            return
        while offset < len(data):
            chunk = data[offset : offset + TRANSFER_CHUNK_BYTES]
            next_offset = offset + len(chunk)
            offset = self.stage_input_chunk(
                transfer_id, offset, chunk, final=next_offset == len(data)
            )

    def accept(self) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM request WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise QueueConflictError("remote request is not durable")
            missing = conn.execute(
                "SELECT COUNT(*) FROM transfers "
                "WHERE direction = 'input' AND finalized = 0"
            ).fetchone()
            if int(missing[0]):
                raise QueueConflictError("remote inputs are not durable")
            if str(row[0]) not in {"DELIVERED", "ACCEPTED"}:
                raise QueueConflictError("remote request cannot be accepted")
            conn.execute("UPDATE request SET state = 'ACCEPTED' WHERE singleton = 1")

    def grant(self, fence: str) -> None:
        _identifier(fence, "fence")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, fence FROM request WHERE singleton = 1"
            ).fetchone()
            if row is None or str(row["state"]) not in {"ACCEPTED", "GRANTED"}:
                raise QueueConflictError("remote request is not accepted")
            if row["fence"] is not None and str(row["fence"]) != fence:
                raise QueueConflictError("remote grant fence conflicts")
            conn.execute(
                "UPDATE request SET state = 'GRANTED', fence = ? WHERE singleton = 1",
                (fence,),
            )

    def mark_process_started(self, execution_id: str, process_id: int) -> None:
        _identifier(execution_id, "process_execution_id")
        if (
            isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id < 1
        ):
            raise QueueServiceError("remote process ID is invalid")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, process_execution_id, process_id FROM request "
                "WHERE singleton = 1"
            ).fetchone()
            if row is None or str(row["state"]) not in {"GRANTED", "STARTED"}:
                raise QueueConflictError("remote launch requires a durable grant")
            if row["process_execution_id"] is not None and (
                str(row["process_execution_id"]) != execution_id
                or int(row["process_id"]) != process_id
            ):
                raise QueueConflictError("remote process identity conflicts")
            conn.execute(
                "UPDATE request SET state = 'STARTED', process_execution_id = ?, "
                "process_id = ? WHERE singleton = 1",
                (execution_id, process_id),
            )

    def worker_request(self) -> StageWorkerRequest:
        request = self.request()
        fingerprint = StageFingerprintRecord.from_dict(
            thaw_plain_data(request.fingerprint, path="remote fingerprint")
        )
        inputs = {
            item.logical_name: item.local_ref(self.root / "inputs" / item.logical_name)
            for item in request.inputs
        }
        logs = self.root / "logs"
        local_run_uri = f"loom-agent:{request.assignment_id}"
        return StageWorkerRequest(
            schema_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
            run_uri=local_run_uri,
            stage_name=request.stage_name,
            attempt=request.attempt,
            prepared_at=request.prepared_at,
            executor_name=request.executor_name,
            inputs=inputs,
            fingerprint=fingerprint,
            stdout_path=str(logs / "stdout.log"),
            stderr_path=str(logs / "stderr.log"),
            traceback_path=str(logs / "traceback.log"),
            result_path=str(self.root / "worker-result.json"),
            resolved_runtime=request.resolved_runtime,
            metadata=request.worker_metadata,
        )

    def persist_worker_result(self, result: StageWorkerResult) -> None:
        request = self.request()
        if (
            result.run_uri != f"loom-agent:{request.assignment_id}"
            or result.stage_name != request.stage_name
            or result.attempt != request.attempt
        ):
            raise QueueConflictError("resident worker result identity conflicts")
        encoded = _canonical_json(result.to_dict())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, result_json FROM request WHERE singleton = 1"
            ).fetchone()
            if row is None or str(row["state"]) not in {"STARTED", "RESULT"}:
                raise QueueConflictError(
                    "resident worker result requires a confirmed process start"
                )
            if row["result_json"] is not None and str(row["result_json"]) != encoded:
                raise QueueConflictError("resident worker result replay conflicts")
            conn.execute(
                "UPDATE request SET state = 'RESULT', result_json = ? "
                "WHERE singleton = 1",
                (encoded,),
            )

    def worker_result(self) -> StageWorkerResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM request WHERE singleton = 1"
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return StageWorkerResult.from_dict(json.loads(str(row[0])))

    def retain_outputs(self) -> _RemoteExecutionReport:
        request = self.request()
        result = self.worker_result()
        if result is None:
            raise QueueConflictError("remote result is not durable")
        outputs: list[_RemoteOutputArtifact] = []
        if result.status is StageStatus.SUCCEEDED:
            if set(result.outputs) != set(request.declared_outputs):
                raise QueueConflictError(
                    "remote result does not match declared outputs"
                )
            for logical_name in sorted(result.outputs):
                ref = result.outputs[logical_name]
                try:
                    unresolved_source = uri_to_path(ref.uri)
                    if unresolved_source.is_symlink():
                        raise QueueConflictError("remote output is a link")
                    source = unresolved_source.resolve(strict=True)
                    source.relative_to(self.root)
                    data = _read_regular_file_bytes(source)
                except (OSError, ValueError, QueueConflictError) as exc:
                    raise QueueConflictError(
                        "remote output is not a regular file in its assignment workspace"
                    ) from exc
                digest = hashlib.sha256(data).hexdigest()
                if ref.checksum is not None and ref.checksum != f"sha256:{digest}":
                    raise QueueConflictError(
                        "remote output checksum conflicts with its bytes"
                    )
                transfer_id = (
                    "output-"
                    + hashlib.sha256(
                        (
                            request.assignment_id + "\0" + logical_name + "\0" + digest
                        ).encode("utf-8")
                    ).hexdigest()
                )
                target = self.root / "retained-outputs" / logical_name
                _atomic_regular_file(target, data)
                descriptor = _RemoteOutputArtifact(
                    transfer_id=transfer_id,
                    logical_name=logical_name,
                    digest=digest,
                    size_bytes=len(data),
                    artifact_id=ref.artifact_id,
                    artifact_type=ref.artifact_type,
                    codec_key=ref.codec_key,
                    artifact_schema_version=ref.schema_version,
                    fingerprint=ref.fingerprint,
                    producer_stage=ref.producer_stage,
                    created_at=ref.created_at,
                    metadata=ref.metadata,
                )
                outputs.append(descriptor)
                with self._connect() as conn:
                    prior = conn.execute(
                        "SELECT descriptor_json FROM transfers WHERE transfer_id = ?",
                        (transfer_id,),
                    ).fetchone()
                    encoded = _canonical_json(descriptor.to_dict())
                    if prior is not None and str(prior[0]) != encoded:
                        raise QueueConflictError(
                            "remote output manifest replay conflicts"
                        )
                    conn.execute(
                        "INSERT OR IGNORE INTO transfers(transfer_id, logical_name, "
                        "digest, size_bytes, direction, received_bytes, finalized, "
                        "descriptor_json) VALUES (?, ?, ?, ?, 'output', ?, 1, ?)",
                        (
                            transfer_id,
                            logical_name,
                            digest,
                            len(data),
                            len(data),
                            encoded,
                        ),
                    )
        failure = cast(ExecutionFailure | None, result.failure)
        return _RemoteExecutionReport(
            assignment_id=request.assignment_id,
            stage_name=request.stage_name,
            attempt=request.attempt,
            status=result.status,
            started_at=result.started_at,
            finished_at=result.finished_at,
            executor_name=result.executor_name,
            outputs=tuple(outputs),
            failure_type=None if failure is None else failure.failure_type,
            message=(None if failure is None else "resident stage execution failed"),
            exception_type=None if failure is None else failure.exception_type,
            exit_code=result.exit_code,
        )

    def output_chunk(self, transfer_id: str, offset: int) -> tuple[bytes, bool]:
        _identifier(transfer_id, "transfer_id")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise QueueServiceError("remote output chunk offset is invalid")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT logical_name, size_bytes FROM transfers "
                "WHERE transfer_id = ? AND direction = 'output' AND finalized = 1",
                (transfer_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("remote output transfer is not durable")
        size = int(row["size_bytes"])
        if offset > size:
            raise QueueConflictError("remote output chunk offset exceeds its size")
        path = self.root / "retained-outputs" / str(row["logical_name"])
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(TRANSFER_CHUNK_BYTES)
        return data, offset + len(data) == size

    def record_event(
        self, sequence: int, event_id: str, payload: Mapping[str, PlainData]
    ) -> None:
        _identifier(event_id, "event_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise QueueServiceError("remote event sequence is invalid")
        encoded = _canonical_json(
            cast(
                Mapping[str, PlainData],
                ensure_plain_data(payload, path="remote event"),
            )
        )
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT event_id, payload_json FROM events WHERE sequence = ?",
                (sequence,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != event_id or str(existing[1]) != encoded:
                    raise QueueConflictError("remote event replay conflicts")
                return
            next_sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events"
                ).fetchone()[0]
            )
            if sequence != next_sequence:
                raise QueueConflictError("remote event sequence has a gap")
            conn.execute(
                "INSERT INTO events(sequence, event_id, payload_json) VALUES (?, ?, ?)",
                (sequence, event_id, encoded),
            )

    def append_event(
        self, event_id: str, payload: Mapping[str, PlainData]
    ) -> tuple[int, Mapping[str, PlainData]]:
        _identifier(event_id, "event_id")
        encoded = _canonical_json(payload)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT sequence, payload_json FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != encoded:
                    raise QueueConflictError("remote event replay conflicts")
                return int(existing["sequence"]), freeze_plain_data(
                    json.loads(encoded), path="remote event"
                )
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events"
                ).fetchone()[0]
            )
        self.record_event(sequence, event_id, payload)
        return sequence, freeze_plain_data(json.loads(encoded), path="remote event")

    def acknowledge_event(self, sequence: int) -> None:
        with self._connect() as conn:
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE sequence <= ?", (sequence,)
                ).fetchone()[0]
            )
            if count != sequence:
                raise QueueConflictError("cannot acknowledge a remote event gap")
            conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE sequence <= ?",
                (sequence,),
            )

    def pending_events(self) -> tuple[tuple[int, str, Mapping[str, PlainData]], ...]:
        with self._connect() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT sequence, event_id, payload_json FROM events "
                    "WHERE acknowledged = 0 ORDER BY sequence"
                )
            )
        return tuple(
            (
                int(row["sequence"]),
                str(row["event_id"]),
                freeze_plain_data(
                    json.loads(str(row["payload_json"])), path="remote event"
                ),
            )
            for row in rows
        )

    def request(self) -> _DeliveredExecutionRequest:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM request WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise QueueConflictError("remote request is not durable")
        return _DeliveredExecutionRequest.from_dict(json.loads(str(row[0])))

    def state(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM request WHERE singleton = 1"
            ).fetchone()
        return "EMPTY" if row is None else str(row[0])


def _reject_path_bearing_data(value: object, field: str) -> None:
    forbidden_keys = ("path", "root", "uri", "url", "directory", "cwd")
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in forbidden_keys):
                raise QueueServiceError(
                    f"remote {field} must not contain path-bearing fields"
                )
            _reject_path_bearing_data(item, field)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_path_bearing_data(item, field)
    elif isinstance(value, str) and (
        value.startswith(("file:", "http:", "https:", "/")) or "\\" in value
    ):
        raise QueueServiceError(f"remote {field} must not contain paths or URLs")


def _validate_remote_semantic_data(
    *,
    fingerprint: Mapping[str, PlainData],
    resolved_runtime: Mapping[str, PlainData],
    worker_metadata: Mapping[str, PlainData],
) -> None:
    """Reject coordinator-local locations from the semantic wire request."""
    _reject_path_bearing_data(fingerprint, "fingerprint")
    _reject_path_bearing_data(resolved_runtime, "resolved_runtime")
    _reject_path_bearing_data(worker_metadata, "worker_metadata")


def _canonical_json(value: Mapping[str, PlainData]) -> str:
    return json.dumps(
        thaw_plain_data(value, path="remote durable value"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _append_exact_chunk(path: Path, offset: int, received: int, data: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        details = path.lstat()
    except FileNotFoundError:
        actual_size = 0
    else:
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise QueueConflictError("remote transfer staging target is unsafe")
        actual_size = details.st_size
    if actual_size < received:
        raise QueueConflictError("remote transfer staging bytes are incomplete")
    if actual_size > received:
        if offset != received or actual_size != received + len(data):
            raise QueueConflictError("remote transfer staging bytes conflict")
        if _read_regular_file_range(path, offset, len(data)) != data:
            raise QueueConflictError("remote transfer staging replay conflicts")
        return actual_size
    if offset < received:
        existing = _read_regular_file_range(path, offset, len(data))
        if existing != data:
            raise QueueConflictError("remote transfer replay conflicts")
        return received
    if offset != received:
        raise QueueConflictError("remote transfer chunk has a gap")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise QueueConflictError("remote transfer staging target is unsafe")
        with os.fdopen(descriptor, "ab", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    return received + len(data)


def _read_regular_file_range(path: Path, offset: int, size: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QueueConflictError(
            "remote transfer source is not a regular file"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise QueueConflictError("remote transfer source is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            stream.seek(offset)
            return stream.read(size)
    finally:
        os.close(descriptor)


def _read_regular_file_bytes(
    path: Path, *, max_bytes: int = MAX_TRANSFER_BYTES
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QueueConflictError(
            "remote transfer source is not a regular file"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise QueueConflictError("remote transfer source is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(max_bytes + 1)
    finally:
        os.close(descriptor)
    if len(data) > max_bytes:
        raise QueueConflictError("remote transfer source exceeds its byte bound")
    return data


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QueueConflictError(
            "remote transfer source is not a regular file"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise QueueConflictError("remote transfer source is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    finally:
        os.close(descriptor)
    return hasher.hexdigest()


def _published_file_matches(path: Path, *, size_bytes: int, digest: str) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise QueueConflictError("remote transfer target is not a regular file")
    if details.st_size != size_bytes or _file_digest(path) != digest:
        raise QueueConflictError("remote transfer target conflicts with durable identity")
    return True


def _publish_staged_file(staging: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise QueueConflictError("remote transfer target is not a regular file")
    os.replace(staging, target)
    _fsync_directory(target.parent)


def _atomic_regular_file(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise QueueConflictError("remote transfer target is not a regular file")
    descriptor, temporary = tempfile.mkstemp(prefix=".transfer-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _encode_chunk(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode_chunk(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > TRANSFER_CHUNK_BYTES * 2:
        raise QueueServiceError("remote transfer chunk encoding is invalid")
    try:
        data = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise QueueServiceError("remote transfer chunk encoding is invalid") from exc
    if len(data) > TRANSFER_CHUNK_BYTES:
        raise QueueServiceError("remote transfer chunk exceeds its bound")
    return data


__all__ = [
    "MAX_TRANSFER_BYTES",
    "REGULAR_FILE_RELAY_CAPABILITY",
    "REMOTE_EXECUTION_CAPABILITY",
    "REMOTE_EXECUTION_SCHEMA_VERSION",
    "GpuDeviceDescriptor",
    "ResidentExecutionProfile",
    "ResidentGpuDevice",
    "ResidentProfileDescriptor",
]
