"""Generic GPU request and CUDA visibility projection helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import re

from loom.pipeline.executors.apptainer.commands import (
    ApptainerExecOptions,
    ApptainerOptionError,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.serialization import PlainData


CUDA_VISIBLE_DEVICES = "CUDA_VISIBLE_DEVICES"
_CUDA_DEVICE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


@dataclass(frozen=True, slots=True)
class GpuVisibilityEvidence:
    """Requested GPU count and opaque allocation-visible device tokens."""

    requested_gpu_count: int
    cuda_visible_devices: tuple[str, ...]

    def to_dict(self) -> dict[str, PlainData]:
        """Return invocation evidence; callers must not persist raw tokens."""

        return {
            "requested_gpu_count": self.requested_gpu_count,
            "cuda_visible_devices": list(self.cuda_visible_devices),
        }


def requested_gpu_count(
    resources: ResourceRequest | Mapping[str, ResourceEntry] | None,
) -> int:
    """Return an attribute-free exclusive GPU count, or zero when absent."""

    if resources is None:
        return 0
    entries = resources.entries if isinstance(resources, ResourceRequest) else resources
    entry = entries.get("gpu")
    if entry is None:
        return 0
    if not isinstance(entry, ResourceEntry):
        raise ApptainerOptionError("gpu resource entry must be ResourceEntry")
    if entry.unit not in {None, "count"}:
        raise ApptainerOptionError("gpu resource unit must be omitted or 'count'")
    if entry.attributes:
        raise ApptainerOptionError("gpu resource attributes are unsupported")
    amount = entry.amount
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ApptainerOptionError("gpu resource amount must be a non-negative integer")
    return amount


def project_apptainer_gpu_options(
    options: ApptainerExecOptions,
    resources: ResourceRequest | Mapping[str, ResourceEntry] | None,
) -> ApptainerExecOptions:
    """Add NVIDIA passthrough for a bare requested GPU without changing options."""

    if not isinstance(options, ApptainerExecOptions):
        raise ApptainerOptionError("options must be ApptainerExecOptions")
    requires_gpu = requested_gpu_count(resources) > 0
    if requires_gpu and options.rocm:
        raise ApptainerOptionError(
            "generic GPU resources cannot select NVIDIA passthrough while rocm is enabled"
        )
    return replace(options, nv=options.nv or requires_gpu)


def validate_cuda_visibility(
    requested_count: int,
    environment: Mapping[str, str],
) -> GpuVisibilityEvidence:
    """Validate opaque CUDA visibility at a host or allocation boundary."""

    if isinstance(requested_count, bool) or not isinstance(requested_count, int):
        raise ApptainerOptionError("requested GPU count must be an integer")
    if requested_count < 0:
        raise ApptainerOptionError("requested GPU count must be non-negative")
    if not isinstance(environment, Mapping):
        raise ApptainerOptionError("environment must be a mapping")
    if requested_count == 0:
        return GpuVisibilityEvidence(0, ())
    raw = environment.get(CUDA_VISIBLE_DEVICES)
    devices = _parse_visible_devices(raw)
    if len(devices) != requested_count:
        raise ApptainerOptionError(
            "CUDA_VISIBLE_DEVICES does not match the requested GPU count: "
            f"requested {requested_count}, observed {'missing' if raw is None else 'invalid'}"
        )
    return GpuVisibilityEvidence(
        requested_gpu_count=requested_count,
        cuda_visible_devices=devices,
    )


def _parse_visible_devices(value: str | None) -> tuple[str, ...]:
    if value is None or value == "" or value == "-1":
        return ()
    if not isinstance(value, str):
        raise ApptainerOptionError("CUDA_VISIBLE_DEVICES must be a string")
    devices = tuple(value.split(","))
    if any(not _CUDA_DEVICE_PATTERN.fullmatch(device) for device in devices):
        raise ApptainerOptionError(
            "CUDA_VISIBLE_DEVICES contains an invalid device token"
        )
    if len(set(devices)) != len(devices):
        raise ApptainerOptionError(
            "CUDA_VISIBLE_DEVICES contains duplicate device tokens"
        )
    return devices


__all__ = [
    "CUDA_VISIBLE_DEVICES",
    "GpuVisibilityEvidence",
    "project_apptainer_gpu_options",
    "requested_gpu_count",
    "validate_cuda_visibility",
]
