"""Explicit NVIDIA CLI inventory discovery for local GPU pool planning.

Importing this module is inert.  Discovery is an explicit call so applications
can choose the NVIDIA environment and decide when an external observation is
appropriate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import csv
import re
import subprocess

from loom.queue.errors import QueueServiceError

from .local import LocalGpuDevice, LocalGpuInventory, LocalGpuLink


_DEVICE_QUERY_ARGV = (
    "nvidia-smi",
    "--query-gpu=index,uuid,pci.bus_id",
    "--format=csv,noheader,nounits",
)
_TOPOLOGY_ARGV = ("nvidia-smi", "topo", "-m")
_GPU_LABEL = re.compile(r"GPU(?P<index>[0-9]+)$")
_NVLINK_TOKEN = re.compile(r"NV(?P<count>[1-9][0-9]*)$")
_GPU_UUID = re.compile(r"GPU-[A-Za-z0-9-]+$")
_TOPOLOGY_KINDS = {
    "PIX": (1, "pcie_same_switch"),
    "PXB": (2, "pcie_multi_switch"),
    "PHB": (3, "pcie_host_bridge"),
    "NODE": (4, "numa"),
    "SYS": (5, "system"),
}


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(tuple(argv), capture_output=True, check=False, text=True)


@dataclass(frozen=True, slots=True)
class _NvidiaSmiDiscoveryError(QueueServiceError):
    """Safe, category-bearing external-discovery failure."""

    reason_code: str
    command: str
    return_category: str

    def __str__(self) -> str:
        return (
            "NVIDIA GPU discovery failed: "
            f"{self.reason_code} ({self.command}; {self.return_category})"
        )


@dataclass(frozen=True, slots=True)
class NvidiaSmiGpuInventoryProvider:
    """Discover one immutable local GPU inventory with fixed ``nvidia-smi`` argv.

    ``command_runner`` receives the complete argv tuple and must return a
    text-mode :class:`subprocess.CompletedProcess`.  It is intentionally
    injectable for tests and project-local operational wrappers.
    """

    include_topology: bool = False
    command_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = (
        _default_runner
    )

    def get_inventory(self) -> LocalGpuInventory:
        """Satisfy the generic explicit inventory-provider protocol."""

        return self.discover()

    def discover(self) -> LocalGpuInventory:
        """Run the selected queries once and return normalized GPU observations."""

        observations = _parse_devices(self._run(_DEVICE_QUERY_ARGV))
        devices = tuple(
            LocalGpuDevice(device_id=observation.uuid, binding_value=observation.uuid)
            for observation in observations
        )
        if not self.include_topology:
            return LocalGpuInventory(devices)
        return LocalGpuInventory(
            devices,
            _parse_topology(
                self._run(_TOPOLOGY_ARGV),
                observations=observations,
            ),
        )

    def _run(self, argv: tuple[str, ...]) -> str:
        try:
            result = self.command_runner(argv)
        except FileNotFoundError:
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.command_unavailable", argv[0], "unavailable"
            ) from None
        except OSError:
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.command_execution_failed", argv[0], "execution_error"
            ) from None
        except Exception:  # noqa: BLE001
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.command_execution_failed", argv[0], "runner_error"
            ) from None
        if result.returncode != 0:
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.command_failed", argv[0], "nonzero_exit"
            )
        if not isinstance(result.stdout, str):
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.command_output_invalid", argv[0], "invalid_output"
            )
        return result.stdout


def _parse_devices(stdout: str) -> tuple["_DeviceObservation", ...]:
    try:
        rows = list(csv.reader(stdout.splitlines()))
    except csv.Error:
        raise _NvidiaSmiDiscoveryError(
            "nvidia_smi.device_rows_malformed", "nvidia-smi", "invalid_output"
        ) from None
    observations: list[_DeviceObservation] = []
    seen_indices: set[int] = set()
    seen_uuids: set[str] = set()
    seen_pci_bus_ids: set[str] = set()
    for row in rows:
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 3:
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.device_rows_malformed", "nvidia-smi", "invalid_output"
            )
        index_text, uuid, pci_bus_id = (value.strip() for value in row)
        if (
            not index_text.isdecimal()
            or not _GPU_UUID.fullmatch(uuid)
            or not pci_bus_id
            or any(character.isspace() or character == "\0" for character in pci_bus_id)
        ):
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.device_rows_malformed", "nvidia-smi", "invalid_output"
            )
        index = int(index_text)
        if (
            index in seen_indices
            or uuid in seen_uuids
            or pci_bus_id in seen_pci_bus_ids
        ):
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.device_rows_duplicate", "nvidia-smi", "invalid_output"
            )
        try:
            LocalGpuDevice(device_id=uuid, binding_value=uuid)
        except QueueServiceError:
            raise _NvidiaSmiDiscoveryError(
                "nvidia_smi.device_rows_malformed", "nvidia-smi", "invalid_output"
            ) from None
        seen_indices.add(index)
        seen_uuids.add(uuid)
        seen_pci_bus_ids.add(pci_bus_id)
        observations.append(_DeviceObservation(index, uuid, pci_bus_id))
    if not observations:
        raise _NvidiaSmiDiscoveryError(
            "nvidia_smi.inventory_empty", "nvidia-smi", "invalid_output"
        )
    return tuple(observations)


def _parse_topology(
    stdout: str, *, observations: tuple["_DeviceObservation", ...]
) -> tuple[LocalGpuLink, ...]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise _topology_error("topology_matrix_incomplete")
    header = lines[0].split()
    labels: list[str] = []
    for token in header:
        if _GPU_LABEL.fullmatch(token):
            labels.append(token)
        elif labels:
            break
    expected_labels = {f"GPU{item.index}" for item in observations}
    if not labels or len(labels) != len(set(labels)) or set(labels) != expected_labels:
        raise _topology_error("topology_labels_inconsistent")
    rows: dict[str, list[str]] = {}
    for line in lines[1:]:
        if line.startswith("Legend:"):
            break
        values = line.split()
        if not values or not _GPU_LABEL.fullmatch(values[0]):
            continue
        label, links = values[0], values[1 : 1 + len(labels)]
        if len(links) != len(labels) or label not in expected_labels or label in rows:
            raise _topology_error("topology_matrix_incomplete")
        rows[label] = links
    if set(rows) != expected_labels:
        raise _topology_error("topology_matrix_incomplete")
    by_label = {f"GPU{item.index}": item.uuid for item in observations}
    pair_tokens: list[tuple[str, str, str]] = []
    for left_index, left_label in enumerate(labels):
        if rows[left_label][left_index] != "X":
            raise _topology_error("topology_matrix_inconsistent")
        for right_index in range(left_index + 1, len(labels)):
            right_label = labels[right_index]
            forward = rows[left_label][right_index]
            reverse = rows[right_label][left_index]
            if forward != reverse:
                raise _topology_error("topology_matrix_inconsistent")
            pair_tokens.append((left_label, right_label, forward))
    max_nvlink_count = max(
        (_nvlink_count(token) for _, _, token in pair_tokens), default=0
    )
    parsed: list[LocalGpuLink] = []
    for left_label, right_label, token in pair_tokens:
        rank, kind = _topology_value(token, max_nvlink_count=max_nvlink_count)
        parsed.append(
            LocalGpuLink(by_label[left_label], by_label[right_label], rank, kind)
        )
    return tuple(parsed)


def _topology_value(token: str, *, max_nvlink_count: int) -> tuple[int, str]:
    count = _nvlink_count(token)
    if count:
        return max_nvlink_count - count, "nvlink"
    value = _TOPOLOGY_KINDS.get(token)
    if value is None:
        raise _topology_error("topology_token_unknown")
    rank, kind = value
    return max_nvlink_count + rank, kind


def _nvlink_count(token: str) -> int:
    match = _NVLINK_TOKEN.fullmatch(token)
    return int(match["count"]) if match else 0


def _topology_error(reason_code: str) -> _NvidiaSmiDiscoveryError:
    return _NvidiaSmiDiscoveryError(
        f"nvidia_smi.{reason_code}", "nvidia-smi", "invalid_output"
    )


@dataclass(frozen=True, slots=True)
class _DeviceObservation:
    index: int
    uuid: str
    pci_bus_id: str
