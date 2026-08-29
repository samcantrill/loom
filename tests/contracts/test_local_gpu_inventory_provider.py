"""Contract coverage for explicit local GPU inventory providers."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

from loom.queue.gpu import LocalGpuInventory, LocalGpuInventoryProvider
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider


def test_nvidia_provider_returns_the_immutable_generic_inventory_contract() -> None:
    provider = NvidiaSmiGpuInventoryProvider(command_runner=_Runner())

    assert isinstance(provider, LocalGpuInventoryProvider)
    assert isinstance(provider.get_inventory(), LocalGpuInventory)
    assert provider.get_inventory().devices == provider.discover().devices


class _Runner:
    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert tuple(argv) == (
            "nvidia-smi",
            "--query-gpu=index,uuid,pci.bus_id",
            "--format=csv,noheader,nounits",
        )
        return subprocess.CompletedProcess(argv, 0, "0, GPU-a, 00000000:01:00.0\n", "")
