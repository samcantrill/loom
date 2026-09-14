"""Protected coordinator and agent role preflight diagnostics."""

from __future__ import annotations
from collections.abc import Mapping
from loom.serialization import PlainData
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.diagnostics.models import PreflightResult, PreflightCheckResult


def run_role_preflight(
    config_path: str | Path,
    *,
    role: str,
    env_file: str | Path | None = None,
    probe_io: bool = False,
    probe_gpu: bool = False,
) -> "PreflightResult":
    """Inspect one role and aggregate its applicable installation findings.

    Default inspection creates no deployment/run/claim state. Explicit IO probes
    touch only private temporary members beneath named, existing execution roots.
    Explicit GPU probes require initialized idle ownership and persist diagnostic
    claims until process containment and provider release are established.
    Connection and scientific checks remain with their actual owning operations.
    """
    import os
    import sys
    from dataclasses import replace

    from loom.diagnostics.models import (
        PreflightCheckStatus as Status,
        PreflightGroup as Group,
        PreflightResult,
    )
    from .deployment import (
        load_coordinator_service_config,
        load_outbound_agent_service_config,
    )
    from .errors import QueueError
    from .resident_readiness import readiness_check

    checks: list[PreflightCheckResult] = []

    def add(
        check_id: str,
        group: Group,
        status: Status,
        message: str,
        *,
        owner: str,
        repair: str,
        applicability: str = "required",
        evidence: Mapping[str, PlainData] | None = None,
    ) -> None:
        checks.append(
            readiness_check(
                check_id,
                group,
                status,
                message,
                owner=owner,
                consequence="Failed required checks withhold new work; retained ownership is unchanged.",
                repair=repair,
                applicability=applicability,
                evidence=evidence,
            )
        )

    try:
        if role == "coordinator":
            coordinator = load_coordinator_service_config(
                config_path, env_file=env_file, _allow_unready=True
            )
            gpu_configuration = coordinator
            agent = coordinator.local_agent
            profiles = () if agent is None else (agent.profile,)
            agent_root = None if agent is None else agent.agent_root
            assert coordinator.daemon.deployment_root is not None
            roots = (
                coordinator.daemon.deployment_root,
                coordinator.daemon.run_store_root,
            )
            capacity = coordinator.effective_capacity
        elif role == "agent":
            outbound = load_outbound_agent_service_config(
                config_path, env_file=env_file, _allow_unready=True
            )
            gpu_configuration = outbound
            profiles = outbound.client.resident_profiles
            agent_root = outbound.client.agent_root
            roots = () if agent_root is None else (agent_root,)
            capacity = outbound.effective_capacity
        else:
            raise ValueError("unknown managed role")
    except QueueError:
        add(
            "configuration.inputs",
            Group.CONFIG,
            Status.FAIL,
            "Protected role configuration or required bindings are unavailable.",
            owner="role loader",
            repair="Repair the explicit role files, required values, schema and path bindings.",
        )
        for name, group in (
            ("service.connection", Group.SERVICE),
            ("python.interpreter", Group.PYTHON),
            ("packages.required_imports", Group.PACKAGES),
            ("environment.worker", Group.ENVIRONMENT),
            ("resources.capacity", Group.RESOURCES),
            ("filesystem.role_roots", Group.FILESYSTEM),
            ("execution.identity", Group.IDENTITY),
        ):
            add(
                name,
                group,
                Status.SKIP,
                "This check requires a valid resolved role.",
                owner="role loader",
                repair="Repair configuration.inputs first.",
                applicability="blocked by configuration.inputs",
            )
        return PreflightResult(
            tuple(checks), tuple(dict.fromkeys(item.group for item in checks))
        )

    add(
        "configuration.inputs",
        Group.CONFIG,
        Status.PASS,
        "Explicit protected role inputs resolved and normalized.",
        owner="role loader",
        repair="Keep the configured files protected and use explicit reload for changed values.",
    )
    add(
        "service.connection",
        Group.SERVICE,
        Status.SKIP,
        "Live identity, authentication and connection checks run at startup/reconnect.",
        owner="coordinator/agent protocol",
        repair="Start the configured roles and inspect their connection findings.",
        applicability="startup/reconnect boundary; no connection created by this check",
    )
    if role == "coordinator":
        add(
            "python.service",
            Group.PYTHON,
            Status.PASS if sys.version_info >= (3, 12) else Status.FAIL,
            "Coordinator service interpreter observed.",
            owner="coordinator service",
            repair="Run Loom with supported Python.",
            evidence={"version": list(sys.version_info[:3])},
        )
    for profile in profiles:
        result = profile.readiness_result
        if result is None:
            add(
                "execution.identity",
                Group.IDENTITY,
                Status.FAIL,
                "Resident qualification evidence is unavailable.",
                owner="resident profile",
                repair="Qualify the selected installation before offering work.",
            )
            continue
        for check in result.checks:
            checks.append(
                replace(
                    check,
                    details={
                        **dict(check.details),
                        "profile_id": profile.descriptor.profile_id,
                    },
                )
            )
    if not profiles:
        for name, group in (
            ("packages.required_imports", Group.PACKAGES),
            ("environment.worker", Group.ENVIRONMENT),
            ("execution.identity", Group.IDENTITY),
        ):
            add(
                name,
                group,
                Status.SKIP,
                "This coordinator has no local worker profile.",
                owner="coordinator role",
                repair="Configure agents when execution capacity is required.",
                applicability="coordinator only",
            )
    add(
        "resources.capacity",
        Group.RESOURCES,
        (Status.PASS if capacity is not None else Status.WARN)
        if profiles
        else Status.SKIP,
        (
            "Agent resource selection was checked against available supported limits."
            if capacity is not None
            else "Legacy profile capacity is declared; host limits and GPU selection were not discovered."
        )
        if profiles
        else "A pure coordinator needs no execution resources.",
        owner="agent resource providers",
        repair="Select valid agent capacity; current claims are distinct from declared capacity.",
        applicability="agent resources" if profiles else "coordinator only",
        evidence={
            "effective_capacity": None if capacity is None else capacity.to_dict()
        },
    )
    roots_ok = True
    for root in roots:
        path = Path(root)
        while not path.exists() and path != path.parent:
            path = path.parent
        roots_ok = (
            roots_ok and path.is_dir() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
        )
    add(
        "filesystem.role_roots",
        Group.FILESYSTEM,
        Status.PASS if roots_ok else Status.FAIL,
        "Execution roots or their existing parents are accessible."
        if roots_ok
        else "An execution root or parent is unavailable.",
        owner="role/workspace stores",
        repair="Create accessible execution roots on storage supported by the selected store; access inspection is not write proof.",
        evidence={"write_probe_requested": probe_io},
    )
    if probe_io:
        for index, root in enumerate(roots):
            checks.append(_role_io_probe(Path(root), index))
    else:
        add(
            "filesystem.io",
            Group.FILESYSTEM,
            Status.SKIP,
            "Active IO probe was not requested.",
            owner="role/workspace stores",
            repair="Use --probe-io for tiny writes in existing execution-owned roots.",
            applicability="unrequested active probe",
        )
    add(
        "scientific.inputs",
        Group.PIPELINE,
        Status.SKIP,
        "Scientific inputs, run contracts and artifact compatibility are checked by the project at check/prepare.",
        owner="project preparation",
        repair="Run the project check with its selected data, cache and run configuration.",
        applicability="project check/prepare boundary",
    )
    if agent_root is not None and Path(agent_root).exists():
        from ._agent_process_supervisor import (
            AgentProcessSupervisorError,
            SupervisorLaunchConfiguration,
            _service_configuration,
        )

        try:
            retained = _service_configuration(Path(agent_root) / "supervisor")
            current = SupervisorLaunchConfiguration(
                retained.agent_id, tuple(profile.launch_profile for profile in profiles)
            )
            matches = retained.fingerprint == current.fingerprint
        except (AgentProcessSupervisorError, OSError):
            matches = False
        add(
            "execution.retained_binding",
            Group.IDENTITY,
            Status.PASS if matches else Status.FAIL,
            "Observed profile bindings match initialized ownership."
            if matches
            else "Observed installation or private binding differs from initialized ownership.",
            owner="resident supervisor",
            repair="Preserve retained work; settle it before deliberately qualifying a new profile/deployment.",
        )
    if probe_gpu and not any(check.status is Status.FAIL for check in checks):
        from ._gpu_probe import run_role_gpu_probes

        checks.extend(run_role_gpu_probes(gpu_configuration))
    else:
        add(
            "resources.gpu_compute",
            Group.RESOURCES,
            Status.SKIP,
            "GPU enumeration does not establish compute qualification.",
            owner="agent GPU provider",
            repair="Repair failed checks, then use --probe-gpu after init and before serve.",
            applicability="blocked by failed readiness"
            if probe_gpu
            else "unrequested active probe",
        )
    return PreflightResult(
        tuple(checks), tuple(dict.fromkeys(item.group for item in checks))
    )


