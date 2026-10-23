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
from loom.fleet._timing import timed


@timed("image_hash")
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


def _qualified(service):
    return {
        "immutable": service.immutable_fingerprint,
        "active": service.active_fingerprint,
        "profile": (service.client.resident_profiles[0].descriptor.to_dict()
                    if service.client.resident_profiles else None),
    }


@timed("candidate_qualification")
def qualify(request, declaration, *, check_promotion=False, original=None):
    """Qualify using the native protected loader in the existing path frame."""
    with _candidate_config(request, declaration) as temporary:
        service = load_outbound_agent_service_config(
            temporary, env_file=environment(request)
        )
        if check_promotion:
            from loom.queue._profile_promotion import validate_candidate

            if original is None:
                original = load_outbound_agent_service_config(
                    config(request), env_file=environment(request)
                )
            validate_candidate(original.client, service.client, request["workload_profile"])
        return _qualified(service)


def coordinator_probe(request):
    """Qualify the derived coordinator target on its owning host without reload."""
    if role(request) != "coordinator":
        raise QueueConflictError("coordinator candidate requires a coordinator")
    predecessor = None
    if request.get("retire_configuration"):
        predecessor = _coordinator_retirement_predecessor(request)
        from .workload_sources import _retirement_coordinator

        before, after = payload(request), request["declaration"]
        mutable = {"preparation", "shared_roots", "remote_profiles", "container_capabilities"}
        if {key: value for key, value in before.items() if key not in mutable} != {
            key: value for key, value in after.items() if key not in mutable
        }:
            raise QueueConflictError("coordinator retirement changed unrelated declaration")
        _retirement_coordinator(before, after)
    with _candidate_config(request, request["declaration"]) as temporary:
        service = load_coordinator_service_config(
            temporary, env_file=environment(request)
        )
        if predecessor is not None:
            from loom.queue.local_daemon import _validate_deployment_binding

            _validate_deployment_binding(service.daemon, coordinator_id=predecessor[0])
            if _coordinator_retirement_predecessor(request) != predecessor:
                raise QueueConflictError("coordinator predecessor changed during qualification")
        return {
            "immutable": service.immutable_fingerprint,
            "active": service.active_fingerprint,
        }


def _coordinator_retirement_predecessor(request):
    """Compare authored identity with accepted state without probing old roots."""
    from loom.fleet._host import native_root
    from loom.queue.deployment import read_coordinator_scheduling_fingerprint
    from loom.queue.operations import _readonly_root

    authored = read_coordinator_scheduling_fingerprint(config(request), env_file=environment(request))
    native = owner(request)
    if native["owner"] != request["expected_root_id"]:
        raise QueueConflictError("coordinator predecessor native root identity changed")
    with _readonly_root(native_root(request)) as conn:
        accepted = dict(conn.execute(
            "SELECT key,value FROM daemon_metadata WHERE key IN "
            "('scheduling_fingerprint','scheduling_epoch','active_configuration_revision')"
        ))
    if accepted.get("scheduling_fingerprint") != authored:
        raise QueueConflictError("coordinator predecessor differs from accepted scheduling")
    return native["owner"], accepted


def probe(request):
    if role(request) != "agent":
        raise QueueConflictError("workload candidate requires an agent")
    authored = payload(request)
    if request.get("retire_configuration"):
        return _retirement_probe(request, authored)
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
    with _candidate_config(request, authored) as temporary:
        original = load_outbound_agent_service_config(
            temporary, env_file=environment(request)
        )
    return {
        "source": _qualified(original),
        "target": qualify(request, after, check_promotion=True, original=original),
        "image_sha256": sha,
        "declaration": after,
        "native_owner": owner(request),
    }


