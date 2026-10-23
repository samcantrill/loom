"""Fixed candidate-runtime host steps; native owners establish settlement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sys
import time
from typing import Any, cast

from loom.fleet._host import (
    atomic,
    config,
    environment,
    native_root,
    owner,
    read,
    role,
)
from loom.queue.errors import QueueConflictError, QueueError
from loom.queue.operations import probe_upgrade_compatibility
from loom.queue.service_upgrade import inspect_service_settlement
from loom.fleet._timing import measure, timed


@timed("candidate_qualification")
def _inspect(request, *, native_owner=None):
    """Keep qualification local to this candidate-host activation boundary."""
    from loom.fleet.releases import verify_release

    bundle = (
        Path(request["admin"])
        / "releases"
        / request["release"]["descriptor_sha256"]
        / "bundle"
    )
    if verify_release(bundle / request["descriptor_name"]) != request["release"]:
        raise QueueConflictError("candidate bundle bytes changed")
    observed = owner(request) if native_owner is None else native_owner
    if observed["owner"] != request["expected_root_id"]:
        raise QueueConflictError("upgrade native root identity changed")
    compatibility = probe_upgrade_compatibility(
        native_root(request),
        required_capabilities=tuple(request["required_capabilities"]) + (
            ("quiescent-configuration-retirement-v1", "quiescent-coordinator-retirement-v1")
            if request.get("retirement_declaration") is not None else ()
        ),
    )
    facts = compatibility.to_dict()
    if (
        compatibility.availability != "available"
        or not compatibility.value["compatible"]
    ):
        raise QueueConflictError(
            "candidate compatibility unavailable: " + str(compatibility.reason)
        )
    images = {}
    service = None
    retirement = None
    predecessor = None
    if request.get("retirement_declaration") is not None:
        from loom.fleet._workload_host import probe, coordinator_probe

        candidate = {**request, "retire_configuration": True}
        if role(request) == "agent":
            candidate["candidate_declaration"] = request["retirement_declaration"]
            qualified = probe(candidate)
            retirement, predecessor = qualified["target"], qualified["source"]
        else:
            candidate["declaration"] = request["retirement_declaration"]
            retirement = coordinator_probe(candidate)
        if request.get("retirement_target") is not None and retirement != request["retirement_target"]:
            raise QueueConflictError("runtime retirement candidate qualification changed")
    elif role(request) == "agent":
        from loom.diagnostics.models import PreflightStatus
        from loom.queue.deployment import load_outbound_agent_service_config
        from loom.queue.preflight import check_loaded_agent

        try:
            service = load_outbound_agent_service_config(
                config(request), env_file=environment(request),
                _allow_unready=True, _deadline=time.monotonic() + 180,
            )
        except (QueueError, TimeoutError):
            service = None
        report = check_loaded_agent(service)
        failed = report.status is PreflightStatus.FAIL
        atomic(Path(request["admin"]) / "last-native.json", {
            "command": "agent-check", "returncode": int(failed),
            "stdout": json.dumps({"operation": "agent-check", **report.to_dict()}),
            "stderr": "",
        })
        if failed:
            raise QueueConflictError("native role command failed; inspect protected host evidence")
        assert service is not None
        for profile in service.client.resident_profiles:
            container = profile.container
            if container is not None:
                selected_container = cast(dict[str, Any], container["container"])
                image = Path(selected_container["image"]["reference"])
                qualified = profile.readiness_result
                sha = None if qualified is None else qualified.image_sha256
                if sha is None:
                    with measure("image_hash"), image.open("rb") as stream:
                        sha = hashlib.file_digest(stream, "sha256").hexdigest()
                images[str(image)] = sha
    if request.get("images") is not None and images != request["images"]:
        raise QueueConflictError("immutable workload image changed")
    return {
        "native_owner": observed,
        "compatibility": facts,
        "images": images,
        "python": sys.executable,
        **({"retirement_target": retirement} if retirement is not None else {}),
        **({"retirement_source": predecessor} if predecessor is not None else {}),
    }, service


def inspect(request, *, native_owner=None):
    """Recheck candidate storage, profile/image bytes and native root identity."""
    facts, _ = _inspect(request, native_owner=native_owner)
    return facts


def _settled(request):
    if request.get("recovery_results") is not None:
        from loom.queue.service_upgrade import require_result_recovery
        return require_result_recovery(
            native_root(request), expected_root_id=request["expected_root_id"],
            role=role(request), agent_results=request["recovery_results"],
        ).to_dict()
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
    return stop_owned(request, observe=owner)


def stop_owned(request, *, observe):
    """Recheck the native owner around pidfd acquisition; never escalate a stop."""
    proof = _settled(request)
    observed = observe(request)
    if observed["owner"] != request["expected_root_id"]:
        raise QueueConflictError("upgrade root identity changed")
    if observed["value"]["ownership"] == "live":
        descriptor = os.pidfd_open(observed["value"]["expected_process"])
        try:
            current = observe(request)
            if (
                current["owner"] != observed["owner"]
                or current["revision"] != observed["revision"]
                or current["availability"] != "available"
                or current["value"].get("ownership") != "live"
                or current["value"].get("expected_process")
                != observed["value"]["expected_process"]
            ):
                raise QueueConflictError("service process changed before stop")
            with measure("signal_to_exit"):
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                poll = select.poll()
                poll.register(descriptor, select.POLLIN)
                if not poll.poll(30000):
                    raise QueueConflictError("native stop still pending; no escalation")
        finally:
            os.close(descriptor)
    elif observed["reason"] != "service_stopped":
        raise QueueConflictError("native stop ownership is uncertain")
    return {"outcome": "stopped", "settlement": proof, "native_owner": observe(request)}


def replace(request):
    """Preserve stopped current units, then bind the exact candidate runtime."""
    from loom.queue.deployment import (
        load_coordinator_service_config,
        service_replacement_guard,
    )
    from loom.fleet._services import unit_name, render, systemctl
    from loom.fleet._host import start, keep

    if request.get("retirement_declaration") is not None:
        raise QueueConflictError("runtime replacement requires native retirement publication first")
    admin = Path(request["admin"])
    previous = read(admin / "active.json")
    if previous not in (request["source_release"], request["release"]):
        raise QueueConflictError("another runtime owns the service binding")
    if previous == request["release"]:
        if read(admin / "service.json") != request:
            raise QueueConflictError("service binding changed during replacement")
        started = start(request)
        return {
            "outcome": "unchanged",
            "release": previous,
            **started,
        }
    if owner(request)["value"]["ownership"] == "live":
        raise QueueConflictError("service must stop before replacement")
    _, service = _inspect(request)
    _settled(request)
    if service is None:
        service = load_coordinator_service_config(config(request), env_file=environment(request))
    with service_replacement_guard(
        service, request["expected_root_id"],
        recovery_results=request.get("recovery_results"),
    ):
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
    if action == "upgrade-check-capture":
        from ._check_preflight import capture
        return capture(request)
    if action == "upgrade-check-prepare":
        from ._check_preflight import prepare
        return prepare(request)
    if action == "upgrade-probe":
        return inspect(request)
    if action == "upgrade-result-recovery":
        from loom.queue.service_upgrade import (
            inspect_agent_result_recovery, inspect_coordinator_result_recovery,
        )
        if role(request) == "agent":
            return inspect_agent_result_recovery(
                native_root(request), expected_root_id=request["expected_root_id"],
            ).to_dict()
        return inspect_coordinator_result_recovery(
            native_root(request), expected_root_id=request["expected_root_id"],
            agent_results=request["recovery_results"],
        ).to_dict()
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
