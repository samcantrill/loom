"""Non-exclusive CUDA capability checking in the selected resident runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from loom.queue._resident_probe import run_resident_probe
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.queue._remote_stage_execution import ResidentExecutionProfile


_SCRIPT = """
import contextlib, json, sys
with contextlib.redirect_stdout(sys.stderr):
    from loom.fleet.probes import gpu_probe
    result = gpu_probe()
print(json.dumps(result))
"""


def gpu_capability(profile: ResidentExecutionProfile) -> dict[str, object]:
    """Check one declared CUDA device without acquiring scheduler capacity.

    This fixed, bounded probe may share an occupied GPU. It proves device
    visibility, a float32 2x2 matrix product and process containment, not
    exclusive scheduling, available memory, throughput or claim release.
    Provider occupancy and live resource claims are neither read nor changed.
    """
    return _probe(profile.launch_profile, profile.gpu_devices,
                  profile.readiness_requirements.timeout_seconds, profile.descriptor.to_dict())


def submitted_gpu_capability(policy, execution, inventory, *, workspace):
    """Probe an explicit submitted image using the agent's declared GPU inventory."""
    launch = policy.launch_profile(execution, workspace=workspace)
    return _probe(launch, inventory.gpu_devices, 120, policy.capability.to_dict())


def _probe(launch, gpu_devices, timeout_seconds, identity):
    devices = sorted(
        (device for device in gpu_devices if device.descriptor.healthy),
        key=lambda device: device.descriptor.device_id,
    )
    evidence: dict[str, object] = {
        "mode": "nonexclusive",
        "scope": "cuda_capability",
        "profile": identity,
        **({"execution": launch.submitted_execution.to_dict()}
           if launch.submitted_execution is not None else {}),
        "exclusive_scheduling": "not_tested",
    }
    if not devices:
        return {**evidence, "outcome": "unsupported", "code": "no_healthy_declared_gpu"}
    device = devices[0]
    binding = device.binding_value
    try:
        canonical = "GPU-" + str(UUID(binding.removeprefix("GPU-")))
    except ValueError:
        canonical = ""
    if canonical != binding or device.descriptor.device_id != binding:
        return {**evidence, "outcome": "unsupported", "code": "uuid_binding_required"}
    evidence["device_uuid"] = binding
    # Resource intent enables the container's GPU transport and UUID visibility.
    # No scheduler/provider is involved; this is explicitly not a resource claim.
    runtime: dict[str, PlainData] = {
        "resources": {
            "schema_version": 2,
            "entries": {"gpu": {"kind": "gpu", "amount": 1, "unit": "count", "attributes": {}}},
        },
        "resource_policy": {"account_for": [], "enforce": ["gpu"]},
        "resource_selection": {"account_for": [], "enforce": ["gpu"]},
    }
    result = run_resident_probe(
        launch,
        _SCRIPT,
        {},
        timeout_seconds=timeout_seconds,
        device_environment={"CUDA_VISIBLE_DEVICES": binding},
        runtime=runtime,
    )
    evidence["contained"] = result.contained
    if result.failure is not None or not result.contained:
        return {
            **evidence,
            "outcome": "failed",
            "code": "gpu_capability_failed",
            "reason": result.failure or "probe containment unconfirmed",
        }
    observed = dict(result.payload or {})
    passed = (
        observed.get("outcome") == "passed"
        and observed.get("device_uuid") == binding
        and observed.get("device_count") == 1
        and observed.get("result") == [[19.0, 22.0], [43.0, 50.0]]
    )
    return {
        **evidence,
        "outcome": "passed" if passed else "failed",
        "code": "gpu_capability_complete" if passed else "gpu_uuid_or_result_mismatch",
        "probe": observed,
    }
