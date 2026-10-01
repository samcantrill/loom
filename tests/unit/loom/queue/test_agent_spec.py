"""Protected declaration snapshots and their explicit qualification boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from typing import Any, cast

import pytest

from loom.queue import deployment
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.agent_session_transport import AgentTlsClientConfig
from loom.queue.deployment import (
    load_outbound_agent_service_config,
    qualify_agent_spec,
    read_agent_spec,
)
from loom.queue.errors import QueueConfigError, QueueServiceError
from loom.queue.resident_readiness import ResidentReadinessResult
from tests.unit.loom.queue.test_deployment import (
    _agent_config,
    _write_protected,
    _write_protected_text,
)

pytestmark = pytest.mark.unit


def _forbid(*_args: object, **_kwargs: object) -> Any:
    pytest.fail("declaration reading crossed the qualification boundary")


def _observe(profile: Any, **_kwargs: Any) -> Any:
    return replace(
        profile,
        descriptor=ResidentProfileDescriptor(
            "remote-profile",
            "v1",
            "project-observed",
            "environment-observed",
            "executor-observed",
        ),
        readiness_result=ResidentReadinessResult((), "a" * 64),
        readiness_identity="a" * 64,
    )


@pytest.mark.parametrize("composition", ["gpu", "provider", "slurm", "container"])
def test_read_does_not_qualify_or_construct_execution_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    composition: str,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    profile = payload["resident_profiles"][0]
    profile["project_root"] = "missing-project"
    profile["python_executable"] = "missing-python"
    if composition == "gpu":
        payload["resources"] = {
            "cpu_capacity": 1,
            "memory_capacity_bytes": 0,
            "gpu": {"provider": "nvidia", "devices": "GPU-unavailable"},
        }
    elif composition == "provider":
        payload["provider_factory"] = {"_target_": "uninstalled.module.factory"}
    elif composition == "slurm":
        payload["resident_profiles"] = []
        payload["slurm_profiles"] = [{"_target_": "uninstalled.module.profile"}]
    else:
        profile["container"] = {
            "kind": "apptainer",
            "container": {"image": {"reference": "/missing/image.sif"}},
            "options": {"command": "/missing/apptainer"},
            "python_executable": "/usr/bin/python3",
            "daemon_endpoint": None,
        }
        profile["shared_roots"] = {
            "dataset": {
                "host_path": "/missing/data",
                "container_path": "/loom/data",
                "access": "ro",
                "challenge": {"path": "proof", "sha256": "a" * 64},
            },
        }
    _write_protected(source, payload)
    for name in (
        "ResidentExecutionProfile",
        "qualified_resident_profile",
        "_trusted_target",
    ):
        monkeypatch.setattr(deployment, name, _forbid)
    monkeypatch.setattr(
        "loom.queue.gpu.nvidia.NvidiaSmiGpuInventoryProvider.discover", _forbid
    )
    monkeypatch.setattr(
        "loom.queue.resources.require_effective_agent_capacity", _forbid
    )
    monkeypatch.setattr("loom.queue.resident_readiness.run_resident_probe", _forbid)
    monkeypatch.setattr(
        "loom.queue.resident_readiness._container_software_identity", _forbid
    )
    monkeypatch.setattr("loom.queue.shared_execution.qualifications", _forbid)
    spec = read_agent_spec(source)
    assert spec.agent_root == tmp_path / "remote-agent"
    assert spec.source_path == source
    assert len(spec.declaration_digest) == 64
    assert spec.declarations["server_ca_path"] == str(tmp_path / "ca.crt")
    assert bool(spec.declarations["slurm_profiles"]) == (composition == "slurm")
    assert not spec.agent_root.exists()


def test_read_freezes_nested_declarations_and_qualification_snapshot(
    tmp_path: Path,
) -> None:
    spec = read_agent_spec(_agent_config(tmp_path))
    with pytest.raises(FrozenInstanceError):
        spec.agent_root = tmp_path  # type: ignore[misc]
    with pytest.raises(TypeError):
        spec.declarations["url"] = "https://other"  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.declarations["resident_profiles"][0]["environment"]["TOKEN"] = "new"  # type: ignore[index]
    with pytest.raises(TypeError):
        spec._payload["registration"]["pools"][0] = "other"  # type: ignore[index]


def test_normalized_defaults_numbers_and_paths_have_one_declaration_digest(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resources"] = {
        "cpu_capacity": 1,
        "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": "none"},
    }
    _write_protected(source, payload)
    first = read_agent_spec(source)
    payload["max_concurrent_assignments"] = 1
    payload["slurm_profiles"] = []
    payload["provider_factory"] = None
    payload["reconnect_seconds"] = "0.10"
    payload["agent_root"] = str(tmp_path / "remote-agent")
    payload["resources"]["cpu_capacity"] = "01"
    payload["resources"]["memory_capacity_bytes"] = "00"
    payload["resources"]["gpu"]["occupancy"] = {}
    profile = payload["resident_profiles"][0]
    profile["cpu_capacity"] = "01"
    profile["memory_capacity_bytes"] = "00"
    profile["project_root"] = "."
    profile["descriptor"] = {"profile_id": "remote-profile", "revision": "v1"}
    profile["readiness"] = {
        "imports": ["loom"],
        "distributions": ["LOOM"],
        "source_roots": [],
        "lockfile": str(tmp_path / "uv.lock"),
        "timeout_seconds": "5",
    }
    profile["container"] = None
    profile["shared_roots"] = {}
    profile["preparation_shared_roots"] = {}
    equivalent = read_agent_spec(_write_protected(source, payload))
    assert equivalent.declaration_digest == first.declaration_digest
    assert equivalent.declarations == first.declarations


def test_declaration_digest_binds_relative_path_context_and_executable_entry(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    first = read_agent_spec(source)
    payload = json.loads(source.read_text())
    other = tmp_path / "other"
    other.mkdir()
    moved = read_agent_spec(_write_protected(other / "agent.yaml", payload))
    assert moved.declaration_digest != first.declaration_digest
    for name in (
        "agent_root",
        "server_ca_path",
        "certificate_path",
        "private_key_path",
    ):
        payload[name] = str(tmp_path / payload[name])
    equivalent = read_agent_spec(_write_protected(other / "agent.yaml", payload))
    assert equivalent.declaration_digest == first.declaration_digest
    executable = Path(payload["resident_profiles"][0]["python_executable"])
    link = tmp_path / "venv-python"
    link.symlink_to(executable)
    payload["resident_profiles"][0]["python_executable"] = str(link)
    selected = read_agent_spec(_write_protected(other / "agent.yaml", payload))
    profiles = cast(tuple[Mapping[str, Any], ...], selected.declarations["resident_profiles"])
    assert profiles[0]["python_executable"] == str(link)
    assert selected.declaration_digest != first.declaration_digest


@pytest.mark.optional_dependency
def test_explicit_environment_values_are_snapshotted_and_source_names_are_provenance(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["agent_root"] = "${oc.env:AGENT_ROOT}"
    _write_protected(source, payload)
    environment = _write_protected_text(
        tmp_path / "agent.env", "AGENT_ROOT=remote-agent\n"
    )
    first = read_agent_spec(source, env_file=environment)
    other = _write_protected_text(tmp_path / "other.env", "AGENT_ROOT=remote-agent\n")
    equivalent = read_agent_spec(source, env_file=other)
    assert first.environment_path == environment
    assert equivalent.environment_path == other
    assert first.declaration_digest == equivalent.declaration_digest
    other.write_text("AGENT_ROOT=replacement-agent\n")
    assert (
        read_agent_spec(source, env_file=other).declaration_digest
        != first.declaration_digest
    )


@pytest.mark.parametrize(
    "reader", [read_agent_spec, load_outbound_agent_service_config]
)
@pytest.mark.parametrize(
    "invalid",
    [
        "mode",
        "schema",
        "capacity",
        "profile",
        "include",
        "capacity_domain",
        pytest.param("environment", marks=pytest.mark.optional_dependency),
    ],
)
def test_protected_inputs_and_declared_schema_are_enforced(
    tmp_path: Path,
    reader: Any,
    invalid: str,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    kwargs = {}
    if invalid == "mode":
        source.chmod(0o644)
    elif invalid == "environment":
        kwargs["env_file"] = _write_protected_text(
            tmp_path / "agent.env", "A=one\nA=two\n"
        )
    elif invalid == "include":
        included = _write_protected(tmp_path / "base.yaml", payload["registration"])
        included.chmod(0o666)
        payload["registration"] = {"_include_": "base.yaml"}
        _write_protected(source, payload)
    else:
        if invalid == "schema":
            payload["schema_version"] = 999
        elif invalid == "capacity":
            payload["resident_profiles"][0]["cpu_capacity"] = True
        elif invalid == "capacity_domain":
            other = dict(payload["resident_profiles"][0])
            other["descriptor"] = {"profile_id": "other", "revision": "v1"}
            other["cpu_capacity"] = 2
            payload["resident_profiles"].append(other)
        else:
            payload["resident_profiles"][0]["unknown"] = True
        _write_protected(source, payload)
    match = "source must be owner-protected" if invalid == "include" else None
    with pytest.raises(QueueConfigError, match=match):
        reader(source, **kwargs)


def test_qualification_preserves_published_fingerprints_and_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _agent_config(tmp_path)
    spec = read_agent_spec(source)
    deadlines = []

    def observe(profile: Any, *, _deadline: float | None = None) -> Any:
        deadlines.append(_deadline)
        return _observe(profile)

    monkeypatch.setattr(deployment, "qualified_resident_profile", observe)
    service = load_outbound_agent_service_config(source, _deadline=123.0)
    # Captured from the baseline loader at 3d7e53c8 with these observed facts.
    assert (
        service.immutable_fingerprint
        == "1a1e7ee584419dea516e3cd03cae3c19cdc43ce9f41841a5138ab61abb3becd4"
    )
    assert (
        service.active_fingerprint
        == "3d89a575c5dc2ce3ab1f5930928a443d59a88186c64d898c1e22d380663eff24"
    )
    assert service.client.declaration_digest == spec.declaration_digest
    payload = json.loads(source.read_text())
    payload["registration"]["config_revision"] = "new-revision"
    _write_protected(source, payload)
    qualified = qualify_agent_spec(spec, _deadline=456.0)
    assert qualified == service
    assert deadlines == [123.0, 456.0]
    assert (
        AgentTlsClientConfig(
            "https://localhost",
            tmp_path / "ca",
            tmp_path / "cert",
            tmp_path / "key",
        ).declaration_digest
        is None
    )


def test_full_loader_still_rejects_missing_execution_files(tmp_path: Path) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resident_profiles"][0]["python_executable"] = "missing-python"
    _write_protected(source, payload)
    read_agent_spec(source)
    with pytest.raises(QueueServiceError, match="Python executable is unavailable"):
        load_outbound_agent_service_config(source)


def test_full_loader_still_qualifies_imports_and_honors_allow_unready(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resident_profiles"][0]["readiness"] = {
        "imports": ["loom_missing_package_for_test"]
    }
    _write_protected(source, payload)
    read_agent_spec(source)
    with pytest.raises(QueueConfigError, match="readiness failed"):
        load_outbound_agent_service_config(source)
    service = load_outbound_agent_service_config(source, _allow_unready=True)
    result = service.client.resident_profiles[0].readiness_result
    assert result is not None and not result.ok


def test_readiness_path_context_preserves_worker_parent_traversal(tmp_path: Path) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resident_profiles"][0]["readiness"] = {"source_roots": ["link/../source"]}
    spec = read_agent_spec(_write_protected(source, payload))
    payload["resident_profiles"][0]["readiness"] = {"source_roots": ["source"]}
    direct = read_agent_spec(_write_protected(source, payload))
    # A worker/container symlink named link can make these different sources.
    assert spec.declaration_digest != direct.declaration_digest


def test_trusted_composition_binds_its_invocation_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["provider_factory"] = {"_target_": "uninstalled.module.factory"}
    _write_protected(source, payload)
    monkeypatch.chdir(tmp_path)
    spec = read_agent_spec(source)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert read_agent_spec(source).declaration_digest != spec.declaration_digest
    monkeypatch.setattr(deployment, "qualified_resident_profile", _forbid)
    with pytest.raises(QueueConfigError, match="composition directory changed"):
        qualify_agent_spec(spec)
