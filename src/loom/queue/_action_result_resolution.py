"""Join native readiness, original commits and installed action verification."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.io.uris import uri_to_path
from loom.pipeline._action_verification import action_candidate, action_verification_response
from loom.pipeline._project_contracts import CONTRACT, load_contract_report, plain_mapping, worker_contract_metadata
from loom.pipeline.cleanup.preparation_pins import preparation_path_is_retained, retain_preparation_path
from loom.pipeline.planning._action_identity import action_execution_identity
from loom.pipeline.planning.fingerprints import _output_spec_identity
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.coordinator_authority import coordinator_authority_identity
from loom.pipeline.stores.read_models import ActionResultBinding, LifecycleReason
from loom.pipeline.stores.local_artifacts import LocalArtifactStore
from loom.pipeline.stores.shared_artifacts import binding as shared_binding, verify_ref
from loom.serialization import PlainData

from ._action_results import ActionResults
from .errors import QueueConflictError


class ActionResultResolution:
    """Private coordinator integration; projects supply only checked semantics."""

    def __init__(self, execution: Any) -> None:
        self.execution = execution
        self.daemon = execution._daemon_owner()
        self.store = ActionResults(self.daemon._connection)

    def attach_fence(self, run_uri: str, fence: Any) -> None:
        snapshot = self.execution._authority_store(run_uri).open_run(run_uri)
        stage = next((stage for stage in snapshot.stages if any(attempt.attempt_id == fence.attempt_id for attempt in stage.attempts)), None)
        if stage is None:
            raise QueueConflictError("action producer attempt is unavailable")
        claim = self.store.owner(run_uri, stage.stage_name)
        if claim is not None:
            self.store.attach_fence(claim["claim_id"], run_uri=run_uri, node=stage.stage_name,
                                    attempt_id=fence.attempt_id, assignment_id=fence.assignment_id,
                                    fencing_token=fence.fencing_token)

    def resolve(self, admission: Any, intent: Any, authority: Any,
                stage_plan: Any, readiness: Any, revision: Any) -> Any:
        run_uri, node = admission.run_uri, stage_plan.stage_name
        report = load_contract_report(self.execution.run_store, run_uri)
        if report is None:
            return None
        descriptor = plain_mapping(report["profile_descriptor"])
        if not descriptor.get("action_reuse_qualified", False):
            return None
        requirement = intent.execution_requirements[node].to_dict()
        if any(descriptor[key] != value for key, value in requirement.items()):
            raise QueueConflictError("action installation differs from admitted execution")
        implementation = {**requirement, "processor": plain_mapping(report["project_preparation"])["processor"]}
        spec = intent.pipeline.get_stage(node)
        contract = worker_contract_metadata(self.execution.run_store, run_uri, spec)[CONTRACT]
        snapshot = authority.open_run(run_uri)
        stages = {stage.stage_name: stage for stage in snapshot.stages}
        inputs = {}
        for input_ in (*stage_plan.bound_inputs.values(), *stage_plan.pending_inputs):
            source = stages.get(input_.source_stage)
            if source is None or source.latest_commit is None:
                return None
            fact = next((fact for fact in source.artifact_facts if fact.artifact_name == input_.source_output), None)
            if fact is None:
                raise QueueConflictError("action input has no original output fact")
            self._verify_artifact(fact.artifact)
            inputs[input_.input_name] = {"commit": source.latest_commit.to_dict(), "output_port": input_.source_output,
                                         "artifact": fact.artifact.to_dict()}
        identity = action_execution_identity(spec, plain_mapping(contract), implementation=implementation,
                                             inputs=inputs, generation=cast(str, plain_mapping(report.get("generations", {})).get(node, "default")))
        if identity is None:
            return None
        with self.daemon._connection() as conn:
            source = conn.execute("SELECT principal_id, selected_json FROM preparation_operations WHERE operation_id = ?", (report["operation_id"],)).fetchone()
        if source is None:
            raise QueueConflictError("action preparation scope is unavailable")
        scope = {"principal_id": str(source["principal_id"]),
                 "authority": coordinator_authority_identity(self.daemon.config.coordinator_authority_factory),
                 "store_root": self.daemon.config.run_store_root.as_uri(), "installation": implementation}
        selected = self.store.select(run_uri=run_uri, node=node, scope=scope, identity=identity)
        claim = selected["claim"]
        self._retain(claim)
        if selected["decision"] == "owner":
            return None
        if selected["decision"] == "wait":
            self._observe(claim)
            selected = self.store.select(run_uri=run_uri, node=node, scope=scope, identity=identity)
            claim = selected["claim"]
        if selected["decision"] == "wait":
            return revision
        if selected["decision"] == "failed":
            return self._reject(authority, run_uri, node, revision, claim, "action.producer_failed")
        if selected["decision"] == "bound":
            return authority.bind_action_result(run_uri, node, ActionResultBinding.from_dict(selected["binding"]), expected_revision=revision)
        result = plain_mapping(json.loads(claim["result_json"]))
        self._verify_result(claim, result)
        candidate: dict[str, PlainData] = {
            "schema_version": 1, "namespace": plain_mapping(contract)["namespace"],
            "semantic_key": plain_mapping(contract)["semantic_key"], "execution_key": claim["execution_key"],
            "producer": {"run_uri": claim["owner_run_uri"], "node_id": claim["owner_node"],
                         "attempt_id": claim["attempt_id"], "assignment_id": claim["assignment_id"], "fencing_token": claim["fencing_token"]},
            "result": result, "output_contracts": {port: _output_spec_identity(output) for port, output in spec.outputs.items()},
            "installation": implementation,
            "access": {"mode": "read_only", "artifact_root": str(self.execution.run_store.local_artifact_root(claim["owner_run_uri"]))},
        }
        candidate["candidate_digest"] = hash_mapping(candidate)
        candidate = action_candidate(candidate)
        verification = self.daemon._preparations.verify_action_result(source_operation_id=cast(str, report["operation_id"]),
                                                                     node_id=node, contract=plain_mapping(contract), candidate=candidate)
        if verification is None:
            return revision
        if verification["failure_code"] is not None:
            return self._reject(authority, run_uri, node, revision, claim, "action.verification_invalid")
        verdict = action_verification_response(verification["verification"], candidate)
        if verdict["verdict"] == "rejected":
            return self._reject(authority, run_uri, node, revision, claim, "action.project_rejected",
                                {"namespace": candidate["namespace"], "reason": verdict["reason"]})
        # Recheck mutable authority, bytes, retention and principal immediately
        # before the revision-guarded binding transaction.
        self._verify_result(claim, result)
        with self.daemon._connection() as conn:
            current = conn.execute("SELECT principal_id FROM preparation_operations WHERE operation_id = ?", (report["operation_id"],)).fetchone()
        if current is None or current["principal_id"] != source["principal_id"]:
            raise QueueConflictError("action authorization changed before binding")
        binding = self.store.bind(run_uri=run_uri, node=node, claim_id=claim["claim_id"],
                                  expected_revision=claim["revision"], result=result, verification=verdict)
        return authority.bind_action_result(run_uri, node, ActionResultBinding.from_dict(binding), expected_revision=revision)

    def _observe(self, claim: Mapping[str, Any]) -> None:
        snapshot = self.execution._authority_store(claim["owner_run_uri"]).open_run(claim["owner_run_uri"])
        stage = next((stage for stage in snapshot.stages if stage.stage_name == claim["owner_node"]), None)
        if stage is None:
            return
        if stage.status is StageStatus.SUCCEEDED and stage.latest_commit is not None:
            result = {"commit": stage.latest_commit.to_dict(), "artifact_facts": [fact.to_dict() for fact in stage.artifact_facts]}
            self._verify_result(claim, result)
            self.store.publish(claim["claim_id"], result=result, attempt_id=claim["attempt_id"],
                               assignment_id=claim["assignment_id"], fencing_token=claim["fencing_token"])
        elif stage.status in {StageStatus.FAILED, StageStatus.CANCELLED}:
            self.store.fail(claim["claim_id"], {"code": "producer_failed"})

    def _retain(self, claim: Mapping[str, Any]) -> None:
        retain_preparation_path(self.execution.run_store.local_run_dir(claim["owner_run_uri"]),
                                coordinator_id=self.execution.coordinator_id, operation_id="action-" + claim["claim_id"])

    def _verify_result(self, claim: Mapping[str, Any], result: Mapping[str, PlainData]) -> None:
        uri = claim["owner_run_uri"]
        if not preparation_path_is_retained(self.execution.run_store.local_run_dir(uri)):
            raise QueueConflictError("action result retention is unavailable")
        snapshot = self.execution._authority_store(uri).open_run(uri)
        stage = next((stage for stage in snapshot.stages if stage.stage_name == claim["owner_node"]), None)
        if stage is None or stage.status is not StageStatus.SUCCEEDED or stage.result_binding is not None or stage.latest_commit is None or stage.latest_commit.attempt_id != claim["attempt_id"]:
            raise QueueConflictError("action candidate has no original successful producer")
        if {"commit": stage.latest_commit.to_dict(), "artifact_facts": [fact.to_dict() for fact in stage.artifact_facts]} != result:
            raise QueueConflictError("action candidate original authority changed")
        for fact in stage.artifact_facts:
            self._verify_artifact(fact.artifact)

    def _verify_artifact(self, ref: ArtifactRef) -> None:
        path = uri_to_path(ref.uri)
        if shared_binding(ref.metadata) is not None:
            verify_ref(ref, path)
        elif not LocalArtifactStore(self.daemon.config.run_store_root).verify_checksum(ref):
            raise QueueConflictError("action artifact integrity is unavailable")

    @staticmethod
    def _reject(authority: Any, run_uri: str, node: str, revision: Any,
                claim: Mapping[str, Any], code: str, detail: Mapping[str, PlainData] | None = None) -> Any:
        return authority.transition_stage(run_uri, node, from_status=None,
            to_status=StageStatus.FAILED, expected_revision=revision,
            reason=LifecycleReason(code=code, detail={"claim_id": claim["claim_id"],
                "origin_run_uri": claim["owner_run_uri"], "origin_node_id": claim["owner_node"],
                "original_result": None if claim["result_json"] is None else json.loads(claim["result_json"]),
                **dict(detail or {})})).revision
