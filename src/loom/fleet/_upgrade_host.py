"""Fixed candidate-runtime host steps; native owners establish settlement."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import select
import signal
import sys

from loom.fleet._host import (
    atomic,
    config,
    environment,
    native_root,
    owner,
    payload,
    read,
    role,
    run_native,
)
from loom.queue.errors import QueueConflictError
from loom.queue.operations import probe_upgrade_compatibility
from loom.queue.service_upgrade import inspect_service_settlement


def inspect(request):
    """Recheck candidate storage, profile/image bytes and native root identity."""
    from loom.fleet.releases import verify_release

    bundle = (
        Path(request["admin"])
        / "releases"
        / request["release"]["descriptor_sha256"]
        / "bundle"
    )
    if verify_release(bundle / request["descriptor_name"]) != request["release"]:
        raise QueueConflictError("candidate bundle bytes changed")
    observed = owner(request)
    if observed["owner"] != request["expected_root_id"]:
        raise QueueConflictError("upgrade native root identity changed")
    compatibility = probe_upgrade_compatibility(
        native_root(request),
        required_capabilities=tuple(request["required_capabilities"]),
    )
    facts = compatibility.to_dict()
    if (
        compatibility.availability != "available"
        or not compatibility.value["compatible"]
    ):
        raise QueueConflictError(
            "candidate compatibility unavailable: " + str(compatibility.reason)
        )
    if role(request) == "coordinator":
        current = compatibility.value["current_storage_version"]
        if current != compatibility.value["target_storage_version"] and current != 18:
            raise QueueConflictError(
                "unsupported direct Fleet migration; use the native intermediate upgrade"
            )
    images = {}
    if role(request) == "agent":
        # The candidate native checker owns supervisor/profile compatibility.
        run_native(request, "agent-check")
        for profile in payload(request)["resident_profiles"]:
            container = profile.get("container")
            if container is not None:
                image = Path(container["container"]["image"]["reference"])
                with image.open("rb") as stream:
                    images[str(image)] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
    if request.get("images") is not None and images != request["images"]:
        raise QueueConflictError("immutable workload image changed")
    return {
        "native_owner": observed,
        "compatibility": facts,
        "images": images,
        "python": sys.executable,
    }


def _settled(request):
    observation = inspect_service_settlement(
        native_root(request), expected_root_id=request["expected_root_id"]
    )
    if observation.availability != "available" or not observation.value.get("settled"):
        raise QueueConflictError(
            "native service settlement required: " + str(observation.to_dict())
        )
    return observation.to_dict()


def stop(request):
    """Stop only the positively identified communication process after settlement."""
    inspect(request)
    proof = _settled(request)
    observed = owner(request)
    if observed["owner"] != request["expected_root_id"]:
        raise QueueConflictError("upgrade root identity changed")
    if observed["value"]["ownership"] == "live":
        descriptor = os.pidfd_open(observed["value"]["expected_process"])
        try:
            current = owner(request)
            if (
                current["owner"] != observed["owner"]
                or current["revision"] != observed["revision"]
            ):
                raise QueueConflictError("service process changed before stop")
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            poll = select.poll()
            poll.register(descriptor, select.POLLIN)
            if not poll.poll(30000):
                raise QueueConflictError("native stop still pending; no escalation")
        finally:
            os.close(descriptor)
    elif observed["reason"] != "service_stopped":
        raise QueueConflictError("native stop ownership is uncertain")
    return {"outcome": "stopped", "settlement": proof, "native_owner": owner(request)}


def replace(request):
    """Migrate offline, preserve old units, then bind the exact candidate runtime."""
    from loom.queue.deployment import (
        load_coordinator_service_config,
        load_outbound_agent_service_config,
        service_backend_migration_guard,
    )
    from loom.fleet._services import unit_name, render, systemctl
    from loom.fleet._host import start, keep

    admin = Path(request["admin"])
    previous = read(admin / "active.json")
    if previous not in (request["source_release"], request["release"]):
        raise QueueConflictError("another runtime owns the service binding")
    if (
        previous == request["release"]
        and owner(request)["value"]["ownership"] == "live"
    ):
        return {
            "outcome": "unchanged",
            "native_owner": owner(request),
            "release": previous,
        }
    if owner(request)["value"]["ownership"] == "live":
        raise QueueConflictError("service must stop before replacement")
    inspect(request)
    _settled(request)
    if role(request) == "coordinator":
        run_native(request, "daemon-upgrade")
    loader = (
        load_coordinator_service_config
        if role(request) == "coordinator"
        else load_outbound_agent_service_config
    )
    service = loader(config(request), env_file=environment(request))
    with service_backend_migration_guard(service, request["expected_root_id"]):
        binding = admin / "service.json"
        archive = (
            admin
            / "releases"
            / request["source_release"]["descriptor_sha256"]
            / "service-binding.json"
        )
        if archive.exists():
            if read(binding) not in (read(archive), request):
                raise QueueConflictError("service binding changed during replacement")
        elif binding.exists():
            keep(archive, binding.read_bytes())
        atomic(binding, request)
        if request.get("service_manager", "tmux") == "systemd-user":
            kinds = (
                ["supervisor", "agent"] if role(request) == "agent" else ["coordinator"]
            )
            for kind in kinds:
                path = admin / "units" / unit_name(request, kind)
                previous_unit = archive.parent / path.name
                rendered = render(request, kind).encode()
                if previous_unit.exists():
                    if path.read_bytes() not in (previous_unit.read_bytes(), rendered):
                        raise QueueConflictError(
                            "service unit changed during replacement"
                        )
                elif path.exists():
                    keep(previous_unit, path.read_bytes())
                # Atomic unit publication; existing symlink still names this file.
                from loom.fleet._host import tempfile

                descriptor, temporary = tempfile.mkstemp(dir=path.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(rendered)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            systemctl("daemon-reload")
        atomic(admin / "active.json", request["release"])
    started = start(request)
    return {"outcome": "applied", "release": request["release"], **started}


def execute(request):
    action = request["action"]
    if action == "upgrade-probe":
        return inspect(request)
    if action == "upgrade-settlement":
        return inspect_service_settlement(
            native_root(request),
            expected_root_id=request["expected_root_id"],
            include_pending_poll=request.get("include_pending_poll", True),
        ).to_dict()
    if action == "upgrade-stop":
        return stop(request)
    if action == "upgrade-replace":
        return replace(request)
    raise QueueConflictError("unsupported fixed upgrade step")
