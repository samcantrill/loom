"""Exercise NVIDIA discovery and planning without managed-local execution."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

from loom.queue.gpu import grouped, plan_local_gpu_pool, shares_per_gpu, whole_gpus
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider


def main() -> None:
    inventory = NvidiaSmiGpuInventoryProvider(
        include_topology=True,
        command_runner=_FakeNvidiaSmi(),
    ).discover()
    whole = plan_local_gpu_pool(inventory, whole_gpus())
    shares = plan_local_gpu_pool(inventory, shares_per_gpu(2))
    grouped_plan = plan_local_gpu_pool(inventory, grouped(2, grouping="topology"))

    print(f"whole_capacity: {whole.capacity}")
    print(f"shares_capacity: {shares.capacity}")
    print(f"grouped_capacity: {grouped_plan.capacity}")
    print(f"safe_summary_has_uuid: {'GPU-' in repr(grouped_plan.safe_summary())}")


class _FakeNvidiaSmi:
    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "--query-gpu=index,uuid,pci.bus_id" in argv:
            stdout = (
                "0, GPU-fake-a, 00000000:01:00.0\n"
                "1, GPU-fake-b, 00000000:02:00.0\n"
            )
        elif tuple(argv) == ("nvidia-smi", "topo", "-m"):
            stdout = "GPU0 GPU1\nGPU0 X NV4\nGPU1 NV4 X\n"
        else:
            raise AssertionError(f"unexpected NVIDIA argv: {argv!r}")
        return subprocess.CompletedProcess(argv, 0, stdout, "")


if __name__ == "__main__":
    main()
