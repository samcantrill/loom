"""Unit coverage for explicit, failure-closed NVIDIA CLI discovery."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from loom.queue import QueueServiceError
from loom.queue.gpu import (
    LocalGpuDevice,
    LocalGpuInventory,
    LocalGpuInventoryProvider,
    LocalGpuPoolLayout,
    plan_local_gpu_pool,
)
from loom.queue.gpu.nvidia import (
    NvidiaSmiGpuInventoryProvider,
    resolve_nvidia_gpu_selection,
)
from loom.queue.gpu.occupancy import NvidiaSmiGpuProcessObserver


DEVICE_ARGV = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,memory.total,pci.bus_id",
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
    assert [
        (
            item.device_id,
            item.binding_value,
            item.host_index,
            item.model,
            item.vram_bytes,
        )
        for item in inventory.devices
    ] == [
        ("GPU-a", "GPU-a", 0, "test-model", 1024 * 1024**2),
        ("GPU-b", "GPU-b", 1, "test-model", 1024 * 1024**2),
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


def test_topology_prefers_more_direct_nvlink_evidence() -> None:
    inventory = NvidiaSmiGpuInventoryProvider(
        include_topology=True,
        command_runner=_FakeRunner(
            _result(
                "0, GPU-a, 00000000:01:00.0\n"
                "1, GPU-b, 00000000:02:00.0\n"
                "2, GPU-c, 00000000:03:00.0\n"
                "3, GPU-d, 00000000:04:00.0\n"
            ),
            _result(
                "GPU0 GPU1 GPU2 GPU3\n"
                "GPU0 X NV4 PIX PIX\n"
                "GPU1 NV4 X PIX PIX\n"
                "GPU2 PIX PIX X NV1\n"
                "GPU3 PIX PIX NV1 X\n"
            ),
        ),
    ).discover()

    plan = plan_local_gpu_pool(
        inventory, LocalGpuPoolLayout.grouped(2, grouping="topology")
    )

    assert plan.operator_summary()["groups"] == [("GPU-a", "GPU-b"), ("GPU-c", "GPU-d")]
    ranks = {(link.left_id, link.right_id): link.rank for link in inventory.links}
    assert ranks[("GPU-a", "GPU-b")] < ranks[("GPU-c", "GPU-d")]
    assert ranks[("GPU-c", "GPU-d")] < ranks[("GPU-a", "GPU-c")]


def test_topology_normalizes_natural_enumeration_permutations() -> None:
    first = NvidiaSmiGpuInventoryProvider(
        include_topology=True,
        command_runner=_FakeRunner(
            _result(
                "0, GPU-a, 00000000:01:00.0\n"
                "1, GPU-b, 00000000:02:00.0\n"
                "2, GPU-c, 00000000:03:00.0\n"
                "3, GPU-d, 00000000:04:00.0\n"
            ),
            _result(
                "GPU0 GPU1 GPU2 GPU3\n"
                "GPU0 X NV4 PIX PIX\n"
                "GPU1 NV4 X PIX PIX\n"
                "GPU2 PIX PIX X NV1\n"
                "GPU3 PIX PIX NV1 X\n"
            ),
        ),
    ).discover()
    permuted = NvidiaSmiGpuInventoryProvider(
        include_topology=True,
        command_runner=_FakeRunner(
            _result(
                "0, GPU-c, 00000000:03:00.0\n"
                "1, GPU-a, 00000000:01:00.0\n"
                "2, GPU-d, 00000000:04:00.0\n"
                "3, GPU-b, 00000000:02:00.0\n"
            ),
            _result(
                "GPU0 GPU1 GPU2 GPU3\n"
                "GPU0 X PIX NV1 PIX\n"
                "GPU1 PIX X PIX NV4\n"
                "GPU2 NV1 PIX X PIX\n"
                "GPU3 PIX NV4 PIX X\n"
            ),
        ),
    ).discover()

    first_plan = plan_local_gpu_pool(
        first, LocalGpuPoolLayout.grouped(2, grouping="topology")
    )
    permuted_plan = plan_local_gpu_pool(
        permuted, LocalGpuPoolLayout.grouped(2, grouping="topology")
    )

    # Stable UUID/topology planning remains deterministic, but a host index
    # renumbering is retained as distinct inventory evidence for reconciliation.
    assert permuted != first
    assert permuted_plan.fingerprint == first_plan.fingerprint
    assert (
        permuted_plan.operator_summary()["groups"]
        == first_plan.operator_summary()["groups"]
    )


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


def test_selection_resolves_indices_to_stable_uuid_identities() -> None:
    inventory = LocalGpuInventory(
        (
            LocalGpuDevice("GPU-a", "GPU-a", host_index=0, model="a", vram_bytes=1),
            LocalGpuDevice("GPU-b", "GPU-b", host_index=2, model="b", vram_bytes=1),
            LocalGpuDevice("GPU-c", "GPU-c", host_index=5, model="c", vram_bytes=1),
        )
    )

    assert [
        item.device_id for item in resolve_nvidia_gpu_selection("0,2,5", inventory)
    ] == ["GPU-a", "GPU-b", "GPU-c"]
    assert [
        item.device_id
        for item in resolve_nvidia_gpu_selection("GPU-c,GPU-a", inventory)
    ] == ["GPU-c", "GPU-a"]
    assert resolve_nvidia_gpu_selection("none", inventory) == ()


@pytest.mark.parametrize("selection", ("", "2-0", "0,0", "0-2,2", "1", "0,GPU-a"))
def test_selection_rejects_ambiguous_or_unknown_devices(selection: str) -> None:
    inventory = LocalGpuInventory(
        (LocalGpuDevice("GPU-a", "GPU-a", host_index=0, model="a", vram_bytes=1),)
    )

    with pytest.raises(QueueServiceError):
        resolve_nvidia_gpu_selection(selection, inventory)


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
            "GPU0 GPU1\nGPU0 X NV1\nGPU1 NV4 X\n",
            "nvidia_smi.topology_matrix_inconsistent",
        ),
        (
            "GPU0 GPU1\nGPU0 X NV0\nGPU1 NV0 X\n",
            "nvidia_smi.topology_token_unknown",
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


def test_process_observer_blocks_compute_graphics_and_combined_contexts() -> None:
    runner = _ProcessRunner(
        subprocess.CompletedProcess(
            ("nvidia-smi",),
            0,
            """
