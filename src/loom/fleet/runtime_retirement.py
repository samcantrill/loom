"""Retire deleted predecessor inputs while replacing the service runtime.

Uses the existing Fleet operation, native maintenance gate, source publication,
control delivery and service replacement receipts. Preview never installs code.
"""

from pathlib import Path

from loom.deployment import load_deployment
from loom.fleet import upgrades as maintenance, ssh_operations as sshops
from loom.fleet._host import atomic, read, digest
from loom.fleet.workload_upgrades import WorkloadUpgrade
from loom.queue.errors import QueueConfigError, QueueConflictError


def preview(inventory, *, runtime_release, workload_inventory, deployment, connection,
            config, check_execution, env_file):
    if workload_inventory is None or check_execution is None:
        raise QueueConfigError("runtime retirement requires candidate inventory and submitted check execution")
    plan = maintenance.preview(inventory, runtime_release=runtime_release,
        deployment=deployment, connection=connection, config=config,
        check_execution=check_execution, env_file=env_file)
    from .workload_sources import candidates

    declarations, inputs, sources = candidates(inventory, workload_inventory, plan,
        plan["agents"], env_file, retire_configuration=True)
    selected = load_deployment(plan["checks"]["deployment"])
    for name in plan["agents"]:
        if maintenance._check_profile(declarations, name, selected, check_execution) != selected.preparation_profile:
            raise QueueConfigError("runtime retirement checks must select a retained submitted profile")
    plan.update(retire_configuration=True, runtime_retirement=True,
        workload_profile=None, image=None, image_sha256=None,
        generation="retirement-" + digest(declarations)[:16], candidates={}, coordinator_target=None,
        workload_inventory=str(Path(workload_inventory).resolve()), candidate_inputs=inputs,
        candidate_sources=sources, target_declarations=declarations,
        preparation_profile=selected.preparation_profile,
        sequence=["install and qualify candidate runtime and declarations", "close and settle admission",
                  "drain and stop roles", "convert and replace coordinator",
                  "convert and replace agents with native acknowledgement", "run submitted checks",
                  "publish clients at held checkpoint", "restore admission"])
    return plan


class RuntimeRetirementUpgrade(WorkloadUpgrade):
    def qualification(self, name):
        value = read(self.directory / (name + "-candidate.json"))
        if value["intent_digest"] != digest(self.intent):
            raise QueueConflictError("runtime retirement qualification intent changed")
        return value

    def promotion_candidate(self, name):
        value = self.qualification(name)
        return {"source": value["retirement_source"], "target": value["retirement_target"],
                "declaration": self.intent["target_declarations"][name]}

    def probes(self):
        for name in self.intent["hosts"]:
            path = self.directory / (name + "-candidate.json")
            previous = self.qualification(name) if path.exists() else None
            result = self.host_observe(name, "upgrade-probe", **self.runtime_arguments(name),
                retirement_declaration=self.intent["target_declarations"][name],
                retirement_target=None if previous is None else previous["retirement_target"])
            if previous is not None and result.get("retirement_source") != previous.get("retirement_source"):
                raise QueueConflictError("runtime retirement predecessor changed")
            atomic(path, {**result, "intent_digest": digest(self.intent)})

    def runtime_arguments(self, name):
        row = self.intent["hosts"][name]
        return {"expected_root_id": row["expected_root_id"],
                "source_release": row["source_release"],
                "coordinator_id": self.intent["check_selection"]["coordinator_id"],
                "descriptor_name": Path(self.intent["target_path"]).name,
                "required_capabilities": list(maintenance.REQUIRED_CAPABILITIES), "images": {}}



def continue_upgrade(operation):
    directory, intent = operation.directory, operation.intent
    if (directory / "complete.json").exists():
        return read(directory / "complete.json")
    if (directory / "restoring.json").exists():
        maintenance._restore(operation)
        return maintenance._complete_runtime(operation)
    operation.reconcile_publications()
    operation.recheck()
    irreversible = directory / "irreversible.json"
    if not irreversible.exists():
        maintenance.phase(operation, "preparing")
        maintenance._capable(operation.operator)
        installed = sshops._ssh_many({name: (row["host"], {
            **row, "action": "install-candidate", "release": intent["release"],
            **sshops._bundle(operation.inventory),
        }) for name, row in intent["hosts"].items()})
        for result in installed.values():
            if isinstance(result, Exception):
                raise result
        operation.probes()
        operation.call_many([(name, "workload-stage", {
            "retire_configuration": True, "declaration": intent["target_declarations"][name],
            "target": operation.qualification(name)["retirement_target"],
        }) for name in intent["agents"]])
        maintenance._preflight_checks(operation)
        operation.maintenance("close", "close")
        operation.settled()
        maintenance.phase(operation, "draining")
        maintenance._independent_policies(operation, [
            (name, name + "-drain", "drain", (agent.get("control") or {}).get("operation_id"))
            for name, agent in intent["agents"].items()])
        operation.settled()
        for name in intent["hosts"]:
            fact = operation.host_observe(name, "upgrade-settlement")
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise maintenance._Waiting("host native settlement: " + name, "settlement_pending")
        gate = operation.gate()
        atomic(irreversible, {"step": "runtime-retirement", "intent_digest": digest(intent),
            "scheduling_epoch": operation.operator.observe_status().value["scheduling_epoch"],
            "retirement": {"maintenance_id": gate["maintenance_id"],
                           "maintenance_intent_digest": gate["intent_digest"],
                           "expected_gate_revision": gate["revision"]}})
    checkpoint = read(irreversible)
    maintenance.phase(operation, "replacing")
    for name in [*intent["agents"], "coordinator"]:
        operation.call(name, "upgrade-stop", **operation.runtime_arguments(name),
            retirement_declaration=intent["target_declarations"][name],
            retirement_target=operation.qualification(name)["retirement_target"])
    operation.call("coordinator", "workload-publish",
        expected_root_id=intent["hosts"]["coordinator"]["expected_root_id"],
        source_release=intent["hosts"]["coordinator"]["source_release"],
        declaration=intent["target_declarations"]["coordinator"], stopped_retirement=True,
        expected_scheduling_epoch=checkpoint["scheduling_epoch"], retirement=checkpoint["retirement"])
    operation.call("coordinator", "upgrade-replace", **operation.runtime_arguments("coordinator"))
    maintenance._capable(operation.operator)
    operation.gate()
    for name in intent["agents"]:
        staged = read(operation.receipts / (name + "-workload-stage") / "receipt.json")
        operation.promote_stopped(name, staged["candidate_source"], operation.runtime_arguments(name))
    # Reuse runtime ownership/release observations after all native conversions.
    maintenance._Upgrade.probes(operation)
    maintenance._independent_policies(operation, [
        (name, name + "-checks-capacity", "resume", intent["operation_id"] + "-" + name + "-promotion")
        for name in intent["agents"]])
    maintenance._run_checks(operation)
    atomic(directory / "restoring.json", {"intent_digest": digest(intent)})
    maintenance._restore(operation)
    return maintenance._complete_runtime(operation)
