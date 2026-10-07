"""Fixed workload candidate qualification and authored configuration publication.

Executable protected bindings remain exclusively owned by native promotion;
this adapter only publishes trusted role source for that accepted control.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, cast

from loom.fleet._host import atomic, config, environment, payload, read, role, owner
from loom.queue.errors import QueueConflictError
from loom.queue.deployment import load_outbound_agent_service_config
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


def qualify(request, declaration):
    """Qualify using the native protected loader in the existing path frame."""
    descriptor, temporary = tempfile.mkstemp(dir=config(request).parent, suffix=".json")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(declaration, stream)
        service = load_outbound_agent_service_config(
            temporary, env_file=environment(request)
        )
        return {
            "immutable": service.immutable_fingerprint,
            "active": service.active_fingerprint,
            "profile": service.client.resident_profiles[0].descriptor.to_dict(),
        }
    finally:
        Path(temporary).unlink(missing_ok=True)


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
    after = json.loads(json.dumps(authored))
    after["resident_profiles"][0]["container"]["container"]["image"] = {
        "reference": request["image"]
    }
    after["resident_profiles"][0]["descriptor"] = {
        "profile_id": request["workload_profile"],
        "revision": "image-" + sha[:24],
    }
    return {
        "source": qualify(request, authored),
        "target": qualify(request, after),
        "image_sha256": sha,
        "declaration": after,
        "native_owner": owner(request),
    }


def publish(request, directory):
    """Retain before/after source and reload only through native control owners."""
    current = payload(request)
    target = request["declaration"]
    retained = directory / "reload.json"
    if retained.exists():
        intent = read(retained)
        if intent["after"] != target:
            raise QueueConflictError("workload publication target changed")
    else:
        if role(request) == "agent":
            _image(request["image"], request["image_sha256"])
            if qualify(request, target) != request["target"]:
                raise QueueConflictError("workload target qualification changed")
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


def execute(request, directory):
    if request["action"] == "workload-probe":
        return probe(request)
    if request["action"] == "workload-supervisor":
        if request.get("service_manager") == "systemd-user":
            from loom.fleet._services import systemctl, unit_name

            systemctl("start", unit_name(request, "supervisor"))
        return {"outcome": "applied"}
    if request["action"] == "workload-publish":
        return publish(request, directory)
    raise QueueConflictError("unsupported fixed workload host action")
