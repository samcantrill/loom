"""Selected SIF promotion composed with native whole-fleet maintenance.

No service runtime is installed here. The accepted source release must already
supply native promotion/recovery on every consuming agent and coordinator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, cast

from loom.deployment import load_deployment, export_connection_deployment
from loom.fleet._host import atomic, read, digest
from loom.fleet.configuration import _environment_files
from loom.fleet import ssh_operations as sshops
from loom.fleet import upgrades as maintenance
from loom.queue._profile_promotion import CAPABILITY, RETIREMENT_CAPABILITY
from loom.queue._container_policy_addition import CAPABILITY as ADDITION_CAPABILITY
from loom.queue._publication_budget_increase import CAPABILITY as BUDGET_CAPABILITY
from loom.queue.shared_execution import SOURCE_PROMOTION_CAPABILITY
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.deployment import _load_protected_config
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.serialization import thaw_plain_data


def preview(
    inventory,
    *,
    workload_profile,
    image,
    workload_inventory=None,
    deployment=None,
    connection=None,
    config="fleet-check.yaml",
    env_file=None,
):
    """Qualify immutable bytes on all consumers, without maintenance mutations."""
    _environment_files(inventory, env_file)
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
        if workload_inventory is not None and SOURCE_PROMOTION_CAPABILITY not in source["value"].get("capabilities", ()):
            raise QueueConflictError("source inventory promotion requires a capable runtime upgrade first")
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
    target_declarations = None
    candidate_inputs = {}
    candidate_sources = None
    if workload_inventory is not None:
        from .workload_sources import candidates as source_candidates

        for name in consumers:
            if SOURCE_PROMOTION_CAPABILITY not in plan["hosts"][name]["native_owner"]["value"].get("capabilities", ()):
                raise QueueConflictError("source inventory promotion requires a capable agent runtime: " + name)
        target_declarations, candidate_inputs, candidate_sources = source_candidates(
            inventory, workload_inventory, plan, consumers, env_file
        )
    requests = {}
    for name, row in consumers.items():
        requests[name] = (
            row["host"],
            {
                **row,
                "release": plan["release"],
                "action": "workload-probe",
                "expected_declaration": digest(plan["declarations"][name]),
                "workload_profile": workload_profile,
                "image": str(image),
                "image_sha256": sha,
                **({"candidate_declaration": target_declarations[name]} if target_declarations is not None else {}),
            },
        )
    candidates = sshops._ssh_many(requests)
    for candidate in candidates.values():
        if isinstance(candidate, Exception):
            raise candidate
    profiles = [candidate["target"]["profile"] for candidate in candidates.values()]
    if any(profile != profiles[0] for profile in profiles):
        raise QueueConflictError("native target profile differs across consuming hosts")
    declarations = target_declarations or json.loads(json.dumps(plan["declarations"]))
    for name, candidate in candidates.items():
        declarations[name] = candidate["declaration"]
    coordinator = declarations["coordinator"]
    coordinator["remote_profiles"] = [
        profiles[0] if p["profile_id"] == workload_profile else p
        for p in coordinator["remote_profiles"]
    ]
    policies = coordinator["preparation"]["profiles"]
    generation = "image-" + sha[:16]
    if workload_inventory is not None:
        generation = "source-" + digest({
            "image": sha, "declarations": declarations,
            "profiles": profiles,
        })[:16]
    aliases = {
        name: name + "-" + generation
        for name, value in policies.items()
        if value.get("resident_profile_id") == workload_profile
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
    coordinator_target = None
    if workload_inventory is not None:
        row = plan["hosts"]["coordinator"]
        coordinator_target = sshops.ssh(
            row["host"],
            {
                **row,
                "release": plan["release"],
                "action": "workload-coordinator-probe",
                "expected_declaration": digest(plan["declarations"]["coordinator"]),
                "declaration": coordinator,
            },
        )
    plan.update(
        workload_profile=workload_profile,
        image=str(image),
        image_sha256=sha,
        generation=generation,
        workload_inventory=None if workload_inventory is None else str(Path(workload_inventory).resolve()),
        candidate_inputs=candidate_inputs,
        candidate_sources=candidate_sources,
        coordinator_target=coordinator_target,
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


def configuration_preview(inventory, *, workload_inventory, deployment, connection, config, check_execution, env_file, add_container_policies=False, increase_publication_budgets=False):
    """Qualify additive or narrowing declarations under existing maintenance."""
    label = "publication budget increase" if increase_publication_budgets else "container policy addition" if add_container_policies else "configuration retirement"
    if workload_inventory is None or check_execution is None:
        raise QueueConfigError(label + " requires candidate inventory and submitted check execution")
    plan = maintenance.preview(inventory, runtime_release=inventory.runtime_release,
        deployment=deployment, connection=connection, config=config,
        check_execution=check_execution, env_file=env_file)
    mode = "increase_publication_budgets" if increase_publication_budgets else "add_container_policies" if add_container_policies else "retire_configuration"
    required = {BUDGET_CAPABILITY} if increase_publication_budgets else {ADDITION_CAPABILITY} if add_container_policies else {RETIREMENT_CAPABILITY, "quiescent-coordinator-retirement-v1"}
    if not required <= set(plan["source"]["value"].get("capabilities", ())):
        raise QueueConflictError("source runtime lacks " + label + " capability")
    consumers = {name: row for name, row in plan["hosts"].items() if name != "coordinator"}
    for row in plan["hosts"].values():
        if row["source_release"] != plan["release"]:
            raise QueueConflictError(label + " cannot change the service runtime")
    for name, row in consumers.items():
        if (BUDGET_CAPABILITY if increase_publication_budgets else ADDITION_CAPABILITY if add_container_policies else RETIREMENT_CAPABILITY) not in row["native_owner"]["value"].get("capabilities", ()):
            raise QueueConflictError("agent runtime lacks " + label + " capability: " + name)
    from .workload_sources import candidates as source_candidates

    declarations, inputs, sources = source_candidates(inventory, workload_inventory, plan,
        consumers, env_file, **{mode: True})
    candidates = sshops._ssh_many({name: (row["host"], {
        **row, "release": plan["release"], "action": "workload-probe",
        "expected_declaration": digest(plan["declarations"][name]),
        mode: True, "candidate_declaration": declarations[name],
    }) for name, row in consumers.items()})
    for candidate in candidates.values():
        if isinstance(candidate, Exception):
            raise candidate
    original = load_deployment(plan["checks"]["deployment"])
    for name in consumers:
        if maintenance._check_profile(declarations, name, original, check_execution) != original.preparation_profile:
            raise QueueConfigError(label + " check deployment must select the target submitted profile")
    row = plan["hosts"]["coordinator"]
    target = sshops.ssh(row["host"], {**row, "release": plan["release"],
        "action": "workload-coordinator-probe",
        mode: True,
        "expected_declaration": digest(plan["declarations"]["coordinator"]),
        "declaration": declarations["coordinator"]})
    plan.update(**{mode: True}, workload_profile=None, image=None, image_sha256=None,
        generation=("budget-increase-" if increase_publication_budgets else "policy-addition-" if add_container_policies else "retirement-") + digest(declarations)[:16],
        workload_inventory=str(Path(workload_inventory).resolve()), candidate_inputs=inputs,
        candidate_sources=sources, coordinator_target=target, candidates=candidates,
        target_declarations=declarations, preparation_profile=original.preparation_profile,
        sequence=["qualify target declarations", "close and settle admission", "drain agents",
                  "retire agent declarations", "retire coordinator declarations", "run submitted checks",
                  "publish clients at held checkpoint", "restore admission"],
        irreversible="first native retirement intent")
    if add_container_policies:
        plan["sequence"] = ["qualify added policies", "close and settle admission", "drain agents",
                            "add agent policies", "add coordinator selections", "run submitted checks",
                            "publish clients at held checkpoint", "restore admission"]
        plan["irreversible"] = "first native policy addition intent"
    if increase_publication_budgets:
        plan["sequence"] = ["qualify increased publication budgets", "close and settle admission", "drain agents",
                            "increase agent publication budgets", "increase coordinator publication budgets", "run submitted checks",
                            "publish clients at held checkpoint", "restore admission"]
        plan["irreversible"] = "first native publication budget increase intent"
    return plan


def bind_intent(intent, plan, directory):
    original = load_deployment(plan["checks"]["deployment"])
    destination = directory / ("deployment-" + plan["generation"] + ".json")
    selected = replace(original, preparation_profile=plan["preparation_profile"])
    coordinator = plan["target_declarations"]["coordinator"]
    policy_id = coordinator["preparation"]["profiles"][selected.preparation_profile].get("container_policy_id")
    if policy_id is not None:
        from loom.queue.submitted_execution import SubmittedContainerCapability
        capability = next(item for item in coordinator["container_capabilities"] if item["policy_id"] == policy_id)
        selected = replace(selected, worker_contract=SubmittedContainerCapability.from_dict(capability).required_worker_contract)
    if destination.exists():
        retained = load_deployment(destination)
        if (
            retained.source != selected.source
            or retained.connection != selected.connection
            or retained.preparation_profile != selected.preparation_profile
            or retained.worker_contract != selected.worker_contract
        ):
            raise QueueConflictError("versioned workload selection conflicts")
    else:
        export_connection_deployment(selected, destination)
    return {
        **intent,
        "kind": ("publication-budget-increase" if plan.get("increase_publication_budgets") else
                 "container-policy-addition" if plan.get("add_container_policies") else
                 "configuration-retirement" if plan.get("retire_configuration") else "workload-upgrade"),
        **({"add_container_policies": True} if plan.get("add_container_policies") else {}),
        **({"increase_publication_budgets": True} if plan.get("increase_publication_budgets") else {}),
        **({"retire_configuration": True} if plan.get("retire_configuration") else {}),
        **({"runtime_retirement": True} if plan.get("runtime_retirement") else {}),
        **{
            key: plan[key]
            for key in (
                "workload_profile",
                "image",
                "image_sha256",
                "candidates",
                "target_declarations",
                "preparation_profile",
                "workload_inventory",
                "candidate_sources",
                "coordinator_target",
            )
        },
        "original_check_selection": intent["check_selection"],
        "check_selection": {
            **intent["check_selection"],
            "deployment": str(destination),
        },
        "inputs": {
            **intent["inputs"],
            **plan["candidate_inputs"],
            str(destination): sshops._file_hash(destination),
        },
    }


class WorkloadUpgrade(maintenance._Upgrade):
    _preview_qualification: dict[str, Any] | None = None

    def reconcile_publications(self):
        # Only one source-changing action is dispatched at a time. Reconcile
        # that exact retained call before the global input-byte check.
        calls = [("coordinator", "workload-publish")]
        if self.intent.get("runtime_retirement"):
            calls.extend((name, "workload-stopped-retire") for name in self.intent["agents"])
        for name, action in calls:
            directory = self.receipts / (name + "-" + action)
            if not (directory / "dispatch.json").exists():
                continue
            request = read(directory / "intent.json")
            generated = {"name", "host", "config", "root", "env_file", "env_sha256",
                         "service_manager", "action", "release", "request_id", "expected_declaration"}
            self.call(name, action, **{key: value for key, value in request.items() if key not in generated})

    def recheck_composed(self, pending_inputs=None):
        super().recheck_composed(pending_inputs)
        sources = self.intent.get("candidate_sources")
        if sources is not None:
            for name, row in sources["hosts"].items():
                current = _load_protected_config(
                    Path(row["config"]), env_file=row["env_file"]
                )[2]
                if current != sources["declarations"][name]:
                    raise QueueConflictError(
                        "composed workload candidate changed since operation intent"
                    )

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
        self.recheck_composed()
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
        # Retain preparation once after intent binding, before closing admission.
        # Staging/promotion still revalidates mutable inputs at activation.
        preview = getattr(self, "_preview_qualification", None)
        reuse_preview = preview is not None and all(
            preview.get(key) == self.intent.get(key) for key in (
                "release", "hosts", "declarations", "agents", "workload_profile",
                "image", "image_sha256", "candidates", "target_declarations",
                "workload_inventory", "candidate_sources", "coordinator_target",
                "retire_configuration", "add_container_policies", "increase_publication_budgets",
            )
        )
        if reuse_preview:
            self.recheck()
            if not (self.intent.get("retire_configuration") or self.intent.get("add_container_policies") or self.intent.get("increase_publication_budgets")) and sshops._file_hash(Path(self.intent["image"])) != self.intent["image_sha256"]:
                raise QueueConflictError("workload image changed after qualification")
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
            if self.intent.get("add_container_policies") and ADDITION_CAPABILITY not in native["value"].get("capabilities", ()):
                raise QueueConflictError("running container policy addition capability unavailable: " + name)
            if self.intent.get("increase_publication_budgets") and BUDGET_CAPABILITY not in native["value"].get("capabilities", ()):
                raise QueueConflictError("running publication budget increase capability unavailable: " + name)
            if self.intent.get("retire_configuration"):
                required = (
                    "quiescent-coordinator-retirement-v1"
                    if name == "coordinator" else RETIREMENT_CAPABILITY
                )
                capabilities = native["value"].get("capabilities", ())
                if name == "coordinator":
                    # Process records describe shared service features; the live
                    # coordinator advertises its role-specific retirement API.
                    source = self.operator.observe_status()
                    if (source.availability != "available" or source.freshness != "current"
                        or source.owner != row["expected_root_id"]):
                        raise QueueConflictError("current coordinator retirement capability observation unavailable")
                    capabilities = cast(Sequence[str], source.value.get("capabilities", ()))
                if required not in capabilities:
                    raise QueueConflictError(
                        "running source retirement capability unavailable: " + name
                    )
            if self.intent.get("workload_inventory") is not None and (
                name == "coordinator" or name in self.intent["candidates"]
            ) and SOURCE_PROMOTION_CAPABILITY not in native["value"].get("capabilities", ()):
                raise QueueConflictError("running source inventory promotion capability unavailable")
            if name in self.intent["candidates"]:
                if native["value"]["ownership"] != "live" or CAPABILITY not in native[
                    "value"
                ].get("capabilities", ()):
                    raise QueueConflictError(
                        "running workload source promotion capability unavailable"
                    )
            prepared = self.directory / (name + "-candidate.json")
            if prepared.exists():
                if read(prepared).get("intent_digest") != digest(self.intent):
                    raise QueueConflictError("workload qualification intent changed")
                continue
            if reuse_preview:
                atomic(prepared, {"intent_digest": digest(self.intent)})
                continue
            if name == "coordinator" and self.intent.get("coordinator_target") is not None:
                target = self.host_observe(
                    name, "workload-coordinator-probe",
                    declaration=self.intent["target_declarations"][name],
                    **({"increase_publication_budgets": True} if self.intent.get("increase_publication_budgets") else
                       {"add_container_policies": True} if self.intent.get("add_container_policies") else
                       {"retire_configuration": True} if self.intent.get("retire_configuration") else {}),
                )
                if target != self.intent["coordinator_target"]:
                    raise QueueConflictError("coordinator workload target qualification changed")
            elif name in self.intent["candidates"]:
                candidate = self.host_observe(
                    name, "workload-probe",
                    **({"increase_publication_budgets": True} if self.intent.get("increase_publication_budgets") else
                       {"add_container_policies": True} if self.intent.get("add_container_policies") else
                           {"retire_configuration": True} if self.intent.get("retire_configuration") else {
                        "workload_profile": self.intent["workload_profile"],
                        "image": self.intent["image"], "image_sha256": self.intent["image_sha256"],
                    }),
                    **({"candidate_declaration": self.intent["target_declarations"][name]}
                       if self.intent.get("workload_inventory") is not None else {}),
                )
                if candidate["target"] != self.intent["candidates"][name]["target"]:
                    raise QueueConflictError("immutable workload target qualification changed")
            atomic(prepared, {"intent_digest": digest(self.intent)})

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

    def promotion_candidate(self, name):
        return self.intent["candidates"][name]

    def accept_promotion(self, name, candidate_source):
        """Retain and submit the exact control before waiting for its agent effect."""
        key = name + "-promotion"
        path = self.receipts / key / "intent.json"
        if path.exists():
            request = read(path)
        else:
            gate = self.gate()
            binding = maintenance._maintenance_binding(self.intent)
            current = cast(
                dict[str, Any], thaw_plain_data(self.operator.observe_agent(name).value)
            )
            candidate = self.promotion_candidate(name)
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
                        "maintenance_id": binding["operation_id"],
                        "maintenance_intent_digest": binding["target_intent_digest"],
                        "expected_gate_revision": gate["revision"],
                        "agent_root_id": current["agent_root_id"],
                        "predecessor_immutable": candidate["source"]["immutable"],
                        "predecessor_active": candidate["source"]["active"],
                        "target_immutable": candidate["target"]["immutable"],
                        "target_active": candidate["target"]["active"],
                        "candidate_source": candidate_source,
                        **({"increase_publication_budgets": True} if self.intent.get("increase_publication_budgets") else
                       {"add_container_policies": True} if self.intent.get("add_container_policies") else
                           {"retire_configuration": True} if self.intent.get("retire_configuration") else {
                            "profile_id": self.intent["workload_profile"],
                            "target_profile": candidate["target"]["profile"],
                        }),
                        **({"enable_submitted_containers": True} if
                           candidate["declaration"].get("container_policies") and not
                           self.intent["declarations"][name].get("container_policies") else {}),
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
        if result["state"] == "failed":
            raise QueueConflictError("native profile promotion failed: " + str(result))
        return request, result

    def promote(self, name, candidate_source):
        request, result = self.accept_promotion(name, candidate_source)
        if result["state"] != "applied" or not result["acknowledged"]:
            raise maintenance._Waiting(
                "native profile promotion acknowledgement: " + request["operation_id"]
            )
        return request["operation_id"]

    def promote_stopped(self, name, candidate_source, replacement):
        """Convert a stopped agent, replace its runtime, then await native ack.

        Resume host publication before submitting the retained control again:
        publication may have changed source bytes before its reply was received.
        Each agent must acknowledge before the next promotion is authorized.
        """
        if not self.intent.get("retire_configuration"):
            raise QueueConflictError("stopped promotion requires configuration retirement")
        host_intent = self.receipts / (name + "-workload-stopped-retire") / "intent.json"
        if host_intent.exists():
            control = read(host_intent)["control"]
        else:
            control, _ = self.accept_promotion(name, candidate_source)
        row = self.intent["hosts"][name]
        self.call(name, "workload-stopped-retire", control=control,
            expected_root_id=row["expected_root_id"], source_release=row["source_release"],
            coordinator_id=self.intent["check_selection"]["coordinator_id"])
        self.call(name, "upgrade-replace", **replacement)
        return self.promote(name, candidate_source)


def _promote_agents(operation):
    intent = operation.intent
    staged = operation.call_many([
        (name, "workload-stage", {
            "declaration": intent["target_declarations"][name],
            **({"increase_publication_budgets": True} if intent.get("increase_publication_budgets") else
                       {"add_container_policies": True} if intent.get("add_container_policies") else
               {"retire_configuration": True} if intent.get("retire_configuration") else {
                "image": intent["image"], "image_sha256": intent["image_sha256"],
            }),
            "target": intent["candidates"][name]["target"],
        }) for name in intent["agents"]
    ])
    # Native promotion authorization requires global control settlement. Staging
    # is independent; each promotion must be acknowledged before the next one.
    for name in intent["agents"]:
        operation.promote(name, staged[name]["candidate_source"])
        response = operation.recover_host(name)
        receipt = operation.receipts / (name + "-native-publication")
        sshops.protected_directory(receipt)
        operation.accept_update(name, response, receipt)


def continue_upgrade(operation):
    directory, intent = operation.directory, operation.intent
    if (directory / "complete.json").exists():
        return read(directory / "complete.json")
    if intent["kind"].endswith("-publication") and (directory / "restoring.json").exists():
        maintenance._restore(operation)
        return _complete_workload(operation)
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
    operation.reconcile_publications()
    maintenance.phase(operation, "preparing")
    operation.recheck()
    source = maintenance._capable(operation.operator)
    if CAPABILITY not in source["value"].get("capabilities", ()):
        raise QueueConflictError(
            "running source lacks native profile promotion; separate runtime upgrade required"
        )
    operation.probes()
    irreversible = directory / "irreversible.json"
    if not irreversible.exists():
        maintenance._preflight_checks(operation)
        if "maintenance_binding" in intent:
            operation.gate()
        else:
            operation.maintenance("close", "close")
        operation.settled()
        if "maintenance_binding" in intent:
            # The predecessor checks are settled evidence, not permission to run
            # the old workload during promotion. Keep their results untouched.
            for identity in list(operation.gate()["checks"]):
                operation.maintenance("revoke-before-promotion-" + identity, "revoke", identity)
        maintenance.phase(operation, "draining")
        maintenance._independent_policies(operation, [
            (name, name + "-drain", "drain",
             (agent.get("control") or {}).get("operation_id"))
            for name, agent in intent["agents"].items()
        ])
        operation.settled()
        for name in intent["agents"]:
            fact = operation.host_observe(name, "upgrade-settlement")
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise maintenance._Waiting("host native settlement: " + name, "settlement_pending")
        atomic(
            irreversible, {"step": "profile-promotion", "intent_digest": digest(intent)}
        )
    maintenance.phase(operation, "replacing")
    _promote_agents(operation)
    publication = {}
    if intent.get("retire_configuration") or intent.get("add_container_policies") or intent.get("increase_publication_budgets"):
        kind = "publication_budget_increase" if intent.get("increase_publication_budgets") else "container_policy_addition" if intent.get("add_container_policies") else "retirement"
        retained = operation.receipts / "coordinator-workload-publish" / "intent.json"
        # Health checks advance the gate revision after publication. Every resume
        # must replay the original authorization, including a lost applied reply.
        publication[kind] = read(retained)[kind] if retained.exists() else {
            "maintenance_id": maintenance._maintenance_binding(intent)["operation_id"],
            "maintenance_intent_digest": maintenance._maintenance_binding(intent)["target_intent_digest"],
            "expected_gate_revision": operation.gate()["revision"],
        }
    operation.call(
        "coordinator",
        "workload-publish",
        declaration=intent["target_declarations"]["coordinator"],
        **publication,
    )
    restoring = directory / "restoring.json"
    if not restoring.exists():
        maintenance._independent_policies(operation, [
            (name, name + "-checks-capacity", "resume",
             intent["operation_id"] + "-" + name + "-promotion")
            for name in intent["agents"]
        ])
        maintenance._run_checks(operation)
        atomic(restoring, {"intent_digest": digest(intent)})
    maintenance._restore(operation)
    return _complete_workload(operation)


def _complete_workload(operation):
    directory, intent = operation.directory, operation.intent
    result = {
        "state": "complete",
        "release": intent["release"],
        "image_sha256": intent["image_sha256"],
        "profile": next(iter(intent["candidates"].values()))["target"]["profile"],
        "checks": maintenance._attempts(operation),
        **maintenance._qualification_result(operation),
        "deployment": intent["check_selection"]["deployment"],
        "previous_deployment": intent["original_check_selection"]["deployment"],
        "operator_connection": intent["check_selection"]["operator_connection"],
    }
    atomic(directory / "complete.json", result)
    return result