def _retirement_probe(request, authored):
    """Qualify a retirement target without probing the discarded predecessor."""
    from loom.queue.deployment import read_agent_spec
    from loom.queue._profile_promotion import validate_retirement_specs
    from loom.queue.retirement import read_agent_declaration_binding

    if any(key in request for key in ("workload_profile", "image", "image_sha256")):
        raise QueueConflictError("retirement must not select resident image promotion")
    after = request["candidate_declaration"]
    with _candidate_config(request, authored) as source:
        previous = read_agent_spec(source, env_file=environment(request))
    accepted = read_agent_declaration_binding(previous.agent_root, previous.declaration_digest)
    if accepted is None:
        raise QueueConflictError("retirement requires an accepted predecessor declaration")
    native = owner(request)
    if native["owner"] != accepted.root_id:
        raise QueueConflictError("retirement predecessor native root identity changed")
    with _candidate_config(request, after) as target:
        candidate = read_agent_spec(target, env_file=environment(request))
        validate_retirement_specs(previous, candidate)
        service = load_outbound_agent_service_config(target, env_file=environment(request))
    if read_agent_declaration_binding(previous.agent_root, previous.declaration_digest) != accepted:
        raise QueueConflictError("retirement predecessor changed during qualification")
    return {
        "source": {"declaration_digest": previous.declaration_digest,
                   "immutable": accepted.immutable_fingerprint, "active": accepted.active_fingerprint},
        "target": {**_qualified(service), "declaration_digest": candidate.declaration_digest},
        "declaration": after,
        "native_owner": native,
    }


def publish(request, directory):
    """Retain before/after source and reload only through native control owners."""
    if role(request) != "coordinator":
        raise QueueConflictError("native promotion owns agent source publication")
    stopped = request.get("stopped_retirement", False)
    if stopped and (request.get("retirement") is None or not request.get("expected_scheduling_epoch")):
        raise QueueConflictError("stopped retirement requires an exact maintenance and scheduling binding")
    binding = read(Path(request["admin"]) / "service.json")
    releases = (request.get("source_release"), request["release"]) if stopped else (request["release"],)
    if (any(binding.get(key) != request.get(key) for key in ("root", "config"))
        or binding.get("release") not in releases):
        raise QueueConflictError("workload retained service binding differs")
    if owner(request)["owner"] != binding["expected_root_id"]:
        raise QueueConflictError("workload native root identity changed")
    # Bind the connection from the already verified service identity, leaving
    # retained host requests and exact reload replay bytes unchanged.
    bound_request = {**request, "coordinator_id": binding["expected_root_id"]}
    current = payload(request)
    target = request["declaration"]
    retained = directory / "reload.json"
    if retained.exists():
        intent = read(retained)
        if (intent["after"] != target or intent.get("reload", {}).get("retirement") != request.get("retirement")
            or intent.get("stopped_retirement", False) != stopped
            or (stopped and intent["reload"]["expected_scheduling_epoch"] != request["expected_scheduling_epoch"])):
            raise QueueConflictError("workload publication target or retirement binding changed")
        if not stopped and current != intent["after"] and request.get("retirement") is not None:
            from loom.fleet._host import coordinator_client

            _, client = coordinator_client(bound_request)
            _retirement_publication_ready(client, request["retirement"])
    else:
        intent = {"before": current, "after": target}
        if role(request) == "coordinator":
            from loom.fleet._host import coordinator_client
            from loom.queue.local_daemon import CoordinatorSchedulingReload

            if stopped:
                epoch = request["expected_scheduling_epoch"]
                intent["stopped_retirement"] = True
            else:
                _, client = coordinator_client(bound_request)
                epoch = client.status().scheduling_epoch
            intent["reload"] = CoordinatorSchedulingReload(
                request["request_id"],
                epoch,
                ("Fleet selected configuration retirement" if request.get("retirement") is not None
                 else "Fleet selected workload profile promotion"),
                retirement=request.get("retirement"),
            ).to_dict()
            if not stopped and request.get("retirement") is not None:
                _retirement_publication_ready(client, request["retirement"])
        atomic(retained, intent)
    if current not in (intent["before"], intent["after"]):
        raise QueueConflictError("workload role source changed during publication")
    staged = None
    if stopped:
        from loom.queue._coordinator_retirement import stage_retirement
        from loom.queue.local_daemon import CoordinatorSchedulingReload

        with _candidate_config(request, target) as candidate:
            staged = stage_retirement(config(request), candidate,
                CoordinatorSchedulingReload.from_dict(intent["reload"]),
                expected_root_id=binding["expected_root_id"], env_file=environment(request))
        if payload(request) != current:
            raise QueueConflictError("stopped retirement source changed before publication")
    if current != intent["after"]:
        atomic(config(request), intent["after"])
    result = {"outcome": "applied", "declaration": target}
    if stopped:
        return {**result, "reload": thaw_plain_data(staged),
                "activation": "applied" if staged["state"] == "applied" else "startup_recovery_required"}
    if role(request) == "coordinator":
        from loom.fleet._host import coordinator_client
        from loom.queue.local_daemon import CoordinatorSchedulingReload

        _, client = coordinator_client(bound_request)
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


