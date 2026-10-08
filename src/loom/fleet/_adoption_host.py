"""Quiesced installation handover; native locks own replacement and migration."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, cast

from loom.fleet import _host, _upgrade_host
from loom.queue.errors import QueueConflictError
from loom.queue.service_upgrade import inspect_adoption_service


def owner(request) -> dict[str, Any]:
    observed = inspect_adoption_service(
        _host.native_root(request), expected_root_id=request["expected_root_id"]
    )
    if observed.availability != "available" or (
        observed.value.get("ownership") != "live"
        and observed.reason != "service_stopped"
    ):
        raise QueueConflictError(
            "adoption ownership unavailable: " + str(observed.reason)
        )
    return cast(dict[str, Any], observed.to_dict())


def _binding(request):
    admin = Path(request["admin"])
    active = admin / "active.json"
    service = admin / "service.json"
    if active.exists() and _host.read(active) != request["release"]:
        raise QueueConflictError(
            "managed installation already exists; use Fleet upgrade"
        )
    if service.exists():
        retained = _host.read(service)
        if retained.get("adoption_id") != request["adoption_id"]:
            raise QueueConflictError("another operation owns the service binding")
        if retained.get("expected_root_id") != request["expected_root_id"]:
            raise QueueConflictError("adoption service identity changed")
    elif active.exists():
        raise QueueConflictError("managed installation lacks adoption binding")


def inspect(request):
    if request.get("service_manager", "tmux") != "tmux":
        raise QueueConflictError("installation adoption retains tmux")
    _binding(request)
    observed = owner(request)
    python = Path(request["previous_python"])
    if not python.is_absolute() or not python.is_file():
        raise QueueConflictError("retained predecessor interpreter is unavailable")
    process_python = None
    if observed["value"]["ownership"] == "live":
        pid = observed["value"]["expected_process"]
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        # A venv's /proc/PID/exe names its base Python, not the selected venv.
        # Preserve the exact interpreter spelling from the service's argv.
        allowed = {str(python).encode()}
        if (Path(request["admin"]) / "service.json").exists():
            allowed.add(sys.executable.encode())
        if not argv or argv[0] not in allowed:
            raise QueueConflictError(
                "live service interpreter differs from adoption input"
            )
        process_python = argv[0].decode()
    facts = _upgrade_host.inspect(request, native_owner=observed)
    facts["process_python"] = process_python
    expected_session = request.get("expected_session_id")
    if (
        expected_session is not None
        and observed["value"].get("session_id") != expected_session
    ):
        raise QueueConflictError("adoption native session changed")
    return facts


def replace(request, directory):
    """Migrate a proven stopped root and publish only the verified new binding."""
    from loom.queue.deployment import (
        load_coordinator_service_config,
        load_outbound_agent_service_config,
        service_backend_migration_guard,
    )

    facts = inspect(request)
    admin = Path(request["admin"])
    binding = admin / "service.json"
    if facts["native_owner"]["value"]["ownership"] == "live":
        if binding.exists() and _host.read(binding) == request:
            # The start succeeded before the SSH reply or host receipt was lost.
            # inspect() proved the selected native owner and candidate interpreter.
            if _host.read(admin / "active.json") != request["release"]:
                raise QueueConflictError("live adopted service lacks matching release")
            if facts["process_python"] != sys.executable:
                raise QueueConflictError(
                    "another interpreter restarted the adopted service"
                )
            return {"outcome": "unchanged", "release": request["release"], **facts}
        raise QueueConflictError("native service must stop before adoption replacement")
    _upgrade_host._settled(request)
    previous = directory / "predecessor.json"
    if not previous.exists():
        _host.atomic(
            previous,
            {
                "native_owner": facts["native_owner"],
                "python": request["previous_python"],
                "compatibility": facts["compatibility"],
            },
        )
    if _host.role(request) == "coordinator":
        _host.run_native(request, "daemon-upgrade")
    loader = (
        load_coordinator_service_config
        if _host.role(request) == "coordinator"
        else load_outbound_agent_service_config
    )
    service = loader(_host.config(request), env_file=_host.environment(request))
    with service_backend_migration_guard(service, request["expected_root_id"]):
        _binding(request)
        if binding.exists() and _host.read(binding) != request:
            raise QueueConflictError("adoption binding changed during replacement")
        _host.atomic(binding, request)
        _host.atomic(admin / "active.json", request["release"])
    started = _host.start(request)
    return {"outcome": "applied", "release": request["release"], **started}


def execute(request, directory):
    action = request["action"]
    if action == "adopt-probe":
        return inspect(request)
    if action == "adopt-stop":
        inspect(request)
        return _upgrade_host.stop_owned(request, observe=owner)
    if action == "adopt-replace":
        return replace(request, directory)
    raise QueueConflictError("unsupported fixed adoption step")
