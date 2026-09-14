"""Diagnostic GPU claims use the existing journal and resource provider."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.queue._managed_local import (
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    GpuResourceProvider,
    ManagedLocalError,
    ObserveRequest,
    SQLiteAgentJournal,
    _ProbeClaimOwner,
)
from loom.scheduling import CapacityAtom, ExactQuantity


pytestmark = pytest.mark.unit


def _provider() -> GpuResourceProvider:
    return GpuResourceProvider(
        GpuResourcePlanner.claim_contracts,
        (
            CapacityAtom(
                "gpu", "agent:gpu", ExactQuantity(1), "count", ExactQuantity(1)
            ),
        ),
        bindings={"agent:gpu": "GPU-owned"},
    )


def _command(provider: GpuResourceProvider) -> ClaimCommand:
    observation = provider.observe(ObserveRequest("agent", "maintenance", "observe"))
    claim = GpuResourcePlanner()._claim(
        observation.atoms, "exclusive", "nvidia", observation.availability_revision
    )
    return ClaimCommand(
        _ProbeClaimOwner("diagnostic-probe:test", "agent"),
        "probe-command",
        claim,
        provider.descriptor,
    )


def _journal(root: Path) -> SQLiteAgentJournal:
    journal = SQLiteAgentJournal(root / "journal.sqlite")
    journal._initialize()
    return SQLiteAgentJournal(journal.path, _allow_initialize=False)


def test_probe_release_requires_containment_and_creates_no_assignment(
    tmp_path: Path,
) -> None:
    provider, journal = _provider(), _journal(tmp_path)
    command = _command(provider)
    probe_id = command.assignment.assignment_id
    journal.reserve_probe(command)
    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    assert provider.worker_environment(command) == {"CUDA_VISIBLE_DEVICES": "GPU-owned"}
    journal.mark_probe_launch_intent(probe_id)
    with pytest.raises(ManagedLocalError, match="cleanup is unproven"):
        journal.release_probe(probe_id, {"gpu": provider})
    with pytest.raises(ManagedLocalError, match="cannot be relaunched"):
        journal.reserve_probe(command)
    with pytest.raises(ManagedLocalError, match="lifecycle conflicts"):
        journal.mark_probe_launch_intent(probe_id)
    journal.mark_probe_contained(probe_id)
    assert journal.release_probe(probe_id, {"gpu": provider})
    assert journal.release_probe(probe_id, {"gpu": provider})
    assert journal.retained_claim_commands() == ()
    assert (
        provider.observe(ObserveRequest("agent", "maintenance", "released")).atoms
        == command.claim.atoms
    )
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM assignments").fetchone()[0] == 0
        assert (
            connection.execute("SELECT state FROM diagnostic_probes").fetchone()[0]
            == "released"
        )


def test_probe_refreshes_existing_composite_gpu_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.queue._gpu_probe import _refresh_probe_gpu_occupancy
    from loom.queue._managed_local import _compose_agent_resource_providers
    from loom.queue.gpu.occupancy import (
        GpuOccupancyMonitor,
        GpuProcessObservation,
        NvidiaSmiGpuProcessObserver,
    )

    queried = []

    def observe(observer):
        queried.append(observer.selected_uuids)
        return {
            uuid: GpuProcessObservation(
                uuid,
                True,
                uuid == "GPU-a",
                "external_process_detected" if uuid == "GPU-a" else "available",
            )
            for uuid in observer.selected_uuids
        }

    monkeypatch.setattr(NvidiaSmiGpuProcessObserver, "observe", observe)
    members = tuple(
        GpuResourceProvider(
            GpuResourcePlanner.claim_contracts,
            (
                CapacityAtom(
                    "gpu", f"agent:{uuid}", ExactQuantity(1), "count", ExactQuantity(1)
                ),
            ),
            bindings={f"agent:{uuid}": uuid},
            occupancy_monitor=GpuOccupancyMonitor((uuid,)),
        )
        for uuid in ("GPU-a", "GPU-b")
    )
    provider = _compose_agent_resource_providers(members)["gpu"]
    request = ObserveRequest("agent", "maintenance", "observe")
    assert provider.observe(request).atoms == () and queried == []
    _refresh_probe_gpu_occupancy(provider)
    observation = provider.observe(request)
    assert set(queried) == {("GPU-a",), ("GPU-b",)}
    assert [atom.local_capacity_key for atom in observation.atoms] == ["agent:GPU-b"]
    assert {
        item.local_capacity_key: item.reason_code
        for item in observation.resource_status
    } == {
        "agent:GPU-a": "external_process_detected",
        "agent:GPU-b": "available",
    }


@pytest.mark.parametrize("last_fact", ("reserved", "launch_intent", "contained"))
def test_unreleased_probe_survives_reopen_and_withholds_capacity(
    tmp_path: Path, last_fact: str
) -> None:
    provider, journal = _provider(), _journal(tmp_path)
    command = _command(provider)
    probe_id = command.assignment.assignment_id
    journal.reserve_probe(command)
    provider.prepare(command)
    provider.activate(command)
    if last_fact != "reserved":
        journal.mark_probe_launch_intent(probe_id)
    if last_fact == "contained":
        journal.mark_probe_contained(probe_id)
    reopened = SQLiteAgentJournal(journal.path, _allow_initialize=False)
    retained = reopened.retained_claim_commands()
    assert retained == (command,)
    replacement = _provider()
    replacement.restore_capacity_holding(retained[0])
    observation = replacement.observe(ObserveRequest("agent", "maintenance", "restart"))
    assert observation.atoms == ()
    assert observation.live_claim_ids == (probe_id,)
    if last_fact != "contained":
        with pytest.raises(ManagedLocalError, match="cleanup is unproven"):
            reopened.release_probe(probe_id, {"gpu": replacement})


def test_indeterminate_provider_release_keeps_durable_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, journal = _provider(), _journal(tmp_path)
    command = _command(provider)
    probe_id = command.assignment.assignment_id
    journal.reserve_probe(command)
    provider.prepare(command)
    provider.activate(command)
    journal.mark_probe_launch_intent(probe_id)
    journal.mark_probe_contained(probe_id)
    monkeypatch.setattr(
        provider,
        "release",
        lambda item: ClaimResult(
            ClaimOutcome.INDETERMINATE, item.operation_id, item.claim.fingerprint
        ),
    )
    assert not journal.release_probe(probe_id, {"gpu": provider})
    assert SQLiteAgentJournal(
        journal.path, _allow_initialize=False
    ).retained_claim_commands() == (command,)


def test_process_death_after_launch_intent_preserves_claim(tmp_path: Path) -> None:
    import subprocess
    import sys

    journal = _journal(tmp_path)
    script = """
import os, sys
from pathlib import Path
from loom.queue._managed_local import SQLiteAgentJournal
from tests.unit.loom.queue.test_gpu_probe import _provider, _command
provider = _provider()
command = _command(provider)
journal = SQLiteAgentJournal(Path(sys.argv[1]), _allow_initialize=False)
journal.reserve_probe(command)
provider.prepare(command)
provider.activate(command)
journal.mark_probe_launch_intent(command.assignment.assignment_id)
os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(journal.path)], check=False, timeout=10
    )
    assert result.returncode == 23
    retained = SQLiteAgentJournal(
        journal.path, _allow_initialize=False
    ).retained_claim_commands()
    assert retained == (_command(_provider()),)
    provider = _provider()
    provider.restore_capacity_holding(retained[0])
    assert (
        provider.observe(ObserveRequest("agent", "maintenance", "restart")).atoms == ()
    )
    with pytest.raises(ManagedLocalError, match="cleanup is unproven"):
        journal.release_probe(retained[0].assignment.assignment_id, {"gpu": provider})
