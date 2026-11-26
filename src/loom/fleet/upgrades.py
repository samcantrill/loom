"""Whole-fleet service maintenance over native gate, control and check owners.

The protected operation directory retains administrative intent only. Every
capacity, settlement and policy decision comes from a fresh native observation.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, cast
import math
import time

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.deployment import load_deployment
from loom.fleet.configuration import protected_directory, _environment_files
from loom.fleet._host import atomic, read, digest
from loom.fleet import ssh_operations as sshops
from loom.fleet._upgrade_progress import Observation, ProgressSink, milestone, phase, reason
from loom.fleet._check_workers import completed_steps, wait_for_checks
from loom.fleet._timing import bind_directory, measure, recording, timed
from loom.fleet.releases import verify_release
from loom.fleet.self_tests import self_test, _check_input_locations, _wait_check_change
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
    def __init__(self, message, code="acknowledgement_pending"):
        super().__init__(message)
        self.code = code


def _reason_code(exc):
    if isinstance(exc, _Waiting):
        return exc.code
    if isinstance(exc, sshops.SshStarting):
        return "acknowledgement_pending"
    if isinstance(exc, sshops.SshUnavailable):
        return "host_unavailable"
    if isinstance(exc, CoordinatorClientError):
        return "coordinator_unavailable" if exc.mutation_outcome == "unknown" or exc.code in {"unavailable", "deadline_exceeded"} else "native_refusal"
    if isinstance(exc, QueueConfigError):
        return "input_invalid"
    if isinstance(exc, QueueConflictError):
        return "native_refusal"
    return "unknown"


def _maintenance_binding(intent):
    """A workload repair borrows its unchanged runtime operation's native gate."""
    return intent.get("maintenance_binding", {
        "operation_id": intent["operation_id"],
        "target_intent_digest": digest(intent),
    })



def _existing_maintenance_binding(gate, maintenance_id):
    """Borrow an explicitly selected empty gate; its owner remains responsible for opening."""
    if maintenance_id is None:
        return None
    if (gate.get("state") != "closed" or gate.get("maintenance_id") != maintenance_id
            or not gate.get("intent_digest") or gate.get("checks")):
        raise QueueConflictError("selected maintenance gate is unavailable or has active checks")
    return {"operation_id": maintenance_id, "target_intent_digest": gate["intent_digest"]}

def _checks(inventory, deployment, connection, config, check_execution=None):
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
        **({"execution": check_execution.to_dict()} if check_execution is not None else {}),
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
    recover_retained_results=False,
    hold_admission=False,
    maintenance_id=None,
    workload_profile=None,
    retire_configuration=False,
    add_container_policies=False,
    increase_publication_budgets=False,
    image=None,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    check_execution=None,
    env_file=None,
):
    """Inspect source and exact target bytes without installs or native mutations.

    Candidate installation/probing is the first apply step, before gate closure;
    preview never presents an uninstalled candidate as qualified.
    """
    _environment_files(inventory, env_file)
    if maintenance_id is not None and (runtime_release is None or hold_admission or retire_configuration
            or add_container_policies or increase_publication_budgets or workload_profile is not None):
        raise QueueConfigError("existing maintenance requires a runtime-only upgrade without publication hold")
    if increase_publication_budgets:
        if retire_configuration or add_container_policies or runtime_release is not None or workload_profile is not None or image is not None or recover_retained_results:
            raise QueueConfigError("publication budget increase must be separate from runtime, retirement, policy addition and image changes")
        from .workload_upgrades import configuration_preview
        result = configuration_preview(inventory, workload_inventory=workload_inventory,
            deployment=deployment, connection=connection, config=config, check_execution=check_execution,
            env_file=env_file, increase_publication_budgets=True)
        return {**result, "hold_admission": hold_admission}
    if add_container_policies:
        if retire_configuration or runtime_release is not None or workload_profile is not None or image is not None or recover_retained_results:
            raise QueueConfigError("container policy addition must be separate from runtime, retirement and image changes")
        from .workload_upgrades import configuration_preview
        result = configuration_preview(inventory, workload_inventory=workload_inventory,
            deployment=deployment, connection=connection, config=config, check_execution=check_execution,
            env_file=env_file, add_container_policies=True)
        return {**result, "hold_admission": hold_admission}
    if retire_configuration:
        if workload_profile is not None or image is not None or recover_retained_results:
            raise QueueConfigError("configuration retirement cannot select resident image promotion or result recovery")
        if runtime_release is not None:
            from .runtime_retirement import preview as retirement_preview
            result = retirement_preview(inventory, runtime_release=runtime_release,
                workload_inventory=workload_inventory, deployment=deployment,
                connection=connection, config=config, check_execution=check_execution, env_file=env_file)
            return {**result, "hold_admission": hold_admission}
        from .workload_upgrades import configuration_preview

        result = configuration_preview(inventory, workload_inventory=workload_inventory,
            deployment=deployment, connection=connection, config=config,
            check_execution=check_execution, env_file=env_file)
        return {**result, "hold_admission": hold_admission}
    if recover_retained_results and (runtime_release is None or workload_profile is not None):
        raise QueueConfigError("retained-result recovery requires a runtime target")
    if workload_profile is not None or image is not None or workload_inventory is not None:
        if check_execution is not None:
            raise QueueConfigError("resident workload promotion requires installed-profile checks")
        if runtime_release is not None:
            raise QueueConfigError("service and workload targets are mutually exclusive")
        from .workload_upgrades import preview as workload_preview
        result = workload_preview(inventory, workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
            deployment=deployment, connection=connection, config=config, env_file=env_file)
        return {**result, "hold_admission": hold_admission}
    if runtime_release is None:
        raise QueueConfigError("upgrade requires a runtime or workload target")
    target = verify_release(Path(runtime_release), previous=inventory.runtime_release)
    selected = _checks(inventory, deployment, connection, config, check_execution)
    rows, declarations = sshops._selection(inventory, None, env_file, runtime_upgrade=True)
    if len(rows) < 2:
        raise QueueConfigError(
            "upgrade requires one pure coordinator and separate agents"
        )
    with CoordinatorOperatorClient.from_connection_file(
        selected["operator_connection"]
    ) as operator:
        source = _capable(operator)
        gate = dict(operator.observe_maintenance())
        binding = _existing_maintenance_binding(gate, maintenance_id)
        agents = {}
        flows = {name: sshops.rpc((name,), operator.observe_agent, name)
                 for name in rows if name != "coordinator"}
        observations = sshops.host_steps(object(), flows, sshops.observer_end(), sshops.SshUnavailable)
        for name in flows:
            observation = observations[name]
            if observation.availability != "available" or (
                observation.freshness != "current" and not observation.value.get("drained")
            ):
                raise QueueConflictError("source agent unavailable: " + name)
            agents[name] = thaw_plain_data(observation.value)
    from loom.queue.deployment import read_coordinator_scheduling_fingerprint

    authored_fingerprint = read_coordinator_scheduling_fingerprint(
        inventory.hosts[0].config, env_file=_environment_files(inventory, env_file)["coordinator"]
    )
    if source["value"]["scheduling_fingerprint"] != authored_fingerprint:
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
    slurm_roles = [name for name, declaration in declarations.items() if declaration.get("slurm_profiles")]
    if slurm_roles and recover_retained_results:
        raise QueueConfigError("Slurm runtime replacement requires full native and scheduler settlement")
    observations = sshops._ssh_many({name: (row["host"], {**row, "action": "inspect", "release": target,
                                                         "inspect_slurm": name in slurm_roles})
                                     for name, row in rows.items()})
    for name, row in rows.items():
        observed = observations[name]
        if isinstance(observed, Exception):
            raise observed
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
        "hold_admission": hold_admission,
        "maintenance_binding": binding,
        "fleet": inventory.name,
        **({"slurm": {name: observations[name]["slurm"] for name in slurm_roles}} if slurm_roles else {}),
        "release": target,
        "source": source,
        "gate": gate,
        "agents": agents,
        "hosts": rows,
        "declarations": declarations,
        "checks": selected,
        "candidate": "isolated installation and native probe required before gate closure",
        "recover_retained_results": recover_retained_results,
        "sequence": ([
            "prepare candidate", "verify the original closed gate" if binding else "close admission", "conditional drain",
            "prove durable contained results", "stop and replace communication runtimes",
            "replay retained results while drained", "resume agents",
            "wait admitted DAGs", "authorize exact checks",
            "wait checks and release", "conditional policy restoration",
        ] if recover_retained_results else [
            "prepare candidate",
            "verify the original closed gate" if binding else "close admission",
            "wait admitted work and native settlement",
            "conditional drain",
            "stop and replace",
            "reconcile",
            "authorize exact checks",
            "wait checks and release",
            "conditional policy restoration",
        ]) + ["revoke checks and preserve the closed gate" if binding else "revoke checks and reopen"],
        "irreversible": "first service stop/replacement intent",
        "required_capabilities": list(REQUIRED_CAPABILITIES),
    }


