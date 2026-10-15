"""Finite infrastructure stages, importable in the selected workload installation.

No framework is imported until the GPU stage executes. These checks say nothing
about scientific accuracy or throughput.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import importlib
import os
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext

STORAGE_BYTES = 65 * 1024 * 1024


def verify_storage(path: Path) -> dict[str, Any]:
    """Read the complete 65 MiB publication; independently derive every byte.

    Offset ``i`` must contain ``i % 251``. Neither a producer digest nor a prefix
    read establishes success. Bounded chunks avoid retaining the artifact in RAM.
    """
    actual, expected = hashlib.sha256(), hashlib.sha256()
    size = 0
    pattern = bytes(range(251))
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            reference = (pattern * ((len(chunk) + 500) // 251))[size % 251 :][
                : len(chunk)
            ]
            actual.update(chunk)
            expected.update(reference)
            size += len(chunk)
            if size > STORAGE_BYTES:
                raise ValueError("storage publication is oversized")
    if size != STORAGE_BYTES or actual.digest() != expected.digest():
        raise ValueError("storage publication size/hash mismatch")
    return {"bytes": size, "sha256": actual.hexdigest()}


def gpu_probe() -> dict[str, Any]:
    """Synchronize float32 2x2 matrix multiplication on one UUID-bound CUDA GPU.

    The CUDA properties UUID is observed independently of the launch environment;
    the operator additionally compares it with native parent-owned claim evidence.
    Missing Torch or UUID observation is unsupported, never a passing fallback.
    """
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        return {
            "outcome": "unsupported",
            "code": "unsupported_check",
            "reason": "torch_unavailable",
        }
    binding = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    try:
        expected = "GPU-" + str(UUID(binding.removeprefix("GPU-")))
    except ValueError as exc:
        raise ValueError("GPU probe requires one full UUID binding") from exc
    if expected != binding or torch.cuda.device_count() != 1:
        raise ValueError("GPU probe requires exactly one bound CUDA device")
    properties = torch.cuda.get_device_properties(0)
    if not hasattr(properties, "uuid"):
        return {
            "outcome": "unsupported",
            "code": "unsupported_check",
            "reason": "cuda_uuid_unavailable",
        }
    actual = "GPU-" + str(UUID(str(properties.uuid).removeprefix("GPU-")))
    left = torch.tensor([[1, 2], [3, 4]], dtype=torch.float32, device="cuda:0")
    right = torch.tensor([[5, 6], [7, 8]], dtype=torch.float32, device="cuda:0")
    result = left @ right
    torch.cuda.synchronize(0)
    values = result.cpu().tolist()
    if actual != binding or values != [[19.0, 22.0], [43.0, 50.0]]:
        raise ValueError("GPU UUID/numerical result mismatch")
    return {
        "outcome": "passed",
        "device_uuid": actual,
        "result": values,
        "torch_version": torch.__version__,
        "device_count": 1,
    }


class ProbeStage:
    """Ordinary stage producing CPU/GPU JSON or a storage publication companion.

    ``stage_config.check`` is cpu, storage or gpu. Inputs are empty. The report
    uses json.v1; storage places values.bin beside it for native shared publication.
    CPU sums integers [0, 10000); GPU performs the fixed float32 matrix product.
    """

    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> dict[str, ArtifactRef]:
        check = context.stage_config.get("check")
        report: dict[str, Any] = {
            "check": check,
            "synthetic": True,
            "outcome": "passed",
            "run_uri": context.run_uri,
            "stage_name": context.stage_name,
            "python_version": sys.version,
            "python": sys.executable,
        }
        if check == "cpu":
            report["result"] = sum(range(10000))
        elif check == "storage":
            path = (
                context.local_output_path("report", suffix=".json").parent
                / "values.bin"
            )
            # A multiple of 251 keeps the period continuous across writes.
            block = bytes(range(251)) * 4096
            remaining = STORAGE_BYTES
            with path.open("wb") as stream:
                while remaining:
                    chunk = block[: min(len(block), remaining)]
                    stream.write(chunk)
                    remaining -= len(chunk)
            report["bytes"] = STORAGE_BYTES
        elif check == "gpu":
            report.update(gpu_probe())
        else:
            raise ValueError("unknown infrastructure check")
        return {
            "report": context.save_artifact(
                "report", report, artifact_type="json", codec_key="json.v1"
            )
        }


def probe_configuration(check: str, agent_id: str) -> dict[str, Any]:
    """Compose fixed probe intent for native capture and placement on one agent."""
    if check not in {"cpu", "storage", "gpu"}:
        raise ValueError("unknown infrastructure check")
    resources: dict[str, Any] = {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
    if check == "gpu":
        resources["gpu"] = {
            "kind": "gpu",
            "amount": 1,
            "unit": "count",
            "attributes": {"allocation_mode": "exclusive"},
        }
    return {
        "pipeline": {
            "name": "fleet-check",
            "stages": [
                {
                    "name": "probe",
                    "factory": {"_target_": "loom.fleet.probes.ProbeStage"},
                    "config": {"check": check},
                    "placement": {"target": agent_id},
                    "resources": {"entries": resources},
                    "outputs": {
                        "report": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        },
        "runtime": {
            "executor": "local",
            "resource_policy": {
                "account_for": "all",
                "enforce": ["gpu"] if check == "gpu" else [],
            },
            "reliability": {"timeout": {"enabled": True, "duration_seconds": 120}},
        },
    }