def _role_io_probe(root: Path, index: int) -> "PreflightCheckResult":
    import tempfile

    from loom.diagnostics.models import (
        PreflightCheckStatus as Status,
        PreflightGroup as Group,
    )
    from .resident_readiness import readiness_check

    passed = False
    try:
        if root.is_dir():
            with tempfile.TemporaryDirectory(
                prefix=".loom-io-probe-", dir=root
            ) as directory:
                source = Path(directory) / "write"
                renamed = Path(directory) / "renamed"
                source.write_bytes(b"loom-io-probe\n")
                if source.read_bytes() != b"loom-io-probe\n":
                    raise OSError("probe read did not match")
                source.replace(renamed)
                if renamed.read_bytes() != b"loom-io-probe\n":
                    raise OSError("probe rename did not preserve contents")
                renamed.unlink()
            passed = True
    except OSError:
        pass
    return readiness_check(
        "filesystem.io",
        Group.FILESYSTEM,
        Status.PASS if passed else Status.FAIL,
        "Tiny execution-root IO probe and cleanup passed."
        if passed
        else "Execution-root IO probe could not complete and clean up.",
        owner="role/workspace stores",
        consequence="Failure withholds the requested filesystem qualification.",
        repair="Use an existing writable execution-owned root; resolve storage/access/cleanup failures.",
        applicability="explicit active probe",
        evidence={"root_index": index},
    )


__all__ = ["run_role_preflight"]
