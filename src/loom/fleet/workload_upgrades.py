"""Selected SIF promotion composed with native whole-fleet maintenance.

No service runtime is installed here. The accepted source release must already
supply native promotion/recovery on every consuming agent and coordinator.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, cast

from loom.deployment import load_deployment, export_connection_deployment
from loom.fleet._host import atomic, read, digest
from loom.fleet import ssh_operations as sshops
from loom.fleet import upgrades as maintenance
from loom.queue._profile_promotion import CAPABILITY
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.deployment import _load_protected_config
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.serialization import thaw_plain_data


def preview(
    inventory,
    *,
    workload_profile,
    image,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    env_file=None,
):
    """Qualify immutable bytes on all consumers, without maintenance mutations."""
    if not workload_profile or image is None:
        raise QueueConfigError(
            "workload upgrade requires --workload-profile and --image"
        )
    selected = maintenance._checks(inventory, deployment, connection, config)
    # Probe the running source before candidate qualification or mutable intent.
    from loom.coordinator import CoordinatorOperatorClient

    with CoordinatorOperatorClient.from_connection_file(
        selected["operator_connection"]
    ) as operator:
        source = maintenance._capable(operator)
        if CAPABILITY not in source["value"].get("capabilities", ()):
            raise QueueConflictError(
                "unsupported_capability: source lacks "
                + CAPABILITY
                + "; complete a separate explicit --runtime-release upgrade first"
            )
    plan = maintenance.preview(
        inventory,
        runtime_release=inventory.runtime_release,
        deployment=deployment,
        connection=connection,
        config=config,
        env_file=env_file,
    )
    consumers = {
        name: row
        for name, row in plan["hosts"].items()
        if name != "coordinator"
        and plan["declarations"][name]["resident_profiles"][0]["descriptor"][
            "profile_id"
        ]
        == workload_profile
    }
    if not consumers:
        raise QueueConfigError("selected workload profile has no consuming agents")
    for name, row in plan["hosts"].items():
        if row["source_release"] != plan["release"]:
            raise QueueConflictError(
                "workload source release differs from selected immutable runtime"
            )
        if name in consumers and CAPABILITY not in row["native_owner"]["value"].get(
            "capabilities", ()
        ):
            raise QueueConflictError(
                "unsupported_capability: running agent "
                + name
                + " lacks "
                + CAPABILITY
                + "; complete a separate explicit --runtime-release upgrade first"
            )
    image = Path(image).resolve()
    sha = sshops._file_hash(image)
    candidates = {}
    for name, row in consumers.items():
        candidates[name] = sshops.ssh(
            row["host"],
            {
                **row,
                "release": plan["release"],
                "action": "workload-probe",
                "expected_declaration": digest(plan["declarations"][name]),
                "workload_profile": workload_profile,
                "image": str(image),
                "image_sha256": sha,
            },
        )
    profiles = [candidate["target"]["profile"] for candidate in candidates.values()]
    if any(profile != profiles[0] for profile in profiles):
        raise QueueConflictError("native target profile differs across consuming hosts")
    declarations = json.loads(json.dumps(plan["declarations"]))
    for name, candidate in candidates.items():
        declarations[name] = candidate["declaration"]
    coordinator = declarations["coordinator"]
    coordinator["remote_profiles"] = [
        profiles[0] if p["profile_id"] == workload_profile else p
        for p in coordinator["remote_profiles"]
    ]
    policies = coordinator["preparation"]["profiles"]
    aliases = {
        name: name + "-image-" + sha[:16]
        for name, value in policies.items()
        if value["resident_profile_id"] == workload_profile
    }
    original = load_deployment(plan["checks"]["deployment"])
    if original.preparation_profile not in aliases:
        raise QueueConfigError(
            "deployment must select the workload profile being upgraded"
        )
    for old, new in aliases.items():
        if new in policies:
            raise QueueConflictError("target preparation generation already exists")
        policies[new] = policies.pop(old)
    plan.update(
        workload_profile=workload_profile,
        image=str(image),
        image_sha256=sha,
        candidates=candidates,
        target_declarations=declarations,
        agents={name: plan["agents"][name] for name in consumers},
        preparation_profile=aliases[original.preparation_profile],
        sequence=[
            "qualify immutable SIF on all consumers",
            "close admission",
            "wait admitted work and native settlement",
            "conditional drain",
            "publish selected source and native promotion",
            "reload coordinator profile selection",
            "join current supervisor",
            "authorize exact checks",
            "wait checks and release",
            "conditional policy restoration",
            "revoke checks and reopen",
        ],
        irreversible="first selected source publication/promotion intent",
    )
    return plan


def bind_intent(intent, plan, directory):
    original = load_deployment(plan["checks"]["deployment"])
    destination = directory / (
        "deployment-image-" + plan["image_sha256"][:16] + ".json"
    )
    selected = replace(original, preparation_profile=plan["preparation_profile"])
    if destination.exists():
        retained = load_deployment(destination)
        if (
            retained.source != selected.source
            or retained.connection != selected.connection
            or retained.preparation_profile != selected.preparation_profile
        ):
            raise QueueConflictError("versioned workload selection conflicts")
    else:
        export_connection_deployment(selected, destination)
    return {
        **intent,
        "kind": "workload-upgrade",
        **{
            key: plan[key]
            for key in (
                "workload_profile",
                "image",
                "image_sha256",
                "candidates",
                "target_declarations",
                "preparation_profile",
            )
        },
        "original_check_selection": intent["check_selection"],
        "check_selection": {
            **intent["check_selection"],
            "deployment": str(destination),
        },
        "inputs": {
            **intent["inputs"],
            str(destination): sshops._file_hash(destination),
        },
    }


class WorkloadUpgrade(maintenance._Upgrade):
    def recheck(self, pending_inputs=None):
        try:
            super().recheck(pending_inputs)
        except QueueConflictError:
            # Native source publication can race a controller read. Defer to its
            # next native reconciliation, never silently accept a changed input.
            updates = (
                read(self.directory / "accepted-inputs.json")
                if (self.directory / "accepted-inputs.json").exists()
                else {}
            )
            for name in self.intent["agents"]:
                row = self.intent["hosts"][name]
                path = Path(row["config"])
                if (
                    self.receipts / (name + "-promotion") / "intent.json"
                ).exists() and sshops._file_hash(path) != updates.get(
                    str(path), self.intent["inputs"][str(path)]
                ):
                    current = _load_protected_config(path, env_file=row["env_file"])[2]
                    if current == self.intent["target_declarations"][name]:
                        raise maintenance._Waiting(
                            "native source publication awaits reconciliation"
                        ) from None
            raise

    def host_observe(self, name, action, **values):
        row = self.intent["hosts"][name]
        declaration = _load_protected_config(
            Path(row["config"]),
            env_file=None if row["env_file"] is None else Path(row["env_file"]),
        )[2]
        return sshops.ssh(
            row["host"],
            {
                **row,
                "action": action,
                "release": self.intent["release"],
                "expected_declaration": digest(declaration),
                **values,
            },
        )

    def probes(self):
        for name, row in self.intent["hosts"].items():
            observed = sshops.ssh(
                row["host"],
                {**row, "action": "inspect", "release": self.intent["release"]},
            )
            if observed["installed"] != row["source_release"]:
                raise QueueConflictError(
                    "workload operation cannot change the service release"
                )
            native = observed["native_owner"]
            if native is None or native["owner"] != row["expected_root_id"]:
                raise QueueConflictError("workload native root identity changed")
            if name in self.intent["candidates"]:
                if native["value"]["ownership"] != "live" or CAPABILITY not in native[
                    "value"
                ].get("capabilities", ()):
                    raise QueueConflictError(
                        "running workload source promotion capability unavailable"
                    )
                candidate = self.host_observe(
                    name,
                    "workload-probe",
                    workload_profile=self.intent["workload_profile"],
                    image=self.intent["image"],
                    image_sha256=self.intent["image_sha256"],
                )
                if candidate["target"] != self.intent["candidates"][name]["target"]:
                    raise QueueConflictError(
                        "immutable workload target qualification changed"
                    )

    def recover_host(self, name):
        """Authorize a communication stop only while our promotion is current."""
        from loom.coordinator import CoordinatorClientError

        identity = self.intent["operation_id"] + "-" + name + "-promotion"
        allow_stop = False
        try:
            control = self.operator.observe_control(identity)
        except CoordinatorClientError as exc:
            if exc.code != "not_found":
                raise
        else:
            if control["state"] == "applied" and control["acknowledged"]:
                current = cast(
                    dict[str, Any],
                    thaw_plain_data(self.operator.observe_agent(name).value),
                )
                if (
                    current["drained"]
                    and (current.get("control") or {}).get("operation_id") == identity
                ):
                    self.gate()
                    allow_stop = True
        row = self.intent["hosts"][name]
        return sshops.ssh(
            row["host"],
            {
                **row,
                "action": "workload-recover",
                "promotion_id": identity,
                "release": self.intent["release"],
                "allow_communication_stop": allow_stop,
            },
        )

    def promote(self, name, candidate_source):
        key = name + "-promotion"
        path = self.receipts / key / "intent.json"
        if path.exists():
            request = read(path)
        else:
            gate = self.gate()
            current = cast(
                dict[str, Any], thaw_plain_data(self.operator.observe_agent(name).value)
            )
            candidate = self.intent["candidates"][name]
            request = cast(
                dict[str, Any],
                AgentControl(
                    self.intent["operation_id"] + "-" + key,
                    AgentControlKind.PROMOTE,
                    name,
                    current["session_id"],
                    current["config_revision"],
                    None,
                    False,
                    "Fleet selected workload promotion",
                    {
                        "maintenance_id": self.intent["operation_id"],
                        "maintenance_intent_digest": digest(self.intent),
                        "expected_gate_revision": gate["revision"],
                        "agent_root_id": current["agent_root_id"],
                        "predecessor_immutable": candidate["source"]["immutable"],
                        "predecessor_active": candidate["source"]["active"],
                        "target_immutable": candidate["target"]["immutable"],
                        "target_active": candidate["target"]["active"],
                        "candidate_source": candidate_source,
                        "profile_id": self.intent["workload_profile"],
                        "target_profile": candidate["target"]["profile"],
                    },
                ).value(),
            )

        def invoke(value):
            self.operator.control_agent(
                AgentControl.from_value(value),
                condition={
                    "expected_control_id": self.intent["operation_id"]
                    + "-"
                    + name
                    + "-drain"
                },
            )
            return self.operator.observe_control(value["operation_id"])

        result = self.native(key, request, invoke)
        if result["state"] != "applied" or not result["acknowledged"]:
            if result["state"] == "failed":
                raise QueueConflictError(
                    "native profile promotion failed: " + str(result)
                )
            raise maintenance._Waiting(
                "native profile promotion acknowledgement: " + request["operation_id"]
            )
        return request["operation_id"]


def continue_upgrade(operation):
    directory, intent = operation.directory, operation.intent
    if (directory / "complete.json").exists():
        return read(directory / "complete.json")
    for name in intent["agents"]:
        if (operation.receipts / (name + "-promotion") / "intent.json").exists():
            response = operation.recover_host(name)
            if response["declaration"] not in (
                intent["declarations"][name],
                intent["target_declarations"][name],
            ):
                raise QueueConflictError("native workload publication conflicts")
            if response["declaration"] == intent["target_declarations"][name]:
                if response["publication_state"] not in {"pending", "applied"}:
                    raise QueueConflictError(
                        "source publication lacks native promotion authorization"
                    )
                receipt = operation.receipts / (name + "-native-publication")
                sshops.protected_directory(receipt)
                operation.accept_update(name, response, receipt)
    operation.recheck()
    source = maintenance._capable(operation.operator)
    if CAPABILITY not in source["value"].get("capabilities", ()):
        raise QueueConflictError(
            "running source lacks native profile promotion; separate runtime upgrade required"
        )
    operation.probes()
    irreversible = directory / "irreversible.json"
    if not irreversible.exists():
        operation.maintenance("close", "close")
        operation.settled()
        for name, agent in intent["agents"].items():
            accepted = operation.policy(
                name,
                name + "-drain",
                "drain",
                (agent.get("control") or {}).get("operation_id"),
            )
            operation.verify_policy(name, accepted)
        operation.settled()
        for name in intent["agents"]:
            fact = operation.host_observe(name, "upgrade-settlement")
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise maintenance._Waiting("host native settlement: " + name)
        atomic(
            irreversible, {"step": "profile-promotion", "intent_digest": digest(intent)}
        )
    for name in intent["agents"]:
        staged = operation.call(
            name,
            "workload-stage",
            declaration=intent["target_declarations"][name],
            image=intent["image"],
            image_sha256=intent["image_sha256"],
            target=intent["candidates"][name]["target"],
        )
        operation.promote(name, staged["candidate_source"])
        response = operation.recover_host(name)
        receipt = operation.receipts / (name + "-native-publication")
        sshops.protected_directory(receipt)
        operation.accept_update(name, response, receipt)
    operation.call(
        "coordinator",
        "workload-publish",
        declaration=intent["target_declarations"]["coordinator"],
    )
    restoring = directory / "restoring.json"
    if not restoring.exists():
        for name in intent["agents"]:
            accepted = operation.policy(
                name,
                name + "-checks-capacity",
                "resume",
                intent["operation_id"] + "-" + name + "-promotion",
            )
            operation.verify_policy(name, accepted)
        maintenance._run_checks(operation)
        atomic(restoring, {"intent_digest": digest(intent)})
    maintenance._restore(operation)
    result = {
        "state": "complete",
        "release": intent["release"],
        "image_sha256": intent["image_sha256"],
        "profile": next(iter(intent["candidates"].values()))["target"]["profile"],
        "checks": maintenance._attempts(operation),
        "deployment": intent["check_selection"]["deployment"],
        "previous_deployment": intent["original_check_selection"]["deployment"],
        "operator_connection": intent["check_selection"]["operator_connection"],
    }
    atomic(directory / "complete.json", result)
    return result
