"""Whole-fleet service maintenance over native gate, control and check owners.

The protected operation directory retains administrative intent only. Every
capacity, settlement and policy decision comes from a fresh native observation.
"""

from __future__ import annotations

from dataclasses import replace
import fcntl
import hashlib
from pathlib import Path
from typing import Any, cast
import math

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.deployment import load_deployment
from loom.fleet.configuration import protected_directory, _environment_files
from loom.fleet._host import atomic, read, digest
from loom.fleet import ssh_operations as sshops
from loom.fleet.releases import verify_release
from loom.fleet.self_tests import self_test
from loom.fleet.probes import probe_configuration
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.deployment import load_coordinator_connection_file
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.queue.operations import OPERATOR_CAPABILITY, CONDITIONAL_CONTROL_CAPABILITY
from loom.serialization import thaw_plain_data

REQUIRED_CAPABILITIES = (
    OPERATOR_CAPABILITY,
    "maintenance-admission-v1",
    CONDITIONAL_CONTROL_CAPABILITY,
)


class _Waiting(Exception):
    pass


def _checks(inventory, deployment, connection, config):
    if deployment is None or connection is None:
        for path in sorted(
            (inventory.path.parent / "operations").glob("*/result.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            result = read(path)
            if (
                result.get("state") == "complete"
                and result.get("deployment")
                and result.get("operator_connection")
            ):
                deployment = deployment or Path(result["deployment"])
                connection = connection or Path(result["operator_connection"])
                break
    if deployment is None or connection is None:
        raise QueueConfigError(
            "upgrade requires --deployment and --connection, or retained completed setup bindings"
        )
    selected = load_deployment(deployment)
    if (
        selected.connection is None
        or selected.coordinator is not None
        or selected.agent is not None
        or selected.source.mode != "shared"
    ):
        raise QueueConfigError(
            "upgrade checks require a connection-only shared-source deployment"
        )
    expected = load_coordinator_connection_file(connection).expected_coordinator_id
    if (
        expected is None
        or load_coordinator_connection_file(selected.connection).expected_coordinator_id
        != expected
    ):
        raise QueueConfigError("upgrade connections must pin the same coordinator")
    return {
        "deployment": str(Path(deployment).resolve()),
        "operator_connection": str(Path(connection).resolve()),
        "config": config,
        "coordinator_id": expected,
    }


def _capable(operator):
    observed = operator.observe_status()
    if observed.availability != "available" or observed.freshness != "current":
        raise QueueConflictError("source capability observation unavailable")
    missing = set(REQUIRED_CAPABILITIES) - set(observed.value.get("capabilities", ()))
    if missing:
        raise QueueConflictError(
            "unsupported_capability: source missing "
            + ", ".join(sorted(missing))
            + "; use the explicit quiesced bridge with operator exclusion"
        )
    return cast(dict[str, Any], observed.to_dict())


def preview(
    inventory,
    *,
    runtime_release=None,
    workload_profile=None,
    image=None,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    env_file=None,
):
    """Inspect source and exact target bytes without installs or native mutations.

    Candidate installation/probing is the first apply step, before gate closure;
    preview never presents an uninstalled candidate as qualified.
    """
    _environment_files(inventory, env_file)
    if workload_profile is not None or image is not None or workload_inventory is not None:
        if runtime_release is not None:
            raise QueueConfigError("service and workload targets are mutually exclusive")
        from .workload_upgrades import preview as workload_preview
        return workload_preview(inventory, workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
            deployment=deployment, connection=connection, config=config, env_file=env_file)
    if runtime_release is None:
        raise QueueConfigError("upgrade requires a runtime or workload target")
    target = verify_release(Path(runtime_release), previous=inventory.runtime_release)
    selected = _checks(inventory, deployment, connection, config)
    rows, declarations = sshops._selection(inventory, None, env_file)
    if len(rows) < 2:
        raise QueueConfigError(
            "upgrade requires one pure coordinator and separate agents"
        )
    with CoordinatorOperatorClient.from_connection_file(
        selected["operator_connection"]
    ) as operator:
        source = _capable(operator)
        gate = dict(operator.observe_maintenance())
        agents = {}
        for name in rows:
            if name != "coordinator":
                observation = operator.observe_agent(name)
                if observation.availability != "available" or (
                    observation.freshness != "current"
                    and not observation.value.get("drained")
                ):
                    raise QueueConflictError("source agent unavailable: " + name)
                agents[name] = thaw_plain_data(observation.value)
    from loom.queue.deployment import load_coordinator_service_config

    accepted = load_coordinator_service_config(
        inventory.hosts[0].config, env_file=_environment_files(inventory, env_file)["coordinator"]
    )
    if source["value"]["scheduling_fingerprint"] != accepted.active_fingerprint:
        raise QueueConflictError(
            "source authored policy differs from accepted native configuration"
        )
    from loom.fleet._credentials import fingerprint

    operator_connection = load_coordinator_connection_file(
        selected["operator_connection"]
    )
    coordinator = declarations["coordinator"]
    credential = coordinator["agent_server"]["credential_fingerprints"].get(
        fingerprint(operator_connection.certificate_path)
    )
    principals = [
        p
        for p in coordinator["agent_policy"]["principals"]
        if p["credential_id"] == credential and p["role"] == "operator"
    ]
    if len(principals) != 1 or not {"maintenance", "drain", "resume"}.issubset(
        principals[0]["actions"]
    ):
        raise QueueConfigError(
            "upgrade operator requires declared maintenance, drain and resume authority"
        )
    for name, row in rows.items():
        observed = sshops.ssh(
            row["host"], {**row, "action": "inspect", "release": target}
        )
        if (
            not observed["root_exists"]
            or observed["installed"] is None
            or observed["service_manager"] != inventory.service_manager
        ):
            raise QueueConflictError(
                "upgrade requires retained matching native roots and service backend"
            )
        if (
            observed["installed"]["release_id"] == target["release_id"]
            and observed["installed"]["descriptor_sha256"]
            != target["descriptor_sha256"]
        ):
            raise QueueConflictError(
                "same installed release label has different immutable bytes"
            )
        native = observed["native_owner"]
        expected = (
            selected["coordinator_id"]
            if name == "coordinator"
            else agents[name]["agent_root_id"]
        )
        if (
            native is None
            or native["owner"] != expected
            or native["value"]["ownership"] != "live"
        ):
            raise QueueConflictError(
                "source host identity or live ownership unavailable"
            )
        row.update(
            expected_root_id=expected,
            source_release=observed["installed"],
            native_owner=native,
        )
    return {
        "schema_version": 1,
        "outcome": "preview",
        "fleet": inventory.name,
        "release": target,
        "source": source,
        "gate": gate,
        "agents": agents,
        "hosts": rows,
        "declarations": declarations,
        "checks": selected,
        "candidate": "isolated installation and native probe required before gate closure",
        "sequence": [
            "prepare candidate",
            "close admission",
            "wait admitted work and native settlement",
            "conditional drain",
            "stop and migrate/replace",
            "reconcile",
            "authorize exact checks",
            "wait checks and release",
            "conditional policy restoration",
            "revoke checks and reopen",
        ],
        "irreversible": "first service stop/replacement intent",
        "required_capabilities": list(REQUIRED_CAPABILITIES),
    }


class _Upgrade(sshops._Operation):
    def __init__(self, inventory, directory, intent):
        super().__init__(
            replace(inventory, runtime_release=Path(intent["target_path"])),
            directory,
            intent,
        )
        self.operator = CoordinatorOperatorClient.from_connection_file(
            intent["check_selection"]["operator_connection"]
        )

    def recheck(self, pending_inputs=None):
        super().recheck(pending_inputs)

    def gate(self):
        gate = cast(
            dict[str, Any], thaw_plain_data(self.operator.observe_maintenance())
        )
        if (
            gate["state"] != "closed"
            or gate["maintenance_id"] != self.intent["operation_id"]
            or gate["intent_digest"] != digest(self.intent)
        ):
            raise QueueConflictError("maintenance gate owner/intent changed")
        return gate

    def native(self, key, request, invoke):
        directory = self.receipts / key
        protected_directory(directory)
        path = directory / "intent.json"
        if path.exists():
            if read(path) != request:
                raise QueueConflictError("retained native intent changed")
        else:
            atomic(path, request)
        self.recheck()
        atomic(
            directory / "dispatch.json",
            {"request_id": request["operation_id"], "outcome": "unknown"},
        )
        # Native exact replay, including after a lost reply, is authoritative.
        result = dict(invoke(request))
        atomic(directory / "receipt.json", result)
        return result

    def maintenance(self, key, action, check=None):
        path = self.receipts / key / "intent.json"
        request = (
            read(path)
            if path.exists()
            else {
                "operation_id": self.intent["operation_id"] + "-" + key,
                "maintenance_id": self.intent["operation_id"],
                "maintenance_intent_digest": digest(self.intent),
                "action": action,
                "expected_revision": self.operator.observe_maintenance()["revision"],
                "check": check,
            }
        )
        if request["action"] != action or request["check"] != check:
            raise QueueConflictError("maintenance continuation intent changed")
        return self.native(
            key,
            request,
            lambda value: self.operator.maintenance(
                value,
                expected_coordinator_id=self.intent["check_selection"][
                    "coordinator_id"
                ],
            ),
        )

    def policy(self, name, key, kind, predecessor):
        path = self.receipts / key / "intent.json"
        if path.exists():
            request = read(path)
        else:
            current = cast(
                dict[str, Any], thaw_plain_data(self.operator.observe_agent(name).value)
            )
            request = {
                **AgentControl(
                    self.intent["operation_id"] + "-" + key,
                    AgentControlKind(kind),
                    name,
                    current["session_id"],
                    current["config_revision"],
                    None,
                    False,
                    "Fleet maintenance policy",
                ).value(),
                "condition": {"expected_control_id": predecessor},
            }
        if request["kind"] != kind or request["condition"] != {
            "expected_control_id": predecessor
        }:
            raise QueueConflictError("policy continuation intent changed")
        successors = _control_successors(self, key)
        if successors:
            request = successors[-1]
            key += "-retry-" + str(len(successors))

        def invoke(value):
            condition = value["condition"]
            self.operator.control_agent(
                AgentControl.from_value(
                    {k: v for k, v in value.items() if k != "condition"}
                ),
                condition=condition,
            )
            return self.operator.observe_control(value["operation_id"])

        result = self.native(key, request, invoke)
        if result["state"] != "applied" or not result["acknowledged"]:
            if result["state"] == "failed":
                detail = "native control failed"
                if kind == "resume" and result.get("code") == "retained_work":
                    detail += "; explicit operation retry-control after recovery required"
                raise QueueConflictError(detail + ": " + str(result))
            raise _Waiting("native control acknowledgement: " + request["operation_id"])
        return request["operation_id"]

    def host_observe(self, name, action, **values):
        row = self.intent["hosts"][name]
        return sshops.ssh(
            row["host"],
            {
                **row,
                "action": action,
                "release": self.intent["release"],
                "expected_declaration": digest(self.intent["declarations"][name]),
                **values,
            },
        )

    def probes(self):
        for name, row in self.intent["hosts"].items():
            path = self.directory / (name + "-candidate.json")
            old = read(path) if path.exists() else None
            observed = self.host_observe(
                name,
                "upgrade-probe",
                required_capabilities=list(REQUIRED_CAPABILITIES),
                descriptor_name=Path(self.intent["target_path"]).name,
                images=None if old is None else old["images"],
            )
            if old is None:
                atomic(path, observed)

    def settled(self):
        gate = self.gate()
        if not gate.get("settled"):
            raise _Waiting(
                "native settlement: "
                + ", ".join(gate.get("wait_reasons", ["unavailable"]))
            )

    def verify_policy(self, name, expected):
        observation = self.operator.observe_agent(name)
        if observation.availability != "available":
            raise _Waiting("agent policy observation required: " + name)
        value = cast(dict[str, Any], thaw_plain_data(observation.value))
        if observation.freshness != "current":
            # Drained agents stop refreshing capacity offers. Confirm the service
            # directly; an expired offer never establishes available capacity.
            if not value.get("drained"):
                raise _Waiting("fresh agent identity required: " + name)
            row = self.intent["hosts"][name]
            inspected = sshops.ssh(
                row["host"],
                {**row, "action": "inspect", "release": self.intent["release"]},
            )
            native = inspected["native_owner"]
            if (
                native is None
                or native["owner"] != row["expected_root_id"]
                or native["value"]["ownership"] != "live"
                or native["value"].get("session_id") != value["session_id"]
            ):
                raise _Waiting("live drained agent identity required: " + name)
        if (
            value["agent_root_id"] != self.intent["hosts"][name]["expected_root_id"]
            or value["session_id"] != self.intent["agents"][name]["session_id"]
        ):
            raise QueueConflictError("native agent/session identity changed")
        if (value.get("control") or {}).get("operation_id") != expected:
            raise QueueConflictError("independent native policy edit: " + name)
        return value

    def close(self):
        self.operator.close()


def _attempts(operation):
    path = operation.directory / "checks.json"
    return read(path) if path.exists() else {}


def _prepare_attempt(operation, name, check, identity, previous=None):
    path = operation.inventory.path.parent / "checks" / identity / "intent.json"
    binding = {
        "operation_id": operation.intent["operation_id"],
        "target_intent_digest": digest(operation.intent),
    }
    if path.exists():
        intent = read(path)
        if intent.get("maintenance_binding") != binding:
            raise QueueConflictError("check belongs to another maintenance intent")
    else:
        selection = operation.intent["check_selection"]
        deployment = load_deployment(selection["deployment"])
        declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
        profile_id = declarations[name]["resident_profiles"][0][
            "descriptor"
        ]["profile_id"]
        policies = declarations["coordinator"]["preparation"][
            "profiles"
        ]
        matches = [
            key
            for key, value in policies.items()
            if value["resident_profile_id"] == profile_id
        ]
        chosen = (
            deployment.preparation_profile
            if deployment.preparation_profile in matches
            else matches[0]
            if len(matches) == 1
            else None
        )
        if chosen is None:
            raise QueueConfigError("check preparation profile is ambiguous for " + name)
        from loom.deployment import export_connection_deployment

        selected_path = operation.directory / (name + "-check-selection.json")
        if selected_path.exists():
            retained_selection = load_deployment(selected_path)
            if (
                retained_selection.source != deployment.source
                or retained_selection.connection != deployment.connection
                or retained_selection.preparation_profile != chosen
            ):
                raise QueueConflictError("retained check selection changed")
        else:
            export_connection_deployment(
                replace(deployment, preparation_profile=chosen), selected_path
            )
        intent = self_test(
            operation.inventory,
            deployment=selected_path,
            operator_connection=Path(selection["operator_connection"]),
            config=selection["config"],
            agent_id=name,
            checks=[check],
            env_file=None
            if operation.intent["env_file"] is None
            else Path(operation.intent["env_file"]),
            _prepare_id=identity,
            _maintenance_binding=binding,
        )
    if intent["agent_id"] != name or set(intent["requests"]) != {check}:
        raise QueueConflictError("check attempt identity conflicts")
    from loom.fleet._credentials import fingerprint

    connection = load_coordinator_connection_file(intent["connection"])
    declaration = operation.intent.get("target_declarations", operation.intent["declarations"])["coordinator"]
    credential = declaration["agent_server"]["credential_fingerprints"].get(
        fingerprint(connection.certificate_path)
    )
    principals = [
        p
        for p in declaration["agent_policy"]["principals"]
        if p["credential_id"] == credential and p["role"] == "client"
    ]
    if len(principals) != 1:
        raise QueueConflictError(
            "check principal must match one declared native client"
        )
    from loom.pipeline.resources import ResourceRequest, ResourceEntry

    def resources(kind):
        entries = probe_configuration(kind, name)["pipeline"]["stages"][0]["resources"][
            "entries"
        ]
        return ResourceRequest(
            {key: ResourceEntry.from_dict(value) for key, value in entries.items()}
        ).to_dict()

    return {
        "maintenance_id": operation.intent["operation_id"],
        "target_intent_digest": digest(operation.intent),
        "previous_check_id": previous,
        "operation_id": identity,
        "slot": [name, check],
        "request_digest": digest(intent["requests"][check]),
        "expected_gate_revision": operation.gate()["revision"],
        "authorization": {
            "request": intent["requests"][check],
            "principal_id": principals[0]["principal_id"],
            "agent_id": name,
            "pool": "default",
            "profile": intent["profile"],
            "resources": resources(check),
            "preparation_resources": resources("cpu"),
            "max_stages": 1,
            "previous_check_id": previous,
        },
    }


def _run_checks(operation):
    attempts = _attempts(operation)
    for name, declaration in operation.intent.get("target_declarations", operation.intent["declarations"]).items():
        if name == "coordinator" or name not in operation.intent["agents"]:
            continue
        profile = declaration["resident_profiles"][0]
        # Provider-backed GPUs belong to the native inventory, so their legacy
        # resident-profile device list can be empty even on a GPU agent.
        devices = profile.get("gpu_devices") or (
            operation.intent["agents"][name].get("offer") or {}
        ).get("gpu_devices")
        for check in (
            "cpu",
            "storage",
            *(["gpu"] if devices else []),
        ):
            slot = name + ":" + check
            if slot not in attempts:
                identity = (
                    "check-"
                    + hashlib.sha256(
                        (operation.intent["operation_id"] + slot).encode()
                    ).hexdigest()[:24]
                )
                attempts[slot] = [_prepare_attempt(operation, name, check, identity)]
                atomic(operation.directory / "checks.json", attempts)
            attempt = attempts[slot][-1]
            identity = attempt["operation_id"]
            operation.maintenance(
                "authorize-" + identity, "authorize", attempt["authorization"]
            )
            result = self_test(
                operation.inventory,
                operation_id=identity,
                timeout_seconds=operation.intent["timeout_seconds"],
            )
            atomic(operation.directory / (identity + "-result.json"), result)
            if result["outcome"] != "passed":
                if result["outcome"] in {"failed", "unsupported"}:
                    raise QueueConflictError(
                        "check "
                        + identity
                        + " "
                        + result["outcome"]
                        + "; explicit operation retry-check required"
                    )
                raise _Waiting("check " + identity + ": " + result["outcome"])
    operation.settled()


def _restore(operation, *, abort=False):
    for name, original in operation.intent["agents"].items():
        keys = [name + "-drain", name + "-checks-capacity"]
        predecessor = (original.get("control") or {}).get("operation_id")
        changed = False
        for key in keys:
            path = operation.receipts / key / "intent.json"
            if path.exists():
                request = read(path)
                predecessor = operation.policy(
                    name,
                    key,
                    request["kind"],
                    request["condition"]["expected_control_id"],
                )
                changed = True
        if changed:
            # Temporary check capacity already restored an originally open policy.
            # Verify ownership without dispatching a redundant native resume.
            if (
                not original["drained"]
                and (
                    operation.receipts / (name + "-checks-capacity") / "intent.json"
                ).exists()
            ):
                operation.verify_policy(name, predecessor)
            else:
                key = name + ("-abort-restore" if abort else "-restore")
                restored = operation.policy(
                    name, key, "drain" if original["drained"] else "resume", predecessor
                )
                operation.verify_policy(name, restored)
    if (operation.receipts / "open" / "intent.json").exists():
        operation.maintenance("open", "open")
        return
    # Abort restores administrative policy while admitted ordinary work continues.
    # Successful replacement still requires every native effect to settle.
    if not abort:
        operation.settled()
    for identity in list(operation.gate()["checks"]):
        operation.maintenance("revoke-" + identity, "revoke", identity)
    operation.maintenance("open", "open")


def _continue(operation):
    if operation.intent.get("kind") == "workload-upgrade":
        from .workload_upgrades import continue_upgrade
        return continue_upgrade(operation)
    if (operation.directory / "complete.json").exists():
        return read(operation.directory / "complete.json")
    operation.recheck()
    irreversible = operation.directory / "irreversible.json"
    if not irreversible.exists():
        _capable(operation.operator)
        for name, row in operation.intent["hosts"].items():
            sshops.ssh(
                row["host"],
                {
                    **row,
                    "action": "install-candidate",
                    "release": operation.intent["release"],
                    **sshops._bundle(operation.inventory),
                },
            )
        operation.probes()
        operation.maintenance("close", "close")
        operation.settled()
        for name, agent in operation.intent["agents"].items():
            predecessor = (agent.get("control") or {}).get("operation_id")
            accepted = operation.policy(name, name + "-drain", "drain", predecessor)
            operation.verify_policy(name, accepted)
        operation.settled()
        for name in operation.intent["hosts"]:
            fact = operation.host_observe(name, "upgrade-settlement")
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise _Waiting("host native settlement: " + name + ": " + str(fact))
        atomic(
            irreversible,
            {"step": "stop-replace", "intent_digest": digest(operation.intent)},
        )
    # Host receipts retain exact stop/migrate/start requests across coordinator downtime.
    for name in [*operation.intent["agents"], "coordinator"]:
        row = operation.intent["hosts"][name]
        operation.call(
            name,
            "upgrade-stop",
            expected_root_id=row["expected_root_id"],
            descriptor_name=Path(operation.intent["target_path"]).name,
            required_capabilities=list(REQUIRED_CAPABILITIES),
            images=read(operation.directory / (name + "-candidate.json"))["images"],
        )
    for name, row in operation.intent["hosts"].items():
        operation.call(
            name,
            "upgrade-replace",
            expected_root_id=row["expected_root_id"],
            source_release=row["source_release"],
            coordinator_id=operation.intent["check_selection"]["coordinator_id"],
            descriptor_name=Path(operation.intent["target_path"]).name,
            required_capabilities=list(REQUIRED_CAPABILITIES),
            images=read(operation.directory / (name + "-candidate.json"))["images"],
        )
    _capable(operation.operator)
    if not (operation.receipts / "open" / "intent.json").exists():
        operation.gate()
    operation.probes()
    restoring = operation.directory / "restoring.json"
    if not restoring.exists():
        for name in operation.intent["agents"]:
            predecessor = operation.intent["operation_id"] + "-" + name + "-drain"
            accepted = operation.policy(
                name, name + "-checks-capacity", "resume", predecessor
            )
            operation.verify_policy(name, accepted)
        _run_checks(operation)
        atomic(restoring, {"intent_digest": digest(operation.intent)})
    _restore(operation)
    result = {
        "state": "complete",
        "release": operation.intent["release"],
        "checks": _attempts(operation),
        "deployment": operation.intent["check_selection"]["deployment"],
        "operator_connection": operation.intent["check_selection"][
            "operator_connection"
        ],
    }
    atomic(operation.directory / "complete.json", result)
    return result


def upgrade(
    inventory,
    *,
    operation_id=None,
    runtime_release=None,
    workload_profile=None,
    image=None,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    env_file=None,
    apply=False,
    timeout_seconds=120,
    action="resume",
    failed_check=None,
    new_check=None,
    failed_control=None,
    new_control=None,
):
    """Preview/apply or continue one immutable service upgrade; never cancel work."""
    _environment_files(inventory, env_file)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise QueueConfigError("timeout must be positive and finite")
    if runtime_release is not None and (workload_profile is not None or image is not None or workload_inventory is not None):
        raise QueueConfigError("service and workload targets are mutually exclusive")
    if apply and runtime_release is None and (workload_profile is None or image is None):
        raise QueueConfigError("apply requires --runtime-release or --workload-profile and --image")
    if not apply and operation_id is None:
        return preview(
            inventory,
            runtime_release=runtime_release,
            workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
            deployment=deployment,
            connection=connection,
            config=config,
            env_file=env_file,
        )
    if operation_id is None:
        raise QueueConfigError("apply requires --operation-id")
    directory = sshops._directory(inventory, operation_id)
    if not (directory / "intent.json").exists() and not apply:
        raise QueueConfigError("unknown upgrade operation")
    protected_directory(directory)
    with (directory / "writer.lock").open("a") as writer:
        try:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueConflictError("operation already has an active writer") from exc
        path = directory / "intent.json"
        if not path.exists():
            plan = preview(
                inventory,
                runtime_release=runtime_release,
                workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
                deployment=deployment,
                connection=connection,
                config=config,
                env_file=env_file,
            )
            target = Path(str(runtime_release or inventory.runtime_release)).resolve()
            inputs = sshops._inputs(inventory, plan["hosts"], env_file)
            for item in (
                target,
                Path(plan["checks"]["deployment"]),
                Path(plan["checks"]["operator_connection"]),
            ):
                inputs[str(item)] = sshops._file_hash(item)
            intent = {
                "schema_version": 1,
                "kind": "runtime-upgrade",
                "operation_id": operation_id,
                "target_path": str(target),
                "release": plan["release"],
                "hosts": plan["hosts"],
                "agents": plan["agents"],
                "declarations": plan["declarations"],
                "inputs": inputs,
                "check_selection": plan["checks"],
                "env_file": None if env_file is None else str(Path(env_file).resolve()),
                "timeout_seconds": timeout_seconds,
            }
            if workload_profile is not None:
                from .workload_upgrades import bind_intent
                intent = bind_intent(intent, plan, directory)
            atomic(path, intent)
        intent = read(path)
        if intent.get("kind") not in {"runtime-upgrade", "workload-upgrade"}:
            raise QueueConflictError("operation belongs to another kind")
        if runtime_release is not None and Path(runtime_release).resolve() != Path(
            intent["target_path"]
        ):
            raise QueueConflictError("upgrade target intent changed")
        if workload_profile is not None and (intent.get("workload_profile") != workload_profile or image is None or intent.get("image") != str(Path(image).resolve())):
            raise QueueConflictError("workload target intent changed")
        if workload_profile is not None and intent.get("workload_inventory") != (
            None if workload_inventory is None else str(Path(workload_inventory).resolve())
        ):
            raise QueueConflictError("workload inventory intent changed")
        if apply:
            selected = _checks(inventory, deployment, connection, config)
            if (
                selected != intent.get("original_check_selection", intent["check_selection"])
                or (None if env_file is None else str(Path(env_file).resolve()))
                != intent["env_file"]
            ):
                raise QueueConflictError("upgrade check or environment intent changed")
        if intent["kind"] == "workload-upgrade":
            from .workload_upgrades import WorkloadUpgrade
            operation = WorkloadUpgrade(inventory, directory, intent)
        else:
            operation = _Upgrade(inventory, directory, intent)
        try:
            if (directory / "aborted.json").exists():
                result = {"state": "aborted"}
            elif action == "abort":
                operation.recheck()
                if (directory / "complete.json").exists():
                    result = read(directory / "complete.json")
                elif (directory / "irreversible.json").exists():
                    raise QueueConflictError(
                        "irreversible stop/replacement may have begun; resume exact operation; no automatic rollback"
                    )
                else:
                    if (operation.receipts / "close" / "intent.json").exists():
                        operation.maintenance("close", "close")
                        _restore(operation, abort=True)
                    atomic(directory / "aborted.json", {"state": "aborted"})
                    result = {"state": "aborted"}
            elif action == "retry-check":
                result = _retry_check(operation, failed_check, new_check)
            elif action == "retry-control":
                result = _retry_control(operation, failed_control, new_control)
            else:
                result = _continue(operation)
        except (_Waiting, sshops.SshUnavailable) as exc:
            result = {"state": "waiting", "reason": str(exc)}
        except CoordinatorClientError as exc:
            result = {
                "state": "waiting"
                if exc.mutation_outcome == "unknown"
                or exc.code in {"unavailable", "deadline_exceeded"}
                else "blocked",
                "reason": exc.code,
                "native_error": exc.to_dict(),
            }
        except (QueueConfigError, QueueConflictError, OSError) as exc:
            result = {"state": "blocked", "reason": str(exc)}
        finally:
            operation.close()
        atomic(directory / "result.json", result)
        return sshops.operation_status(inventory, operation_id)


def _control_successors(operation, key):
    path = operation.receipts / key / "successors.json"
    return read(path) if path.exists() else []


def _retry_control(operation, failed, successor):
    """Select an explicit conditional successor for a failed maintenance resume.

    Existing native requests/effects remain immutable. The operator must resolve
    the underlying cause first; this action neither restarts nor replaces a role.
    """
    if not failed or not successor:
        raise QueueConfigError("retry-control requires --failed-control and --operation-id")
    sshops._directory(operation.inventory, successor)
    operation.recheck()
    selected = []
    for name in operation.intent["agents"]:
        for suffix in ("checks-capacity", "restore"):
            key = name + "-" + suffix
            path = operation.receipts / key / "intent.json"
            if not path.exists():
                continue
            original = read(path)
            rows = _control_successors(operation, key)
            requests = [original, *rows]
            if any(row["operation_id"] == failed for row in requests):
                selected.append((name, key, original, rows))
    if len(selected) != 1:
        raise QueueConflictError("failed control does not belong to this maintenance owner")
    name, key, original, rows = selected[0]
    current = rows[-1] if rows else original
    if current["operation_id"] == successor and current["condition"] == {
        "expected_control_id": failed
    }:
        return _continue(operation)
    operation.gate()
    if current["operation_id"] != failed:
        raise QueueConflictError("another successor already selects this policy")
    if current["kind"] != "resume":
        raise QueueConflictError("only failed maintenance resume controls can be retried")
    result = operation.operator.observe_control(failed)
    if result["state"] != "failed" or not result["acknowledged"]:
        raise QueueConflictError("replacement requires acknowledged native control failure")
    if result["code"] != "retained_work":
        raise QueueConflictError("resume retry requires a recovered retained_work failure")
    observed = operation.verify_policy(name, failed)
    if (
        not observed["drained"]
        or observed["session_id"] != current["expected_session_id"]
        or observed["config_revision"] != current["expected_config_revision"]
    ):
        raise QueueConflictError("failed resume agent policy changed")
    operation.settled()
    fact = operation.host_observe(name, "upgrade-settlement")
    if fact["availability"] != "available" or not fact["value"].get("settled"):
        raise _Waiting("failed resume native effects remain: " + failed)
    # A successor is new authority, never an alias for another native request.
    # Retained intents catch local lost-reply attempts; the native lookup catches
    # controls created independently of this Fleet operation.
    for path in operation.receipts.glob("*/intent.json"):
        if read(path).get("operation_id") == successor:
            raise QueueConflictError("successor identity already belongs to another intent")
    for path in operation.receipts.glob("*/successors.json"):
        if any(row["operation_id"] == successor for row in read(path)):
            raise QueueConflictError("successor identity already belongs to another intent")
    try:
        operation.operator.observe_control(successor)
    except CoordinatorClientError as exc:
        if exc.code != "not_found":
            raise
    else:
        raise QueueConflictError("successor identity already belongs to a native control")
    request = {
        **current,
        "operation_id": successor,
        "condition": {"expected_control_id": failed},
    }
    atomic(operation.receipts / key / "successors.json", [*rows, request])
    return _continue(operation)


def _retry_check(operation, failed, successor):
    if not failed or not successor:
        raise QueueConfigError("retry-check requires --failed-check and --operation-id")
    sshops._directory(operation.inventory, successor)
    operation.recheck()
    operation.gate()
    operation.probes()
    attempts = _attempts(operation)
    selected = [
        rows
        for rows in attempts.values()
        if any(row["operation_id"] == failed for row in rows)
    ]
    if len(selected) != 1:
        raise QueueConflictError(
            "failed check does not belong to this maintenance owner"
        )
    rows = selected[0]
    if (
        rows[-1]["operation_id"] == successor
        and rows[-1]["previous_check_id"] == failed
    ):
        return _continue(operation)
    if rows[-1]["operation_id"] != failed:
        raise QueueConflictError("another successor already selects this slot")
    result = self_test(
        operation.inventory,
        operation_id=failed,
        timeout_seconds=operation.intent["timeout_seconds"],
    )
    if result["outcome"] != "failed" or not any(
        row.get("code") == "native_check_failed" for row in result["checks"].values()
    ):
        raise QueueConflictError(
            "replacement requires confirmed native terminal failure"
        )
    operation.settled()
    for name in operation.intent["hosts"]:
        fact = operation.host_observe(
            name, "upgrade-settlement", include_pending_poll=False
        )
        if fact["availability"] != "available" or not fact["value"].get("settled"):
            raise _Waiting("prior check native effects remain: " + failed)
    name, check = rows[-1]["slot"]
    if any(
        row["operation_id"] == successor
        for values in attempts.values()
        for row in values
    ):
        raise QueueConflictError("successor identity already belongs to another intent")
    rows.append(_prepare_attempt(operation, name, check, successor, previous=failed))
    atomic(operation.directory / "checks.json", attempts)
    return _continue(operation)