def _retirement_publication_ready(client, binding):
    """Protect the source write; native reload owns final acceptance and replay."""
    capability = "quiescent-coordinator-retirement-v1"
    if capability not in client.describe_connection().capabilities:
        raise QueueConflictError("unsupported_capability: " + capability)
    gate = client.observe_maintenance()
    if (gate["state"] != "closed" or not gate["settled"] or gate["checks"]
        or gate["maintenance_id"] != binding["maintenance_id"]
        or gate["intent_digest"] != binding["maintenance_intent_digest"]
        or gate["revision"] != binding["expected_gate_revision"]):
        raise QueueConflictError("coordinator source publication requires exact settled maintenance")


def recover_service(request):
    """Reconcile an accepted native transition and retained service ownership.

    This action is reobserved on each continuation: a previous start receipt
    cannot prove the current process survived. It never creates a service binding.
    """
    from loom.fleet._host import start, digest
    from loom.fleet._startup import startup_path
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
    startup = {**retained, "startup_id": "workload-" + request["promotion_id"],
               "expected_declaration": digest(payload(request))}
    launch = startup_path(startup)
    if fact["value"]["ownership"] != "live" or (launch.exists() and not read(launch)["ready"]):
        if not launch.exists():
            service = load_outbound_agent_service_config(
                config(request), env_file=environment(request)
            )
            recover(service.client)
        start(startup)
    return {
        "outcome": "applied",
        "declaration": payload(request),
        "publication_state": publication_state(
            Path(request["root"]), request["promotion_id"]
        ),
    }


def retire_stopped(request):
    """Receive and apply native retirement while the agent service is stopped.

    Native delivery and promotion journals own authorization and interrupted
    source publication. Runtime replacement/start and acknowledgement remain
    separate Fleet continuation steps.
    """
    from loom.fleet._host import digest
    from loom.queue.agent_sessions import AgentControl, AgentControlKind
    from loom.queue.deployment import read_agent_spec
    from loom.queue._profile_promotion import receive_stopped, apply_stopped, publication_state

    if role(request) != "agent":
        raise QueueConflictError("stopped retirement requires an agent")
    control = AgentControl.from_value(request["control"])
    if (control.kind is not AgentControlKind.PROMOTE
        or not control.promotion.get("retire_configuration")
        or control.promotion["agent_root_id"] != request["expected_root_id"]):
        raise QueueConflictError("stopped retirement control identity differs")
    binding = read(Path(request["admin"]) / "service.json")
    if (any(binding.get(key) != request.get(key) for key in ("root", "config", "expected_root_id"))
        or binding.get("release") not in (request["source_release"], request["release"])):
        raise QueueConflictError("workload retained service binding differs")
    spec = read_agent_spec(config(request), env_file=environment(request))
    if spec.agent_root != Path(request["root"]):
        raise QueueConflictError("stopped retirement source selects another native root")
    state = publication_state(spec.agent_root, control.operation_id)
    if state is None:
        if digest(payload(request)) != request["expected_declaration"]:
            raise QueueConflictError("target declaration changed since expected input")
        receive_stopped(spec, control, expected_coordinator_id=request["coordinator_id"])
    # Pending/applied effects must bypass predecessor delivery: the native
    # journal validates exact control replay and owns the changed source bytes.
    effect = apply_stopped(spec, control)
    return {"outcome": "applied", "effect": effect.value(),
            "declaration": payload(request), "activation": "runtime_start_required"}


def stage(request):
    if request.get("retire_configuration"):
        target = _retirement_probe({**request, "candidate_declaration": request["declaration"]}, payload(request))["target"]
    else:
        _image(request["image"], request["image_sha256"])
        target = qualify(request, request["declaration"])
    if target != request["target"]:
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
    if request["action"] == "workload-stopped-retire":
        return retire_stopped(request)
    if request["action"] == "workload-publish":
        return publish(request, directory)
    raise QueueConflictError("unsupported fixed workload host action")
