"""Fixed workload candidate qualification and authored configuration publication.

Executable protected bindings remain exclusively owned by native promotion;
this adapter only publishes trusted role source for that accepted control.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import select
from pathlib import Path
import tempfile
from typing import Any, cast

from loom.fleet._host import atomic, config, environment, payload, read, role, owner
from loom.queue.errors import QueueConflictError
from loom.queue.deployment import (
    load_coordinator_service_config,
    load_outbound_agent_service_config,
)
from loom.serialization import thaw_plain_data


def _image(path, expected):
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise QueueConflictError("workload image must be an existing absolute SIF")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise QueueConflictError("immutable workload image digest mismatch")
    return actual


@contextmanager
def _candidate_config(request, declaration):
    """Keep native relative paths and protection in the retained role frame."""
    descriptor, temporary = tempfile.mkstemp(dir=config(request).parent, suffix=".json")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(declaration, stream)
        yield temporary
    finally:
        Path(temporary).unlink(missing_ok=True)


def qualify(request, declaration, *, check_promotion=False):
    """Qualify using the native protected loader in the existing path frame."""
    with _candidate_config(request, declaration) as temporary:
        service = load_outbound_agent_service_config(
            temporary, env_file=environment(request)
        )
        if check_promotion:
            from loom.queue._profile_promotion import validate_candidate

            original = load_outbound_agent_service_config(
                config(request), env_file=environment(request)
            )
            validate_candidate(original.client, service.client, request["workload_profile"])
        return {
            "immutable": service.immutable_fingerprint,
            "active": service.active_fingerprint,
            "profile": service.client.resident_profiles[0].descriptor.to_dict(),
        }


def coordinator_probe(request):
    """Qualify the derived coordinator target on its owning host without reload."""
    if role(request) != "coordinator":
        raise QueueConflictError("coordinator candidate requires a coordinator")
    with _candidate_config(request, request["declaration"]) as temporary:
        service = load_coordinator_service_config(
            temporary, env_file=environment(request)
        )
        return {
            "immutable": service.immutable_fingerprint,
            "active": service.active_fingerprint,
        }


def probe(request):
    if role(request) != "agent":
        raise QueueConflictError("workload candidate requires an agent")
    authored = payload(request)
    profiles = authored["resident_profiles"]
    if (
        len(profiles) != 1
        or profiles[0]["descriptor"]["profile_id"] != request["workload_profile"]
    ):
        raise QueueConflictError(
            "workload candidate requires one selected resident profile"
        )
    if profiles[0].get("container", {}).get("kind") != "apptainer":
        raise QueueConflictError("workload upgrade requires an immutable SIF profile")
    sha = _image(request["image"], request["image_sha256"])
    after = json.loads(json.dumps(request.get("candidate_declaration", authored)))
    after["resident_profiles"][0]["container"]["container"]["image"] = {
        "reference": request["image"]
    }
    after["resident_profiles"][0]["descriptor"] = {
        "profile_id": request["workload_profile"],
        "revision": "image-" + sha[:24],
    }
    return {
        "source": qualify(request, authored),
        "target": qualify(request, after, check_promotion=True),
        "image_sha256": sha,
        "declaration": after,
        "native_owner": owner(request),
    }


def publish(request, directory):
    """Retain before/after source and reload only through native control owners."""
    if role(request) != "coordinator":
        raise QueueConflictError("native promotion owns agent source publication")
    current = payload(request)
    target = request["declaration"]
    retained = directory / "reload.json"
    if retained.exists():
        intent = read(retained)
        if intent["after"] != target:
            raise QueueConflictError("workload publication target changed")
    else:
        intent = {"before": current, "after": target}
        if role(request) == "coordinator":
            from loom.fleet._host import coordinator_client
            from loom.queue.local_daemon import CoordinatorSchedulingReload

            _, client = coordinator_client(request)
            intent["reload"] = CoordinatorSchedulingReload(
                request["request_id"],
                client.status().scheduling_epoch,
                "Fleet selected workload profile promotion",
            ).to_dict()
        atomic(retained, intent)
    if current not in (intent["before"], intent["after"]):
        raise QueueConflictError("workload role source changed during publication")
    if current != intent["after"]:
        atomic(config(request), intent["after"])
    result = {"outcome": "applied", "declaration": target}
    if role(request) == "coordinator":
        from loom.fleet._host import coordinator_client
        from loom.queue.local_daemon import CoordinatorSchedulingReload

        _, client = coordinator_client(request)
        result["reload"] = cast(
            dict[str, Any],
            thaw_plain_data(
                client.reload_scheduling(
                    CoordinatorSchedulingReload.from_dict(intent["reload"])
                )
            ),
        )
        if result["reload"]["state"] != "applied":
            raise QueueConflictError("native workload scheduling reload incomplete")
    return result


def recover_service(request):
    """Reconcile an accepted native transition and retained service ownership.

    This action is reobserved on each continuation: a previous start receipt
    cannot prove the current process survived. It never creates a service binding.
    """
    from loom.fleet._host import start
    from loom.queue._profile_promotion import recover, completed, publication_state

    fact = owner(request)
    if fact["owner"] != request["expected_root_id"]:
        raise QueueConflictError("workload native root identity changed")
    retained = read(Path(request["admin"]) / "service.json")
    if any(
        retained.get(key) != request.get(key) for key in ("root", "config", "release")
    ):
        raise QueueConflictError("workload retained service binding differs")
    if (
        fact["value"]["ownership"] == "live"
        and request.get("service_manager") == "systemd-user"
        and completed(Path(request["root"]), request["promotion_id"])
    ):
        from loom.fleet._services import systemctl, unit_name
        from loom.queue.service_upgrade import inspect_service_settlement

        supervisor_pid = systemctl(
            "show", unit_name(request, "supervisor"), "--property=MainPID", "--value"
        )
        if supervisor_pid == "0" and request.get("allow_communication_stop") is True:
            proof = inspect_service_settlement(
                Path(request["root"]), expected_root_id=request["expected_root_id"]
            )
            if proof.availability != "available" or not proof.value.get("settled"):
                raise QueueConflictError("native workload service settlement required")
            agent_unit = unit_name(request, "agent")
            pid = systemctl("show", agent_unit, "--property=MainPID", "--value")
            if pid != str(fact["value"]["expected_process"]):
                raise QueueConflictError(
                    "workload communication service ownership changed"
                )
            descriptor = os.pidfd_open(fact["value"]["expected_process"])
            try:
                current = owner(request)
                if (
                    current["owner"] != fact["owner"]
                    or current["revision"] != fact["revision"]
                    or current["value"]["ownership"] != "live"
                ):
                    raise QueueConflictError(
                        "workload communication service ownership changed"
                    )
                # The managed supervisor takes owner.lock during startup. Keep
                # systemd responsible for stopping its unit, but prove exact
                # process exit: SIGTERM need not publish a native stopped receipt.
                systemctl("stop", agent_unit)
                poll = select.poll()
                poll.register(descriptor, select.POLLIN)
                if not poll.poll(30000):
                    raise QueueConflictError("native stop still pending; no escalation")
                stopped = owner(request)
                if (
                    stopped["owner"] != fact["owner"]
                    or stopped["revision"] != fact["revision"]
                    or stopped["value"]["ownership"] == "live"
                ):
                    raise QueueConflictError(
                        "native communication stop remains unproven"
                    )
                fact = stopped
            finally:
                os.close(descriptor)
    if fact["value"]["ownership"] != "live":
        service = load_outbound_agent_service_config(
            config(request), env_file=environment(request)
        )
        recover(service.client)
        start(retained)
    return {
        "outcome": "applied",
        "declaration": payload(request),
        "publication_state": publication_state(
            Path(request["root"]), request["promotion_id"]
        ),
    }


def stage(request):
    _image(request["image"], request["image_sha256"])
    if qualify(request, request["declaration"]) != request["target"]:
        raise QueueConflictError("workload target qualification changed")
    from loom.fleet._host import keep

    candidate = config(request).with_name(
        ".workload-" + request["request_id"] + ".json"
    )
    keep(candidate, json.dumps(request["declaration"], sort_keys=True).encode())
    return {"outcome": "applied", "candidate_source": str(candidate)}


def execute(request, directory):
    if request["action"] == "workload-coordinator-probe":
        return coordinator_probe(request)
    if request["action"] == "workload-probe":
        return probe(request)
    if request["action"] == "workload-recover":
        return recover_service(request)
    if request["action"] == "workload-stage":
        return stage(request)
    if request["action"] == "workload-publish":
        return publish(request, directory)
    raise QueueConflictError("unsupported fixed workload host action")