class _Upgrade(sshops._Operation):
    def __init__(self, inventory, directory, intent, observation=None):
        self.observation = observation
        super().__init__(
            replace(inventory, runtime_release=Path(intent["target_path"])),
            directory,
            intent,
        )
        self.operator = CoordinatorOperatorClient.from_connection_file(
            intent["check_selection"]["operator_connection"]
        )

    def recheck(self, pending_inputs=None):
        from ._inventory_publication import reconcile

        reconcile(self)
        super().recheck(pending_inputs)
        _check_selection(self)

    def observe_gate(self, *, deadline=None):
        deadline = sshops.observer_end(deadline)
        budget = {"deadline": deadline} if deadline is not None else {}
        gate = cast(dict[str, Any], thaw_plain_data(self.operator.observe_maintenance(**budget)))
        binding = _maintenance_binding(self.intent)
        if self.observation is not None:
            if gate["state"] == "open":
                self.observation.gate(False)
            elif gate["maintenance_id"] == binding["operation_id"] and gate["intent_digest"] == binding["target_intent_digest"]:
                self.observation.gate(True)
        return gate

    def gate(self, *, deadline=None):
        gate = self.observe_gate(deadline=deadline)
        binding = _maintenance_binding(self.intent)
        if (
            gate["state"] != "closed"
            or gate["maintenance_id"] != binding["operation_id"]
            or gate["intent_digest"] != binding["target_intent_digest"]
        ):
            raise QueueConflictError("maintenance gate owner/intent changed")
        return gate

    def native(self, key, request, invoke):
        return sshops.inline(self.native_steps(key, request, invoke))

    def native_steps(self, key, request, invoke):
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
        result = dict((yield from sshops.rpc((key, "native"), invoke, request)))
        atomic(directory / "receipt.json", result)
        return result

    def maintenance(self, key, action, check=None, *, deadline=None, revision=None):
        deadline = sshops.observer_end(deadline)
        path = self.receipts / key / "intent.json"
        fresh = not (self.receipts / key / "dispatch.json").exists()
        if action in {"close", "open"}:
            phase(self, "closing_admission" if action == "close" else "reopening_admission")
        binding = _maintenance_binding(self.intent)
        request = (
            read(path)
            if path.exists()
            else {
                "operation_id": self.intent["operation_id"] + "-" + key,
                "maintenance_id": binding["operation_id"],
                "maintenance_intent_digest": binding["target_intent_digest"],
                "action": action,
                "expected_revision": self.observe_gate(deadline=deadline)["revision"] if revision is None else revision,
                "check": check,
            }
        )
        if request["action"] != action or request["check"] != check:
            raise QueueConflictError("maintenance continuation intent changed")
        result = self.native(
            key,
            request,
            lambda value: self.operator.maintenance(
                value,
                expected_coordinator_id=self.intent["check_selection"][
                    "coordinator_id"
                ],
                **({"deadline": deadline} if deadline is not None else {}),
            ),
        )
        if action == "open" and fresh and self.observation is not None:
            self.observation.gate(False)
        return result

    def policy(self, name, key, kind, predecessor):
        return sshops.inline(self.policy_steps(name, key, kind, predecessor))

    def policy_steps(self, name, key, kind, predecessor):
        budget: dict[str, Any] = {} if self.deadline is None else {"deadline": self.deadline}
        path = self.receipts / key / "intent.json"
        if path.exists():
            request = read(path)
        else:
            observed = yield from sshops.rpc((key, "observe"), self.operator.observe_agent, name, **budget)
            current = cast(dict[str, Any], thaw_plain_data(observed.value))
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
                condition=condition, **budget,
            )
            return self.operator.observe_control(value["operation_id"], **budget)

        result = yield from self.native_steps(key, request, invoke)
        if result["state"] != "applied" or not result["acknowledged"]:
            if result["state"] == "failed":
                detail = "native control failed"
                if kind == "resume" and result.get("code") == "retained_work":
                    detail += "; explicit operation retry-control after recovery required"
                raise QueueConflictError(detail + ": " + str(result))
            raise _Waiting("native control acknowledgement: " + request["operation_id"])
        return request["operation_id"]

    def _observation_request(self, name, action, **values):
        row = self.intent["hosts"][name]
        return (
            row["host"],
            {
                **row,
                "action": action,
                "release": self.intent["release"],
                "expected_declaration": digest(self.accepted_declaration(name)),
                **_slurm_binding(self, name),
                **values,
            },
        )

    def host_observe(self, name, action, **values):
        return sshops.ssh(*self._observation_request(name, action, **values))

    def host_observations(self, names, action, **values):
        requests = {name: self._observation_request(name, action, **values) for name in names}
        results = sshops._ssh_many(requests)
        for name in requests:
            if isinstance(results[name], Exception):
                raise results[name]
            yield name, results[name]

    def accepted_declaration(self, name):
        path = Path(self.intent["hosts"][name]["config"])
        updates_path = self.directory / "accepted-inputs.json"
        updates = read(updates_path) if updates_path.exists() else {}
        if str(path) not in updates:
            return self.intent["declarations"][name]
        if sshops._file_hash(path) != updates[str(path)]:
            raise QueueConflictError("accepted role publication changed")
        environment = self.intent["hosts"][name]["env_file"]
        return sshops._load_protected_config(path, env_file=None if environment is None else Path(environment))[2]

    def probes(self):
        requests, retained = {}, {}
        for name, row in self.intent["hosts"].items():
            path = self.directory / (name + "-candidate.json")
            retained[name] = path.exists()
            request = {**row, "release": self.intent["release"]}
            if retained[name]:
                request["action"] = "inspect"
            else:
                request.update(
                    action="upgrade-probe",
                    expected_declaration=digest(self.accepted_declaration(name)),
                    required_capabilities=list(REQUIRED_CAPABILITIES),
                    descriptor_name=Path(self.intent["target_path"]).name,
                    images=None,
                )
            requests[name] = (row["host"], request)
        errors = []
        for name, observed in sshops._ssh_many(requests).items():
            try:
                if isinstance(observed, Exception):
                    raise observed
                if retained[name]:
                    row = self.intent["hosts"][name]
                    # Activation still verifies bytes; retained qualification
                    # never proves current service ownership.
                    native = observed["native_owner"]
                    if observed["installed"] not in (row["source_release"], self.intent["release"]):
                        raise QueueConflictError("runtime service release changed")
                    if native is None or native["owner"] != row["expected_root_id"]:
                        raise QueueConflictError("upgrade native root identity changed")
                    if native["value"]["ownership"] != "live":
                        raise _Waiting("native service readiness: " + name)
                else:
                    atomic(self.directory / (name + "-candidate.json"), observed)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def settled(self, *, deadline=None):
        phase(self, "settling")
        gate = self.gate(**({"deadline": deadline} if deadline is not None else {}))
        if not gate.get("settled"):
            raise _Waiting(
                "native settlement: "
                + ", ".join(gate.get("wait_reasons", ["unavailable"])),
                "settlement_pending"
            )

    def verify_policy(self, name, expected):
        return sshops.inline(self.verify_policy_steps(name, expected))

    def verify_policy_steps(self, name, expected):
        budget: dict[str, Any] = {} if self.deadline is None else {"deadline": self.deadline}
        observation = yield from sshops.rpc((name, expected, "verify"), self.operator.observe_agent, name, **budget)
        if observation.availability != "available":
            raise _Waiting("agent policy observation required: " + name)
        value = cast(dict[str, Any], thaw_plain_data(observation.value))
        if observation.freshness != "current":
            # Drained agents stop refreshing capacity offers. Confirm the service
            # directly; an expired offer never establishes available capacity.
            if not value.get("drained"):
                raise _Waiting("fresh agent identity required: " + name)
            row = self.intent["hosts"][name]
            inspected = yield from sshops.rpc((name, expected, "inspect"), sshops.ssh,
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


def _deferred_checks(operation):
    path = operation.directory / "deferred-checks.json"
    if not path.exists():
        return {}
    value = read(path)
    if value["intent_digest"] != digest(operation.intent):
        raise QueueConflictError("qualification exception belongs to another upgrade")
    return value


def _bind_deferred_checks(operation, agents, reason):
    """Retain an explicit operator exception without rewriting check evidence."""
    if (operation.directory / "workload-repair" / "intent.json").exists():
        raise QueueConfigError("qualification deferral is not supported during a bound workload repair")
    if not agents or isinstance(agents, str) or not isinstance(reason, str) or not reason.strip():
        raise QueueConfigError("deferred qualification requires agent IDs and a reason")
    if any(not isinstance(name, str) or name not in operation.intent["agents"] for name in agents):
        raise QueueConfigError("deferred qualification agent is not an upgrade consumer")
    value = {
        "intent_digest": digest(operation.intent),
        "agents": sorted(set(agents)),
        "reason": reason.strip(),
    }
    retained = _deferred_checks(operation)
    if retained:
        if retained != value:
            raise QueueConflictError("retained qualification exception changed")
        return
    if any((operation.directory / name).exists() for name in ("complete.json", "restoring.json", "aborted.json")):
        raise QueueConflictError("qualification exception requires unfinished checks")
    operation.recheck()
    atomic(operation.directory / "deferred-checks.json", value)


def _qualification_result(operation) -> dict[str, Any]:
    deferred = _deferred_checks(operation)
    return {} if not deferred else {
        "qualification": {
            "state": "partial",
            "deferred_agents": deferred["agents"],
            "reason": deferred["reason"],
        }
    }


def _check_selection(operation):
    """Read the original selection or its explicitly bound profile-only repair."""
    path = operation.directory / "check-selection-repair.json"
    if not path.exists():
        return operation.intent["check_selection"]
    receipt = read(path)
    if receipt["intent_digest"] != digest(operation.intent):
        raise QueueConflictError("check selection repair belongs to another upgrade")
    if sshops._file_hash(Path(receipt["deployment"])) != receipt["deployment_sha256"]:
        raise QueueConflictError("repaired check deployment changed")
    return {**operation.intent["check_selection"], "deployment": receipt["deployment"]}


def _repair_check_selection(operation, deployment):
    """Bind a profile-only correction before checks or after settled failures.

    The original input hashes, maintenance identity and service target remain
    immutable. Ordinary resume still owns checks, policy restoration and opening.
    """
    if deployment is None:
        raise QueueConfigError("repair-check-selection requires --deployment")
    candidate_path = Path(deployment).resolve()
    receipt = {
        "intent_digest": digest(operation.intent),
        "deployment": str(candidate_path),
        "deployment_sha256": sshops._file_hash(candidate_path),
    }
    path = operation.directory / "check-selection-repair.json"
    if path.exists():
        if read(path) != receipt:
            raise QueueConflictError("retained check selection repair changed")
        _check_selection(operation)
        return _continue(operation)
    if (
        operation.intent["kind"] not in {"runtime-upgrade", "runtime-upgrade-publication"}
        or not (operation.directory / "irreversible.json").exists()
        or any((operation.directory / item).exists() for item in (
            "restoring.json", "complete.json", "aborted.json",
            "workload-repair/intent.json",
        ))
        or any(not (operation.receipts / (name + "-upgrade-replace") / "receipt.json").exists()
               for name in operation.intent["hosts"])
    ):
        raise QueueConflictError("check selection repair requires replaced runtime before restoration")
    operation.recheck()
    operation.settled()  # Also checks the live native gate owner and digest.
    attempts = _attempts(operation)
    failed_ids = set()
    for rows in attempts.values():
        failed = rows[-1]["operation_id"]
        _require_failed_check(operation, failed)
        failed_ids.update(row["operation_id"] for row in rows)
    if attempts:
        for name, fact in operation.host_observations(operation.intent["hosts"], "upgrade-settlement", include_pending_poll=False):
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise _Waiting("prior check native effects remain before profile repair")
    original = load_deployment(operation.intent["check_selection"]["deployment"])
    candidate = load_deployment(candidate_path)
    if replace(candidate, path=original.path, preparation_profile=original.preparation_profile) != original:
        raise QueueConfigError("check selection repair may change only the preparation profile")
    declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
    execution = _check_execution(_check_selection(operation))
    for name in operation.intent["agents"]:
        if _check_profile(declarations, name, candidate, execution) != candidate.preparation_profile:
            raise QueueConfigError("repaired preparation profile does not match " + name)
        if not attempts and (operation.directory / (name + "-check-selection.json")).exists():
            raise QueueConflictError("check preparation already started")
        for check in ("cpu", "storage", "gpu"):
            identity = "check-" + hashlib.sha256((operation.intent["operation_id"] + name + ":" + check).encode()).hexdigest()[:24]
            if identity not in failed_ids and (operation.inventory.path.parent / "checks" / identity / "intent.json").exists():
                raise QueueConflictError("check preparation already started")
    # Bind the bytes just admitted, refusing concurrent edits before publication.
    if sshops._file_hash(candidate_path) != receipt["deployment_sha256"]:
        raise QueueConflictError("repaired check deployment changed")
    atomic(path, receipt)
    return _continue(operation)


def _check_execution(selection):
    from loom.queue.submitted_execution import SubmittedContainerExecution

    raw = selection.get("execution")
    return None if raw is None else SubmittedContainerExecution.from_dict(raw)


@timed("check_prepare")
def _check_profile(declarations, name, deployment, execution=None):
    declaration = declarations[name]
    policies = declarations["coordinator"]["preparation"]["profiles"]
    if execution is not None:
        ids = {p["policy_id"] for p in declaration.get("container_policies", ())}
        routes = {p.get("profile_id"): (p.get("submitted_container_policy") or {}).get("policy_id")
                  for p in declaration.get("slurm_profiles", ())}
        matches = [key for key, value in policies.items()
                   if (value.get("container_policy_id") == routes.get(value["execution_route"]["profile"])
                       if value.get("execution_route") else value.get("container_policy_id") in ids)]
    else:
        ids = {p["descriptor"]["profile_id"] for p in declaration["resident_profiles"]}
        matches = [key for key, value in policies.items()
                   if value.get("resident_profile_id") in ids]
    chosen = (deployment.preparation_profile if deployment.preparation_profile in matches
              else matches[0] if len(matches) == 1 else None)
    if chosen is None:
        raise QueueConfigError("check preparation profile is ambiguous for " + name)
    return chosen


def _check_kinds(operation, name, declaration):
    # Provider-backed GPU inventory need not appear in a resident profile list.
    devices = any(p.get("gpu_devices") for p in declaration["resident_profiles"]) or (
        operation.intent["agents"][name].get("offer") or {}
    ).get("gpu_devices")
    return ("cpu", "storage", *(["gpu"] if devices else []))


def _check_identity(operation, name, check):
    return "check-" + hashlib.sha256(
        (operation.intent["operation_id"] + name + ":" + check).encode()
    ).hexdigest()[:24]


def _preflight_checks(operation):
    """Retain actual candidate preparation through existing exact host receipts."""
    from loom.queue.preparation import PrepareRunRequest

    selection = _check_selection(operation)
    deployment = load_deployment(selection["deployment"])
    declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
    deferred = _deferred_checks(operation).get("agents", ())
    def preflight(name):
        chosen = _check_profile(declarations, name, deployment, _check_execution(selection))
        route = declarations["coordinator"]["preparation"]["profiles"][chosen].get("execution_route", {})
        requests = {}
        for check in _check_kinds(operation, name, declarations[name]):
            if check == "gpu" and operation.intent.get("gpu_qualification") == "nonexclusive":
                continue
            identity = _check_identity(operation, name, check)
            requests[check] = PrepareRunRequest(
                identity + "-preflight", identity, deployment.source,
                selection["config"], chosen,
                execution=_check_execution(selection),
                input_locations=_check_input_locations(_check_execution(selection)),
                overrides=tuple(key + "=" + json.dumps(value)
                                for key, value in probe_configuration(check, name, slurm_profile=route.get("profile")).items()),
            ).to_dict()
        captured = yield from operation.call_steps(
            "coordinator", "upgrade-check-capture", agent_id=name,
            expected_root_id=operation.intent["hosts"]["coordinator"]["expected_root_id"],
            candidate_declaration=declarations["coordinator"], checks=requests,
        )
        return (yield from operation.call_steps(name, "upgrade-check-prepare", **{
            "agent_id": name,
            "expected_root_id": operation.intent["hosts"][name]["expected_root_id"],
            "candidate_declaration": declarations[name], "bindings": captured["bindings"],
            **({"slurm_profile": route["profile"]} if route else {}),
        }))

    flows = {name: preflight(name) for name in operation.intent["agents"] if name not in deferred}
    sshops.host_steps(operation.directory, flows, operation.deadline, sshops.SshUnavailable)


def _prepare_attempt(operation, name, check, identity, previous=None, *, deadline=None, revision=None):
    path = operation.inventory.path.parent / "checks" / identity / "intent.json"
    binding = _maintenance_binding(operation.intent)
    if path.exists():
        intent = read(path)
        if intent.get("maintenance_binding") != binding:
            raise QueueConflictError("check belongs to another maintenance intent")
    else:
        selection = _check_selection(operation)
        deployment = load_deployment(selection["deployment"])
        declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
        chosen = _check_profile(declarations, name, deployment, _check_execution(selection))
        from loom.deployment import export_connection_deployment

        # A repaired selection must not rewrite the deployment bound by failed checks.
        suffix = "-repaired-check-selection.json" if (operation.directory / "check-selection-repair.json").exists() else "-check-selection.json"
        selected_path = operation.directory / (name + suffix)
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
        budget = {}
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Waiting("check preparation pending: " + identity)
            budget["timeout_seconds"] = remaining
        intent = self_test(
            operation.inventory,
            deployment=selected_path,
            operator_connection=Path(selection["operator_connection"]),
            config=selection["config"],
            execution=_check_execution(selection),
            agent_id=name,
            checks=[check],
            env_file=None
            if operation.intent["env_file"] is None
            else Path(operation.intent["env_file"]),
            _prepare_id=identity,
            _maintenance_binding=binding,
            **budget,
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

    preparation_resources = resources("cpu")
    if "slurm_profile" in intent:
        capture = read(operation.receipts / ("coordinator-upgrade-check-capture-" + name) / "receipt.json")
        preparation_resources = capture["preparation_resources"][check]
    return {
        "maintenance_id": binding["operation_id"],
        "target_intent_digest": binding["target_intent_digest"],
        "previous_check_id": previous,
        "operation_id": identity,
        "slot": [name, check],
        "request_digest": digest(intent["requests"][check]),
        "expected_gate_revision": operation.gate()["revision"] if revision is None else revision,
        "authorization": {
            "request": intent["requests"][check],
            "principal_id": principals[0]["principal_id"],
            "agent_id": name,
            "pool": "default",
            "profile": intent["profile"],
            "resources": resources(check),
            "preparation_resources": preparation_resources,
            "max_stages": 1,
            "previous_check_id": previous,
            **({"slurm_profile": intent["slurm_profile"]} if "slurm_profile" in intent else {}),
        },
    }


def _gpu_capability(operation, name, declaration, deadline):
    observed = operation.operator.observe_agent(name, deadline=deadline)
    if observed.availability != "available" or observed.freshness != "current":
        raise _Waiting("current GPU capability profile required: " + name)
    selection = _check_selection(operation)
    execution = _check_execution(selection)
    if execution is None:
        policy = {"resident_profile_id": declaration["resident_profiles"][0]["descriptor"]["profile_id"]}
    else:
        declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
        chosen = _check_profile(declarations, name, load_deployment(selection["deployment"]), execution)
        policy = declarations["coordinator"]["preparation"]["profiles"][chosen]
    from .self_tests import selected_check_profile

    profile = selected_check_profile(policy, thaw_plain_data(observed.value), execution)
    successors = _gpu_check_successors(operation, name)
    result = operation.call(name, "gpu-capability", profile=profile, deadline=deadline,
        **({"_step_key": successors[-1]["step_key"]} if successors else {}),
        **({"execution": execution.to_dict()} if execution is not None else {}))
    operation.check_observations[name + ":gpu-capability"] = result
    if result.get("outcome") != "passed":
        raise QueueConflictError("GPU capability failed: " + str(result))


def _gpu_checks_to_observe(operation, names):
    outstanding, passed = [], []
    for name in names:
        successors = _gpu_check_successors(operation, name)
        key = successors[-1]["step_key"] if successors else name + "-gpu-capability"
        path = operation.receipts / key / "receipt.json"
        receipt = read(path) if path.is_file() else None
        if receipt is None or receipt.get("outcome") != "passed":
            outstanding.append(name)
        else:
            operation.check_observations[name + ":gpu-capability"] = receipt
            passed.append(name)
    return outstanding, passed


def _observe_gpu_checks(operation, declarations, names, deadline, *, final=False):
    errors = []
    for index, name in enumerate(names):
        now = time.monotonic()
        if now >= deadline:
            errors.append(_Waiting("GPU capability profile confirmation pending: " + name))
            break
        step_end = deadline if final else now + (deadline - now) / (1 + len(names) - index)
        try:
            _gpu_capability(operation, name, declarations[name], step_end)
        except (sshops.SshUnavailable, _Waiting, CoordinatorClientError, QueueConflictError) as exc:
            errors.append(exc)
    return errors


def _authorize_check_slots(operation, slots, attempts, deadline, save_attempts):
    active, errors = [], []
    if not slots:
        return active, errors
    # The grant mutation is revision-conditional. Preserve a single writer.
    # Existing grants are confirmed from the live owned gate in one read.
    now = time.monotonic()
    setup_end = now + max(0, deadline - now) / 2
    gate = operation.gate(deadline=setup_end)
    missing = sum(key not in gate["checks"] for key in slots)
    grant_uncertain = False
    # Recover a pending revision-conditional request before authorizing
    # another check. An unseen grant may already have consumed the revision.
    ordered = sorted(slots, key=lambda key: not (
        operation.directory / "steps" / ("authorize-" + key) / "intent.json"
    ).is_file())
    for identity in ordered:
        slot, name, check = slots[identity]
        grant = gate["checks"].get(identity)
        if grant is not None and slot in attempts:
            if grant != attempts[slot][-1]["authorization"]:
                raise QueueConflictError("maintenance check authorization changed: " + identity)
            active.append(identity)
            continue
        now = time.monotonic()
        step_end = now + max(0, setup_end - now) / max(1, missing)
        missing -= 1
        if now >= step_end or grant_uncertain:
            continue
        try:
            if slot not in attempts:
                attempts[slot] = [_prepare_attempt(operation, name, check, identity,
                    deadline=step_end, revision=gate["revision"])]
                save_attempts()
            authorization = attempts[slot][-1]["authorization"]
            if grant is None:
                # An uncertain or lost grant reply fences later writes to
                # this gate revision. Already confirmed grants can proceed.
                # This mutation serializes all grants at one gate revision.
                # Rechecking protected inputs is part of the mutation. Give it
                # the remaining grant-phase budget; a per-host preparation
                # slice can already have expired before the RPC can start.
                grant_uncertain = True
                result = operation.maintenance("authorize-" + identity, "authorize",
                    authorization, deadline=setup_end, revision=gate["revision"])
                if (result["gate"]["revision"] <= gate["revision"]
                        or result["gate"]["checks"].get(identity) != authorization):
                    raise QueueConflictError("maintenance check grant changed: " + identity)
                gate["revision"] = result["gate"]["revision"]
                grant_uncertain = False
            elif authorization != grant:
                raise QueueConflictError("maintenance check authorization changed: " + identity)
            active.append(identity)
        except (_Waiting, CoordinatorClientError) as exc:
            errors.append(exc)

    return active, errors


def _transferred_bytes(observation):
    total = 0
    for row in observation.get("checks", {}).values():
        transfer = row.get("transfer") or {}
        total += transfer.get("received_bytes", 0) + transfer.get("reused_bytes", 0)
    return total


def _check_observation(identity, result):
    rows = {}
    for name, row in result.get("checks", {}).items():
        if row["outcome"] == "not_requested":
            continue
        observation = {key: row[key] for key in (
            "operation_id", "outcome", "code", "transfer", "native_result_observed_at",
            "collection_started_at", "artifact_verified_at",
        ) if key in row}
        native = row.get("native") or {}
        admission = native.get("admission")
        if row["outcome"] == "waiting":
            if admission and admission["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
                observation["wait_for"] = {"admission_id": admission["admission_id"], "revision": admission["revision"]}
            elif admission is None and (native.get("operation") or {}).get("state") in {"pending", "applying"}:
                observation["wait_for"] = {"operation_id": native["operation_id"]}
        rows[name] = observation
    return {"operation_id": identity, "outcome": result["outcome"], "checks": rows}


def _run_checks(operation):
    deadline = cast(float, sshops.observer_end(time.monotonic() + operation.intent["timeout_seconds"]))
    phase(operation, "checking")
    operation.check_observations = {}
    attempts = _attempts(operation)
    deferred = _deferred_checks(operation).get("agents", ())
    declarations = operation.intent.get("target_declarations", operation.intent["declarations"])
    slots, capabilities = {}, []
    for name, declaration in declarations.items():
        if name == "coordinator" or name not in operation.intent["agents"] or name in deferred:
            continue
        for check in _check_kinds(operation, name, declaration):
            if check == "gpu" and operation.intent.get("gpu_qualification") == "nonexclusive":
                capabilities.append(name)
                operation.check_observations[name + ":gpu-capability"] = {"outcome": "waiting"}
                continue
            slot = name + ":" + check
            attempt = attempts[slot][-1] if slot in attempts else {}
            identity = attempt.get("operation_id") or _check_identity(operation, name, check)
            slots[identity] = (slot, name, check)
            operation.check_observations[identity] = attempt.get("last_observation") or {
                "outcome": "waiting", "operation_id": identity,
                "checks": attempt.get("dispatch_checks", {check: {
                    "operation_id": identity, "disposition": "pending", "outcome": "waiting",
                }}),
            }

    def save_attempts():
        atomic(operation.directory / "checks.json", attempts)

    active, errors = _authorize_check_slots(operation, slots, attempts, deadline, save_attempts)
    inventory = operation.inventory
    records = {row[-1]["operation_id"]: row[-1] for row in attempts.values()}

    following = getattr(getattr(operation, "observation", None), "follow", False)

    def advance(identity, kind, step_end) -> dict[str, Any]:
        remaining = step_end - time.monotonic()
        if remaining <= 0:
            return {"operation_id": identity, "outcome": "waiting", "code": "deadline_exceeded"}
        return self_test(inventory, operation_id=identity, timeout_seconds=remaining,
                         _dispatch_only=(kind == "dispatch"), _wait=False, _collect=(kind == "transfer"))

    def steps(selected, dispatch, end):
        def next_step(key):
            rows = (records[key].get("last_observation") or {}).get("checks", {}).values()
            codes = {row.get("code") for row in rows}
            if "publication_available" in codes:
                return "transfer"
            if "publication_verified" in codes:
                return "observe"
            return None

        # Continuing a bounded transfer still reselects and rebinds its output.
        # Follow starts with short observations to pick up detached receipts.
        transfers = {key for key in selected if not dispatch and not following and (
            next_step(key) == "transfer" or _transferred_bytes(records[key].get("last_observation") or {})
        )}
        return completed_steps(
            operation.directory, records, selected, dispatch=dispatch, transfers=transfers,
            deadline=end, advance=advance, started=save_attempts,
            next_step=None if dispatch else next_step, detach_transfers=following,
        )

    # Dispatch gets the first opportunity for every selected slot. Accepted and
    # rejected receipts belong to an immutable attempt, and survive detachment.
    dispatch = [key for key in active if not records[key].get("dispatch_settled")]
    dispatched = set()
    now = time.monotonic()
    dispatch_end = now + max(0, deadline - now) / 2
    for identity, future in steps(dispatch, True, dispatch_end):
        try:
            dispatch_result = future.result()
        except Exception as exc:
            errors.append(exc)
            continue
        dispatched.add(identity)
        rows = dispatch_result.get("checks", {})
        records[identity]["dispatch_checks"] = rows
        records[identity]["dispatch_settled"] = bool(rows) and all(
            row.get("disposition") in {"accepted", "rejected"} for row in rows.values()
        )
        if not records[identity].get("last_observation"):
            operation.check_observations[identity]["checks"] = rows
        save_attempts()
    # The native dispatch pass has run. Bound direct GPU reads and the
    # receipt lookup/replay by the same deadline, leaving time for native
    # observations even if a capability host uses its entire share.
    outstanding_gpu, retained_gpu = _gpu_checks_to_observe(operation, capabilities)
    errors.extend(_observe_gpu_checks(operation, declarations, outstanding_gpu, deadline))

    first_pass = all(records[key].get("dispatch_turns") for key in dispatch)
    eligible = [key for key in active if first_pass and (key not in dispatch or key in dispatched)]
    waiting = set(slots) - set(eligible)
    failures = []
    for identity in eligible:
        if not records[identity].get("passed_this_round"):
            waiting.add(identity)
    # Recheck passed predecessors against current authorization and output bindings
    # before restoration, including receipts written by older controllers.
    retained = [key for key in eligible if key not in waiting]
    selected = [key for key in eligible if key in waiting]
    if not waiting:
        selected, retained = retained, []
        waiting.update(selected)
    while selected and time.monotonic() < deadline:
        progressed = False
        for identity, future in steps(selected, False, deadline):
            try:
                result = future.result()
            except Exception as exc:
                errors.append(exc)
                continue
            atomic(operation.directory / (identity + "-result.json"), result)
            observation = _check_observation(identity, result)
            previous = records[identity].get("last_observation") or {}
            if result["outcome"] == "waiting" and _transferred_bytes(observation) > _transferred_bytes(previous):
                progressed = True
            records[identity]["last_observation"] = observation
            operation.check_observations[identity] = observation
            if result["outcome"] == "passed":
                records[identity]["passed_this_round"] = True
            else:
                records[identity].pop("passed_this_round", None)
            for field, event in (("native_result_observed_at", "last_native_check_acknowledged"),
                                 ("artifact_verified_at", "last_artifact_verified")):
                if all(any(row.get(field) for row in operation.check_observations[key].get("checks", {}).values())
                       for key in slots):
                    milestone(operation, event)
            save_attempts()
            if result["outcome"] in {"failed", "unsupported"}:
                failures.append((identity, result["outcome"]))
            elif result["outcome"] == "passed":
                waiting.discard(identity)
        # Every eligible check received a bounded opportunity. A transfer
        # with new retained bytes can use the same caller's remaining budget.
        if not waiting and retained and not failures and not errors:
            selected, retained = retained, []
            waiting.update(selected)
            continue
        if not progressed or failures or errors or following:
            break
        selected = [key for key in eligible if key in waiting]
    if failures:
        reason(operation, "check_failed" if any(outcome == "failed" for _, outcome in failures)
               else "native_refusal")
        raise QueueConflictError(
            "; ".join("check " + identity + " " + outcome for identity, outcome in failures)
            + "; explicit operation retry-check required"
        )
    if errors:
        raise errors[0]
    waiting.update(name + ":gpu-capability" for name in capabilities
                   if operation.check_observations[name + ":gpu-capability"]["outcome"] != "passed")
    if waiting:
        raise _Waiting("checks pending: " + ", ".join(sorted(waiting)))
    # A passed capability is an immutable result throughout download. Confirm
    # its live profile and exact request once at the restoration boundary.
    confirmations = _observe_gpu_checks(operation, declarations, retained_gpu, deadline, final=True)
    if confirmations:
        raise confirmations[0]
    operation.settled(deadline=deadline)
    # Fresh invocations after settlement reobserve the checks. A partial
    # round across detachments retains exact, verified predecessors.
    for key in active:
        records[key].pop("passed_this_round", None)
    if active:
        save_attempts()


def _release_publication_hold(operation):
    if not operation.intent["kind"].endswith("-publication"):
        raise QueueConflictError("operation has no client publication hold")
    path = operation.directory / "restoring.json"
    if not path.exists():
        raise QueueConflictError("native checks have not completed")
    receipt = read(path)
    if receipt.get("intent_digest") != digest(operation.intent):
        raise QueueConflictError("publication checkpoint intent changed")
    if receipt.get("publication_released"):
        return
    operation.gate()
    operation.settled()
    # External client publication can change unused host-default keys, but must
    # leave every composed native role and all other pinned inputs unchanged.
    updates_path = operation.directory / "accepted-inputs.json"
    updates = read(updates_path) if updates_path.exists() else {}
    environments = {
        row["env_file"]: sshops._file_hash(Path(row["env_file"]))
        for row in operation.intent["hosts"].values() if row["env_file"] is not None
    }
    operation.recheck(environments)
    atomic(updates_path, {**updates, **environments})
    operation.recheck()
    atomic(path, {**receipt, "publication_released": True})


def _slurm_binding(operation, name):
    profiles = operation.intent.get("slurm_profiles", {}).get(name)
    return {"slurm_profiles": profiles} if profiles else {}


def _slurm_handoff(operation):
    from ._slurm_retirement import recovery_consumers

    if not operation.intent.get("slurm_roles"):
        return {}
    record = operation.directory / "release-retirement.json"
    if record.exists():
        return read(record)
    operation.gate()
    operation.settled()
    checks = set(operation.gate()["checks"])
    authorized = {attempt["operation_id"] for history in _attempts(operation).values() for attempt in history}
    if checks - authorized:
        raise QueueConflictError("maintenance gate contains a check outside this upgrade")
    for identity in sorted(checks):
        operation.maintenance("revoke-" + identity, "revoke", identity)
    from ._slurm_upgrade import _strings

    # An idle resident worker or a peer Slurm helper can still launch from the
    # source release. Bind every role's authored paths before any host retires.
    paths = {path for name in operation.intent["hosts"]
             for path in _strings(operation.accepted_declaration(name)) if Path(path).is_absolute()}
    unattributed_jobs = []
    for name, fact in operation.host_observations(operation.intent["slurm_roles"], "upgrade-settlement",
                                                  include_pending_poll=False):
        if fact["availability"] != "available" or not fact["value"].get("settled"):
            raise _Waiting("Slurm settlement pending before retirement: " + name, "settlement_pending")
        slurm = fact["value"]["slurm"]
        paths.update(path for profile in slurm["profiles"] for path in profile["paths"])
        unattributed_jobs.extend(slurm["other_jobs"])
    consumers = recovery_consumers(operation)
    facts = operation.call_many([
        (name, "upgrade-retire-environment", {
            "source_release": row["source_release"], "expected_root_id": row["expected_root_id"],
            "source_descriptor_name": operation.intent["slurm_source_descriptor_name"],
            "recovery_consumers": consumers, "role_paths": sorted(paths),
            "unattributed_jobs": unattributed_jobs, "deferred_agents": _deferred_checks(operation).get("agents", []),
            **_slurm_binding(operation, name),
        }) for name, row in operation.intent["hosts"].items()
    ])
    atomic(record, facts)
    return facts


def _restore(operation, *, abort=False):
    if not abort and operation.intent.get("slurm_roles"):
        _slurm_handoff(operation)
    if not abort and operation.intent["kind"].endswith("-publication"):
        receipt = read(operation.directory / "restoring.json")
        if receipt.get("intent_digest") != digest(operation.intent):
            raise QueueConflictError("publication checkpoint intent changed")
        if not receipt.get("publication_released"):
            operation.gate()
            raise _Waiting("qualified native checks await client publication", "publication_pending")
    if not abort:
        from ._inventory_publication import publish

        publish(operation)
    phase(operation, "restoring")
    def restore_agent(name, original):
        keys = [name + "-drain", name + "-checks-capacity"]
        predecessor = (original.get("control") or {}).get("operation_id")
        changed = False
        for key in keys:
            path = operation.receipts / key / "intent.json"
            if path.exists():
                request = read(path)
                predecessor = yield from operation.policy_steps(
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
                yield from operation.verify_policy_steps(name, predecessor)
            else:
                key = name + ("-abort-restore" if abort else "-restore")
                restored = yield from operation.policy_steps(
                    name, key, "drain" if original["drained"] else "resume", predecessor
                )
                yield from operation.verify_policy_steps(name, restored)
    agents = operation.intent.get("restore_agents", operation.intent["agents"])
    pending = []
    def restore_one(name, original):
        try:
            yield from restore_agent(name, original)
        except _Waiting as exc:
            pending.append(exc)

    flows = {name: restore_one(name, original) for name, original in agents.items()}
    sshops.host_steps(operation.directory, flows, operation.deadline, sshops.SshUnavailable)
    if pending:
        raise pending[0]
    if (operation.receipts / "open" / "intent.json").exists():
        operation.maintenance("open", "open")
        return
    # Abort restores administrative policy while admitted ordinary work continues.
    # Successful replacement still requires every native effect to settle.
    if not abort:
        operation.settled()
    for identity in list(operation.gate()["checks"]):
        operation.maintenance("revoke-" + identity, "revoke", identity)
    if not operation.intent.get("preserve_maintenance_gate"):
        operation.maintenance("open", "open")


def _independent_policies(operation, requests):
    """Dispatch ordinary per-agent controls without waiting on the first agent.

    Native acceptance and exact predecessor conditions remain authoritative.
    Promotions require global settlement and must never use this helper.
    """
    pending = []
    def apply(name, key, kind, predecessor):
        if kind not in {"drain", "resume"}:
            raise QueueConflictError("independent policies require drain or resume")
        try:
            accepted = yield from operation.policy_steps(name, key, kind, predecessor)
            yield from operation.verify_policy_steps(name, accepted)
        except _Waiting as exc:
            pending.append(exc)

    flows = {name: apply(name, key, kind, predecessor) for name, key, kind, predecessor in requests}
    sshops.host_steps(operation.directory, flows, operation.deadline, sshops.SshUnavailable)
    if pending:
        raise pending[0]


def _continue(operation):
    if (operation.directory / "runtime-candidate-repair" / "intent.json").exists():
        from .runtime_candidate_repair import continue_repair
        return continue_repair(operation)
    if (operation.directory / "workload-repair" / "intent.json").exists():
        from .runtime_workload_repair import continue_repair
        return continue_repair(operation)
    if operation.intent.get("runtime_retirement"):
        from .runtime_retirement import continue_upgrade
        return continue_upgrade(operation)
    if operation.intent.get("kind") in {"workload-upgrade", "workload-upgrade-publication", "configuration-retirement", "configuration-retirement-publication", "container-policy-addition", "container-policy-addition-publication", "publication-budget-increase", "publication-budget-increase-publication"}:
        from .workload_upgrades import continue_upgrade
        return continue_upgrade(operation)
    if (operation.directory / "complete.json").exists():
        return read(operation.directory / "complete.json")
    if operation.intent["kind"].endswith("-publication") and (operation.directory / "restoring.json").exists():
        _restore(operation)
        return _complete_runtime(operation)
    operation.recheck()
    irreversible = operation.directory / "irreversible.json"
    recovery = operation.intent.get("recover_retained_results", False)
    recovery_path = operation.directory / "retained-results.json"
    if not irreversible.exists():
        phase(operation, "preparing")
        _capable(operation.operator)
        sshops._install_candidates(operation)
        operation.probes()
        _preflight_checks(operation)
        if "maintenance_binding" in operation.intent:
            operation.gate()
        else:
            operation.maintenance("close", "close")
        if not recovery:
            operation.settled()
        phase(operation, "draining")
        _independent_policies(operation, [
            (name, name + "-drain", "drain",
             (agent.get("control") or {}).get("operation_id"))
            for name, agent in operation.intent["agents"].items()
        ])
        if recovery:
            results = []
            for name, fact in operation.host_observations(operation.intent["agents"], "upgrade-result-recovery"):
                if fact["availability"] != "available" or not fact["value"].get("recoverable"):
                    raise _Waiting("host result recovery: " + name + ": " + str(fact), "settlement_pending")
                results.extend(fact["value"]["results"])
            fact = operation.host_observe(
                "coordinator", "upgrade-result-recovery", recovery_results=results,
            )
            if fact["availability"] != "available" or not fact["value"].get("recoverable"):
                raise _Waiting("coordinator result recovery: " + str(fact), "settlement_pending")
            atomic(recovery_path, {"results": results})
        else:
            operation.settled()
            for name, fact in operation.host_observations(operation.intent["hosts"], "upgrade-settlement"):
                if fact["availability"] != "available" or not fact["value"].get("settled"):
                    raise _Waiting("host native settlement: " + name + ": " + str(fact), "settlement_pending")
        atomic(
            irreversible,
            {"step": "stop-replace", "intent_digest": digest(operation.intent)},
        )
    phase(operation, "replacing")
    recovery_options = {"recovery_results": read(recovery_path)["results"]} if recovery else {}
    # Host receipts retain exact stop/replace/start requests across coordinator downtime.
    def stop_arguments(name):
        row = operation.intent["hosts"][name]
        return dict(
            expected_root_id=row["expected_root_id"],
            descriptor_name=Path(operation.intent["target_path"]).name,
            required_capabilities=list(REQUIRED_CAPABILITIES),
            images=read(operation.directory / (name + "-candidate.json"))["images"],
            **recovery_options,
            **_slurm_binding(operation, name),
        )

    def replacement_arguments(name):
        row = operation.intent["hosts"][name]
        return dict(
            expected_root_id=row["expected_root_id"],
            source_release=row["source_release"],
            coordinator_id=operation.intent["check_selection"]["coordinator_id"],
            descriptor_name=Path(operation.intent["target_path"]).name,
            required_capabilities=list(REQUIRED_CAPABILITIES),
            images=read(operation.directory / (name + "-candidate.json"))["images"],
            **recovery_options,
            **_slurm_binding(operation, name),
        )
    operation.call_many([
        (name, "upgrade-stop", stop_arguments(name))
        for name in operation.intent["agents"]
    ])
    operation.call("coordinator", "upgrade-stop", **stop_arguments("coordinator"))
    operation.call("coordinator", "upgrade-replace", **replacement_arguments("coordinator"))
    operation.call_many([
        (name, "upgrade-replace", replacement_arguments(name))
        for name in operation.intent["agents"]
    ])
    milestone(operation, "services_replaced")
    _capable(operation.operator)
    if not (operation.receipts / "open" / "intent.json").exists():
        operation.gate()
    operation.probes()
    restoring = operation.directory / "restoring.json"
    if not restoring.exists():
        capacity_controls = []
        if recovery:
            pending = [name for name in operation.intent["agents"]
                       if not (operation.receipts / (name + "-checks-capacity") / "intent.json").exists()]
            for name, fact in operation.host_observations(pending, "upgrade-settlement", include_pending_poll=False):
                if fact["availability"] != "available" or not fact["value"].get("settled"):
                    raise _Waiting("retained result replay: " + name, "settlement_pending")
        for name in operation.intent["agents"]:
            predecessor = operation.intent["operation_id"] + "-" + name + "-drain"
            capacity_controls.append((name, name + "-checks-capacity", "resume", predecessor))
        _independent_policies(operation, capacity_controls)
        if recovery:
            operation.settled()
        _run_checks(operation)
        atomic(restoring, {"intent_digest": digest(operation.intent)})
    _restore(operation)
    return _complete_runtime(operation)


def _complete_runtime(operation):
    result = {
        "state": "complete",
        "release": operation.intent["release"],
        "checks": _attempts(operation),
        **_qualification_result(operation),
        **({"retirement": _slurm_handoff(operation)} if operation.intent.get("slurm_roles") else {}),
        "deployment": _check_selection(operation)["deployment"],
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
    recover_retained_results=False,
    hold_admission=False,
    maintenance_id=None,
    workload_profile=None,
    retire_configuration=False,
    add_container_policies=False,
    increase_publication_budgets=False,
    image=None,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    check_execution=None,
    env_file=None,
    apply=False,
    timeout_seconds: float = 120,
    action="resume",
    failed_check=None,
    new_check=None,
    failed_control=None,
    new_control=None,
    defer_agents=None,
    defer_reason=None,
    repair_agent_id=None,
    progress: ProgressSink | None = None,
    follow: bool = False,
):
    """Preview/apply or continue an immutable upgrade without cancelling work.

    ``progress`` optionally receives bounded diagnostic snapshots on a daemon
    reporting thread. Durations are local monotonic seconds for this invocation;
    observed admission closure is partial and is not service downtime. Callback
    failures/backpressure lose diagnostics without changing native execution.
    Following an apply/resume advances the same operation until completion, an
    operator decision, or the overall timeout. The writer is available between
    advances. Preview and actions other than apply/resume/abort/retry-check/retry-control
    do not support progress. See docs/fleet.md for the diagnostic stream contract.
    """
    options = locals().copy()
    del options["progress"], options["follow"]
    if follow and (operation_id is None or action != "resume"):
        raise QueueConfigError("follow requires upgrade apply or resume")
    if progress is not None and ((not apply and operation_id is None) or
                                 (not apply and action not in {"resume", "abort", "retry-check", "retry-control"})):
        raise QueueConfigError("progress requires an applied or retained upgrade")
    observation = Observation(progress, "apply" if apply else action)
    observation.follow = follow
    try:
        with sshops.observer_budget(timeout_seconds), recording(), measure("upgrade_continuation") as timing:
            cursor = 0
            deadline = cast(float, sshops.observer_end())
            while True:
                observation.reason = "none"
                result = _upgrade(**options, observation=observation)
                if (not follow or result.get("outcome") != "waiting" or result.get("publication_ready")
                        or time.monotonic() >= deadline):
                    break
                # _upgrade has closed all native handles and released the writer.
                pending = [(identity, row) for identity, check in result.get("check_observations", {}).items()
                           for row in check.get("checks", {}).values() if row.get("outcome") == "waiting"]
                if any(row.get("code") in {"unauthorized", "invalid_request", "conflict"} for _, row in pending):
                    break
                targets = [(identity, row["wait_for"]) for identity, row in pending if row.get("wait_for")]
                if targets:
                    cursor %= len(targets)
                cursor += wait_for_checks(
                    sshops._directory(inventory, operation_id), targets[cursor:] + targets[:cursor],
                    min(deadline, time.monotonic() + 2.0), partial(_wait_check_change, inventory),
                )
                if time.monotonic() >= deadline:
                    break
                options = {"inventory": inventory, "operation_id": operation_id, "timeout_seconds": timeout_seconds}
            if result.get("outcome") == "waiting":
                timing["outcome"] = "waiting"
            elif result.get("outcome") in {"blocked", "failed"}:
                timing["outcome"] = "error"
    except BaseException as exc:
        code = _reason_code(exc)
        observation.finish("interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "error", code)
        raise
    observation.finish(result.get("outcome", "complete"))
    return result


def _upgrade(
    inventory,
    *,
    operation_id=None,
    runtime_release=None,
    recover_retained_results=False,
    hold_admission=False,
    maintenance_id=None,
    workload_profile=None,
    retire_configuration=False,
    add_container_policies=False,
    increase_publication_budgets=False,
    image=None,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    check_execution=None,
    env_file=None,
    apply=False,
    timeout_seconds: float = 120,
    action="resume",
    failed_check=None,
    new_check=None,
    failed_control=None,
    new_control=None,
    defer_agents=None,
    defer_reason=None,
    repair_agent_id=None,
    observation,
) -> dict[str, Any]:
    """Preview/apply or continue one immutable service upgrade; never cancel work."""
    if apply:
        observation.kind = "publication-budget-increase" if increase_publication_budgets else "container-policy-addition" if add_container_policies else "configuration-retirement" if retire_configuration else ("workload-upgrade" if workload_profile is not None else "runtime-upgrade")
    _environment_files(inventory, env_file)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise QueueConfigError("timeout must be positive and finite")
    if action == "defer-checks" and not defer_agents:
        raise QueueConfigError("defer-checks requires --agent-id and --reason")
    if defer_reason is not None and not defer_agents:
        raise QueueConfigError("qualification reason requires deferred agents")
    if defer_agents is not None and not apply and operation_id is None:
        raise QueueConfigError("qualification exceptions require an applied upgrade")
    if runtime_release is not None and (workload_profile is not None or image is not None or (workload_inventory is not None and not retire_configuration)):
        raise QueueConfigError("service and workload targets are mutually exclusive")
    if retire_configuration and (workload_profile is not None or image is not None or recover_retained_results):
        raise QueueConfigError("configuration retirement cannot select resident image promotion or result recovery")
    if add_container_policies and (retire_configuration or runtime_release is not None or workload_profile is not None or image is not None or recover_retained_results):
        raise QueueConfigError("container policy addition must be separate from runtime, retirement and image changes")
    if increase_publication_budgets and (retire_configuration or add_container_policies or runtime_release is not None or workload_profile is not None or image is not None or recover_retained_results):
        raise QueueConfigError("publication budget increase must be separate from runtime, retirement, policy addition and image changes")
    if apply and not (retire_configuration or add_container_policies or increase_publication_budgets) and runtime_release is None and (workload_profile is None or image is None):
        raise QueueConfigError("apply requires --runtime-release or --workload-profile and --image")
    if not apply and operation_id is None:
        return preview(
            inventory,
            runtime_release=runtime_release,
            recover_retained_results=recover_retained_results,
            hold_admission=hold_admission,
            maintenance_id=maintenance_id,
            workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
            retire_configuration=retire_configuration, add_container_policies=add_container_policies,
            increase_publication_budgets=increase_publication_budgets,
            deployment=deployment,
            connection=connection,
            config=config,
            check_execution=check_execution,
            env_file=env_file,
        )
    if operation_id is None:
        raise QueueConfigError("apply requires --operation-id")
    directory = sshops._directory(inventory, operation_id)
    if not (directory / "intent.json").exists() and not apply:
        raise QueueConfigError("unknown upgrade operation")
    protected_directory(directory)
    bind_directory(directory)
    with (directory / "writer.lock").open("a") as writer:
        try:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueConflictError("operation already has an active writer") from exc
        path = directory / "intent.json"
        prepared_plan = None
        if not path.exists():
            plan = preview(
                inventory,
                runtime_release=runtime_release,
                recover_retained_results=recover_retained_results,
                hold_admission=hold_admission,
            maintenance_id=maintenance_id,
                workload_profile=workload_profile, image=image, workload_inventory=workload_inventory,
                retire_configuration=retire_configuration, add_container_policies=add_container_policies,
                increase_publication_budgets=increase_publication_budgets,
                deployment=deployment,
                connection=connection,
                config=config,
                check_execution=check_execution,
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
                "recover_retained_results": recover_retained_results,
                "gpu_qualification": inventory.gpu_qualification,
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
            if plan.get("slurm"):
                if _check_execution(plan["checks"]) is None:
                    raise QueueConfigError("Slurm qualification requires an exact submitted --check-execution image")
                for name in plan["slurm"]:
                    if name == "coordinator":
                        continue
                    selection = load_deployment(plan["checks"]["deployment"])
                    chosen = _check_profile(plan["declarations"], name, selection, _check_execution(plan["checks"]))
                    if not plan["declarations"]["coordinator"]["preparation"]["profiles"][chosen].get("execution_route"):
                        raise QueueConfigError("Slurm qualification requires a Slurm preparation and workload route")
                intent["slurm_roles"] = list(plan["slurm"])
                intent["slurm_source_descriptor_name"] = inventory.runtime_release.name
                intent["slurm_profiles"] = {name: evidence["profiles"] for name, evidence in plan["slurm"].items()}
                if any(evidence["status"] == "unavailable" for evidence in plan["slurm"].values()):
                    raise QueueConflictError("Slurm preview evidence unavailable; restore scheduler and journal visibility")
            if workload_profile is not None or retire_configuration or add_container_policies or increase_publication_budgets:
                from .workload_upgrades import bind_intent
                intent = bind_intent(intent, plan, directory)
            if runtime_release is not None:
                from ._inventory_publication import bind

                intent["inventory_publication"] = bind(
                    inventory, target, inputs[str(inventory.path)]
                )
            if plan.get("maintenance_binding") is not None:
                intent["maintenance_binding"] = plan["maintenance_binding"]
                intent["preserve_maintenance_gate"] = True
            if hold_admission:
                intent["kind"] += "-publication"
            atomic(path, intent)
            prepared_plan = plan
        intent = read(path)
        if intent.get("kind") not in {"runtime-upgrade", "workload-upgrade", "runtime-upgrade-publication", "workload-upgrade-publication", "configuration-retirement", "configuration-retirement-publication", "container-policy-addition", "container-policy-addition-publication", "publication-budget-increase", "publication-budget-increase-publication"}:
            raise QueueConflictError("operation belongs to another kind")
        observation.kind = intent["kind"].removesuffix("-publication")
        if action not in {"repair-runtime-candidate", "repair-runtime"} and runtime_release is not None and Path(runtime_release).resolve() != Path(
            intent["target_path"]
        ):
            raise QueueConflictError("upgrade target intent changed")
        if action != "repair-workload" and workload_profile is not None and (intent.get("workload_profile") != workload_profile or image is None or intent.get("image") != str(Path(image).resolve())):
            raise QueueConflictError("workload target intent changed")
        if action != "repair-workload" and workload_profile is not None and intent.get("workload_inventory") != (
            None if workload_inventory is None else str(Path(workload_inventory).resolve())
        ):
            raise QueueConflictError("workload inventory intent changed")
        if apply:
            if maintenance_id != (intent.get("maintenance_binding", {}).get("operation_id")
                    if intent.get("preserve_maintenance_gate") else None):
                raise QueueConflictError("existing maintenance selection changed")
            if bool(intent.get("increase_publication_budgets")) != increase_publication_budgets:
                raise QueueConflictError("publication budget increase intent changed")
            if increase_publication_budgets and (workload_inventory is None or intent["workload_inventory"] != str(Path(workload_inventory).resolve())):
                raise QueueConflictError("publication budget increase candidate inventory changed")
            if bool(intent.get("add_container_policies")) != add_container_policies:
                raise QueueConflictError("container policy addition intent changed")
            if add_container_policies and (workload_inventory is None or intent["workload_inventory"] != str(Path(workload_inventory).resolve())):
                raise QueueConflictError("container policy addition candidate inventory changed")
            if bool(intent.get("retire_configuration")) != retire_configuration:
                raise QueueConflictError("configuration retirement intent changed")
            if retire_configuration and (workload_inventory is None or intent["workload_inventory"] != str(Path(workload_inventory).resolve())):
                raise QueueConflictError("configuration retirement candidate inventory changed")
            if intent["kind"].endswith("-publication") != hold_admission:
                raise QueueConflictError("publication hold intent changed")
            if bool(intent.get("recover_retained_results")) != recover_retained_results:
                raise QueueConflictError("retained-result recovery intent changed")
            selected = _checks(inventory, deployment, connection, config, check_execution)
            if (
                selected != intent.get("original_check_selection", intent["check_selection"])
                or (None if env_file is None else str(Path(env_file).resolve()))
                != intent["env_file"]
            ):
                raise QueueConflictError("upgrade check or environment intent changed")
        if intent.get("runtime_retirement"):
            from .runtime_retirement import RuntimeRetirementUpgrade
            operation = RuntimeRetirementUpgrade(inventory, directory, intent, observation)
        elif intent["kind"] in {"workload-upgrade", "workload-upgrade-publication", "configuration-retirement", "configuration-retirement-publication", "container-policy-addition", "container-policy-addition-publication", "publication-budget-increase", "publication-budget-increase-publication"}:
            from .workload_upgrades import WorkloadUpgrade
            operation = WorkloadUpgrade(inventory, directory, intent, observation)
            operation._preview_qualification = prepared_plan
        else:
            operation = _Upgrade(inventory, directory, intent, observation)
        observation.end_preparation()
        phase(operation, "recovering")
        result: dict[str, Any]
        try:
            if defer_agents is not None:
                _bind_deferred_checks(operation, defer_agents, defer_reason)
            if (directory / "aborted.json").exists():
                result = {"state": "aborted"}
            elif action == "repair-gpu-policy":
                from .gpu_policy_repair import repair
                result = repair(operation, agent_id=repair_agent_id)
            elif action == "repair-runtime-candidate":
                from .runtime_candidate_repair import repair_candidate
                result = repair_candidate(operation, runtime_release=runtime_release)
            elif (directory / "runtime-candidate-repair" / "intent.json").exists():
                from .runtime_candidate_repair import continue_repair
                result = continue_repair(operation, action=action, runtime_release=runtime_release, failed_check=failed_check,
                                         new_check=new_check, failed_control=failed_control,
                                         new_control=new_control)
            elif action == "repair-runtime":
                from .runtime_candidate_repair import repair_candidate
                result = repair_candidate(operation, runtime_release=runtime_release, activated=True)
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
                    elif intent.get("preserve_maintenance_gate"):
                        operation.gate()
                        _restore(operation, abort=True)
                    atomic(directory / "aborted.json", {"state": "aborted"})
                    result = {"state": "aborted"}
            elif action == "release-admission":
                _release_publication_hold(operation)
                result = _continue(operation)
            elif action == "repair-check-selection":
                result = _repair_check_selection(operation, deployment)
            elif action == "repair-workload":
                from .runtime_workload_repair import repair_workload
                result = repair_workload(operation, workload_profile=workload_profile,
                                         image=image, workload_inventory=workload_inventory)
            elif action in {"retry-check", "retry-control"} and (directory / "workload-repair" / "intent.json").exists():
                from .runtime_workload_repair import continue_repair
                result = continue_repair(operation, action=action, failed_check=failed_check,
                                         new_check=new_check, failed_control=failed_control,
                                         new_control=new_control)
            elif action == "retry-check":
                result = _retry_check(operation, failed_check, new_check)
            elif action == "retry-control":
                result = _retry_control(operation, failed_control, new_control)
            else:
                result = _continue(operation)
        except (_Waiting, sshops.SshUnavailable) as exc:
            observation.reason = _reason_code(exc)
            result = {"state": "waiting", "reason": str(exc)}
            if getattr(exc, "code", None) == "publication_pending":
                result.update(publication_ready=True, checks=getattr(operation, "continuation_checks", _attempts(operation)))
                if "image_sha256" in intent:
                    result["image_sha256"] = intent["image_sha256"]
        except CoordinatorClientError as exc:
            observation.reason = _reason_code(exc)
            result = {
                "state": "waiting"
                if exc.mutation_outcome == "unknown"
                or exc.code in {"unavailable", "deadline_exceeded"}
                else "blocked",
                "reason": exc.code,
                "native_error": exc.to_dict(),
            }
        except (QueueConfigError, QueueConflictError, OSError) as exc:
            if observation.reason == "none":
                observation.reason = _reason_code(exc)
            result = {"state": "blocked", "reason": str(exc)}
        finally:
            operation.close()
        result.update(_qualification_result(operation))
        result["check_observations"] = getattr(operation, "check_observations", {})
        result["reason_code"] = observation.reason
        atomic(directory / "result.json", result)
        return cast(dict[str, Any], sshops.operation_status(inventory, operation_id))


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


def _require_failed_check(operation, failed):
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


def _retry_check(operation, failed, successor):
    if not failed or not successor:
        raise QueueConfigError("retry-check requires --failed-check and --operation-id")
    sshops._directory(operation.inventory, successor)
    operation.recheck()
    gpu_retry = _retry_gpu_check(operation, failed, successor)
    if gpu_retry is not None:
        return gpu_retry
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
    operation.gate()
    operation.probes()
    _require_failed_check(operation, failed)
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


def _gpu_check_successors(operation, name):
    path = operation.receipts / (name + "-gpu-capability") / "successors.json"
    return read(path) if path.exists() else []


def _retry_gpu_check(operation, failed, successor):
    """Explicitly repeat a bounded nonexclusive probe under a new host identity.

    An uncertain prior probe may have computed its fixed matrix product. A new
    probe neither adopts its result nor changes a scheduler claim. Scheduled
    checks retain their stronger confirmed-terminal-failure retry requirement.
    """
    if operation.intent.get("gpu_qualification") != "nonexclusive":
        return None
    selected = []
    for name in operation.intent["agents"]:
        key = name + "-gpu-capability"
        path = operation.receipts / key / "intent.json"
        if not path.exists():
            continue
        original = read(path)
        rows = _gpu_check_successors(operation, name)
        identities = [original["request_id"], *(row["operation_id"] for row in rows)]
        if failed in identities:
            selected.append((name, key, original, rows))
    if not selected:
        return None
    if len(selected) != 1:
        raise QueueConflictError("GPU check identity is ambiguous")
    name, key, original, rows = selected[0]
    if rows and rows[-1]["operation_id"] == successor and rows[-1]["previous_check_id"] == failed:
        return _continue(operation)
    current = rows[-1]["operation_id"] if rows else original["request_id"]
    if current != failed:
        raise QueueConflictError("another successor already selects this GPU check")
    step = operation.receipts / (rows[-1]["step_key"] if rows else key)
    if not (step / "dispatch.json").exists():
        raise QueueConflictError("GPU check has not been dispatched")
    receipt = step / "receipt.json"
    if not receipt.exists():
        retained_request = read(step / "intent.json")
        observed = sshops.ssh(operation.intent["hosts"][name]["host"], {
            **retained_request, "action": "receipt",
        })
        if observed is not None:
            operation._finish_call(name, step, retained_request, observed)
    if receipt.exists() and read(receipt).get("outcome") == "passed":
        raise QueueConflictError("successful GPU capability check cannot be replaced")
    if successor == failed or any(
        read(path).get("request_id") == successor
        for path in operation.receipts.glob("*/intent.json")
    ) or any(
        row["operation_id"] == successor
        for agent in operation.intent["agents"]
        for row in _gpu_check_successors(operation, agent)
    ) or any(
        row["operation_id"] == successor
        for values in _attempts(operation).values() for row in values
    ):
        raise QueueConflictError("successor identity already belongs to another intent")
    operation.gate()
    operation.probes()
    operation.settled()
    step_key = key + "-" + successor
    if (operation.receipts / step_key).exists():
        raise QueueConflictError("successor host step already exists")
    atomic(operation.receipts / key / "successors.json", [*rows, {
        "operation_id": successor,
        "previous_check_id": failed,
        "step_key": step_key,
    }])
    return _continue(operation)