<nvidia_smi_log>
  <gpu><uuid>GPU-a</uuid><processes /></gpu>
  <gpu><uuid>GPU-b</uuid><processes><process_info><type>C</type><used_memory>N/A</used_memory></process_info></processes></gpu>
  <gpu><uuid>GPU-c</uuid><processes><process_info><type>G</type></process_info></processes></gpu>
  <gpu><uuid>GPU-d</uuid><processes><process_info><type>C+G</type></process_info></processes></gpu>
</nvidia_smi_log>
""",
            "",
        )
    )

    observations = NvidiaSmiGpuProcessObserver(
        ("GPU-a", "GPU-b", "GPU-c", "GPU-d"), command_runner=runner
    ).observe()

    assert runner.argvs == [
        (
            "nvidia-smi",
            "--query",
            "--xml-format",
            "--id=GPU-a,GPU-b,GPU-c,GPU-d",
        )
    ]
    assert [
        (item.uuid, item.query_succeeded, item.has_gpu_process)
        for item in observations.values()
    ] == [
        ("GPU-a", True, False),
        ("GPU-b", True, True),
        ("GPU-c", True, True),
        ("GPU-d", True, True),
    ]


def test_process_observer_withholds_missing_and_malformed_selected_evidence() -> None:
    malformed = NvidiaSmiGpuProcessObserver(
        ("GPU-a", "GPU-b"), command_runner=_ProcessRunner(_process_result("<not XML"))
    ).observe()
    missing = NvidiaSmiGpuProcessObserver(
        ("GPU-a", "GPU-b"),
        command_runner=_ProcessRunner(
            _process_result(
                "<nvidia_smi_log><gpu><uuid>GPU-a</uuid><processes /></gpu></nvidia_smi_log>"
            )
        ),
    ).observe()

    assert [item.reason_code for item in malformed.values()] == [
        "query_malformed",
        "query_malformed",
    ]
    assert [(item.uuid, item.reason_code) for item in missing.values()] == [
        ("GPU-a", "available"),
        ("GPU-b", "device_missing"),
    ]


def _result(stdout: str, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = "\n".join(
        _device_row(line) for line in stdout.splitlines(keepends=False)
    ) + ("\n" if stdout.endswith("\n") else "")
    return subprocess.CompletedProcess(("nvidia-smi",), returncode, stdout, "")


def _device_row(line: str) -> str:
    parts = line.split(",")
    if len(parts) == 3 and parts[0].strip().isdecimal():
        index, uuid, pci = parts
        return f"{index},{uuid},test-model,1024,{pci}"
    return line


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


def _process_result(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("nvidia-smi",), 0, stdout, "")


class _ProcessRunner:
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.argvs: list[tuple[str, ...]] = []

    def __call__(
        self, argv: Sequence[str], timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        assert timeout_seconds == 2
        self.argvs.append(tuple(argv))
        return self.result


@pytest.mark.parametrize(
    "processes",
    ("N/A", "<error>unsupported</error>", "<process>unknown representation</process>"),
)
def test_process_observer_does_not_treat_unsupported_output_as_idle(
    processes: str,
) -> None:
    observer = NvidiaSmiGpuProcessObserver(
        ("GPU-a",),
        command_runner=_ProcessRunner(
            _process_result(
                f"<nvidia_smi_log><gpu><uuid>GPU-a</uuid><processes>{processes}</processes></gpu></nvidia_smi_log>"
            )
        ),
    )
    result = observer.observe()["GPU-a"]
    assert not result.query_succeeded
    assert result.reason_code == "query_incomplete"


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        (subprocess.TimeoutExpired("nvidia-smi", 2), "query_timeout"),
        (PermissionError("private diagnostic"), "query_permission_denied"),
        (subprocess.CompletedProcess(["nvidia-smi"], 1, "", "private diagnostic"), "query_failed"),
    ],
)
def test_process_observation_command_failures_withhold_every_selected_gpu(
    failure: Exception | subprocess.CompletedProcess[str], expected_reason: str
) -> None:
    def run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        assert argv[-1] == "--id=GPU-a,GPU-b"
        assert timeout == 2
        if isinstance(failure, Exception):
            raise failure
        return failure

    observations = NvidiaSmiGpuProcessObserver(("GPU-a", "GPU-b"), command_runner=run).observe()
    assert set(observations) == {"GPU-a", "GPU-b"}
    assert all(not item.query_succeeded for item in observations.values())
    assert {item.reason_code for item in observations.values()} == {expected_reason}
    assert "private diagnostic" not in repr(observations)


def test_process_observation_ignores_unselected_gpu_processes() -> None:
    runner = _ProcessRunner(_process_result(
        "<nvidia_smi_log><gpu><uuid>GPU-a</uuid><processes/></gpu>"
        "<gpu><uuid>GPU-b</uuid><processes><process_info>"
        "<type>C</type><pid>123</pid></process_info></processes></gpu></nvidia_smi_log>"
    ))
    observations = NvidiaSmiGpuProcessObserver(("GPU-a",), command_runner=runner).observe()
    assert set(observations) == {"GPU-a"}
    assert observations["GPU-a"].query_succeeded
    assert not observations["GPU-a"].has_gpu_process
