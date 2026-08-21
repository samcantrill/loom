"""Unit coverage for explicit, failure-closed NVIDIA CLI discovery."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from loom.queue import QueueServiceError
from loom.queue.gpu import LocalGpuInventoryProvider
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider


DEVICE_ARGV = (
    "nvidia-smi",
    "--query-gpu=index,uuid,pci.bus_id",
    "--format=csv,noheader,nounits",
)
TOPOLOGY_ARGV = ("nvidia-smi", "topo", "-m")


def test_device_discovery_uses_fixed_argv_uuid_identity_and_no_topology() -> None:
    runner = _FakeRunner(
        _result("1, GPU-b, 00000000:02:00.0\n0, GPU-a, 00000000:01:00.0\n")
    )
    provider = NvidiaSmiGpuInventoryProvider(command_runner=runner)

    inventory = provider.discover()

    assert isinstance(provider, LocalGpuInventoryProvider)
    assert runner.argvs == [DEVICE_ARGV]
    assert [(item.device_id, item.binding_value) for item in inventory.devices] == [
        ("GPU-a", "GPU-a"),
        ("GPU-b", "GPU-b"),
    ]
    assert inventory.links == ()


def test_topology_discovery_maps_complete_symmetric_matrix_to_ranked_links() -> None:
    runner = _FakeRunner(
        _result("0, GPU-a, 00000000:01:00.0\n1, GPU-b, 00000000:02:00.0\n"),
        _result(
            """
                GPU0 GPU1
GPU0     X    NV4
GPU1    NV4    X

Legend:
"""
        ),
    )

    inventory = NvidiaSmiGpuInventoryProvider(
        include_topology=True, command_runner=runner
    ).get_inventory()

    assert runner.argvs == [DEVICE_ARGV, TOPOLOGY_ARGV]
    assert [
        (link.left_id, link.right_id, link.rank, link.kind) for link in inventory.links
    ] == [("GPU-a", "GPU-b", 0, "nvlink")]


@pytest.mark.parametrize(
    ("device_output", "reason_code"),
    [
        ("", "nvidia_smi.inventory_empty"),
        ("0, GPU-a\n", "nvidia_smi.device_rows_malformed"),
        (
            "0, GPU-a, 00000000:01:00.0\n0, GPU-b, 00000000:02:00.0\n",
            "nvidia_smi.device_rows_duplicate",
        ),
        (
            "0, GPU-a, 00000000:01:00.0\n1, GPU-a, 00000000:02:00.0\n",
            "nvidia_smi.device_rows_duplicate",
        ),
        (
            "0, GPU invalid, 00000000:01:00.0\n",
            "nvidia_smi.device_rows_malformed",
        ),
    ],
)
def test_device_discovery_fails_closed_for_invalid_rows(
    device_output: str, reason_code: str
) -> None:
    with pytest.raises(QueueServiceError) as raised:
        NvidiaSmiGpuInventoryProvider(
            command_runner=_FakeRunner(_result(device_output))
        ).discover()

    assert getattr(raised.value, "reason_code") == reason_code


def test_command_absence_and_nonzero_exit_are_safe_typed_failures() -> None:
    unavailable = NvidiaSmiGpuInventoryProvider(command_runner=_UnavailableRunner())
    nonzero = NvidiaSmiGpuInventoryProvider(
        command_runner=_FakeRunner(_result("operator-only stderr", returncode=1))
    )

    with pytest.raises(QueueServiceError) as unavailable_error:
        unavailable.discover()
    with pytest.raises(QueueServiceError) as nonzero_error:
        nonzero.discover()

    assert (
        getattr(unavailable_error.value, "reason_code")
        == "nvidia_smi.command_unavailable"
    )
    assert getattr(nonzero_error.value, "reason_code") == "nvidia_smi.command_failed"
    assert "operator-only stderr" not in str(nonzero_error.value)


@pytest.mark.parametrize(
    ("topology", "reason_code"),
    [
        (
            "GPU0 GPU2\nGPU0 X NV4\nGPU2 NV4 X\n",
            "nvidia_smi.topology_labels_inconsistent",
        ),
        (
            "GPU0 GPU1\nGPU0 X CXL\nGPU1 CXL X\n",
            "nvidia_smi.topology_token_unknown",
        ),
        (
            "GPU0 GPU1\nGPU0 X NV4\nGPU1 PIX X\n",
            "nvidia_smi.topology_matrix_inconsistent",
        ),
        (
            "GPU0 GPU1\nGPU0 X NV4\n",
            "nvidia_smi.topology_matrix_incomplete",
        ),
    ],
)
def test_topology_discovery_fails_closed_for_unusable_matrix(
    topology: str, reason_code: str
) -> None:
    runner = _FakeRunner(
        _result("0, GPU-a, 00000000:01:00.0\n1, GPU-b, 00000000:02:00.0\n"),
        _result(topology),
    )

    with pytest.raises(QueueServiceError) as raised:
        NvidiaSmiGpuInventoryProvider(
            include_topology=True, command_runner=runner
        ).discover()

    assert getattr(raised.value, "reason_code") == reason_code


def _result(stdout: str, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("nvidia-smi",), returncode, stdout, "")


class _FakeRunner:
    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self._results = list(results)
        self.argvs: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.argvs.append(tuple(argv))
        return self._results.pop(0)


class _UnavailableRunner:
    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(argv[0])
