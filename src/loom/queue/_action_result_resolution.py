"""Join native readiness, original commits and installed action verification."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
import json
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.io.uris import uri_to_path
from loom.pipeline._action_verification import (
    action_candidate,
    action_verification_response,
)
from loom.pipeline._project_contracts import (
    CONTRACT,
    load_contract_report,
    plain_mapping,
    _worker_contract_metadata,
)
from loom.pipeline.cleanup.preparation_pins import (
    preparation_path_is_retained,
    retain_preparation_path,
)
from loom.pipeline.planning._action_identity import action_execution_identity
from loom.pipeline.planning.fingerprints import _output_spec_identity
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import ActionProducerBinding
from loom.pipeline.stores.coordinator_authority import coordinator_authority_identity
from loom.pipeline.stores.read_models import ActionResultBinding, AuthoritativeRunSnapshot, LifecycleReason
from loom.pipeline.stores.local_artifacts import LocalArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError
from loom.pipeline.stores.shared_artifacts import binding as shared_binding, verify_ref
from loom.serialization import PlainData

from ._action_results import ActionResults
from ._run_observations import ObservationSteps
from ._result_verification import PendingResult
from ._phase_timing import PhaseTimings, phase
from ._preparation_operations import _PendingActionVerification
from .errors import QueueConflictError


@dataclass(frozen=True, slots=True)
class _PendingReuse:
    readiness: tuple[Any, ...]
    claim_id: str
    claim_revision: int
    child: _PendingActionVerification
    recheck_at: float


@dataclass(frozen=True, slots=True)
class _ReuseContext:
    operation_id: str
    implementation: Mapping[str, PlainData]
    contract: Mapping[str, PlainData]
    identity: Mapping[str, PlainData]


@dataclass(frozen=True, slots=True)
class _PendingReuseContext:
    token: tuple[Any, ...]
    future: Future[_ReuseContext | None]
    timings: PhaseTimings


@dataclass(frozen=True, slots=True)
class _PendingReuseProof:
    context_token: tuple[Any, ...]
    context: _ReuseContext
    claim_token: tuple[Any, ...]
    future: Future[None] | None
    timings: PhaseTimings


@dataclass(frozen=True, slots=True)
class _PendingProducerRead:
    token: tuple[Any, ...]
    future: Future[tuple[Any, AuthoritativeRunSnapshot]]


class _InputUnavailable(Exception):
    def __init__(self, port: str, artifact: ArtifactRef) -> None:
        self.detail = {"input_port": port, "original_artifact": artifact.to_dict()}


class ActionResultResolution:
    """Private coordinator integration; projects supply only checked semantics."""

    def __init__(self, execution: Any) -> None:
        self.execution = execution
        self.daemon = execution._daemon_owner()
        self.store = ActionResults(self.daemon._connection)
        # Bounded, disposable wait hints. Restart/eviction repeats the full proof;
        # no cached contract or artifact evidence can authorize adoption.
        self._producer_reads: dict[tuple[str, str], _PendingProducerRead] = {}
        self._pending: dict[tuple[str, str], _PendingReuse] = {}
        self._contexts: dict[tuple[str, str], _PendingReuseContext] = {}
        self._reuse_proofs: dict[tuple[str, str], _PendingReuseProof] = {}

    def reconcile_producers(self, run_uri: str) -> None:
        claims = self.store.producers(run_uri)
        if not claims:
            return
        authority = self.execution._authority_store(run_uri)
        self._apply_producer_observation(
            authority, claims, authority.open_run(run_uri) if self._needs_observation(claims) else None,
        )

    @staticmethod
    def _needs_observation(claims: tuple[dict[str, Any], ...]) -> bool:
        return any(claim["state"] in {"owned", "settling"} for claim in claims)

    def producer_steps(self, run_uri: str, authority: Any) -> ObservationSteps[None]:
        claims = self.store.producers(run_uri)
        snapshot = (yield) if self._needs_observation(claims) else None
        self._apply_producer_observation(authority, claims, snapshot)

    def _apply_producer_observation(
        self, authority: Any, claims: tuple[Mapping[str, Any], ...], snapshot: AuthoritativeRunSnapshot | None,
    ) -> None:
        for claim in claims:
            # A retry or a demand detach can supersede a read in flight. Its
            # original attempt must never release the successor's permission.
            if snapshot is None or self.store.claim(claim["claim_id"])["revision"] == claim["revision"]:
                self._observe(claim, authority, snapshot)

    def _observe_waiting_producer(self, key: tuple[str, str], claim: Mapping[str, Any]) -> None:
        uri = claim["owner_run_uri"]
        # Live producers reconcile their own claims, even during cancellation.
        # A retained terminal admission from a previous release may still
        # need a consumer to drive settlement after restart.
        with self.daemon._connection() as conn:
            owner = conn.execute("SELECT state FROM managed_admissions WHERE run_uri = ?", (uri,)).fetchone()
        if owner is not None and owner[0] not in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
            return
        token = (self.daemon._epoch, self.daemon._scheduling_epoch, claim["claim_id"], claim["revision"])
        pending = self._producer_reads.get(key)
        if pending is not None:
            if not pending.future.done():
                return
            del self._producer_reads[key]
            if pending.token == token:
                authority, snapshot = pending.future.result()
                self._apply_producer_observation(authority, (claim,), snapshot)
                return
        if len(self._producer_reads) >= 2:
            return

        def read():
            authority = self.execution._authority_store(uri)
            return authority, authority.open_run(uri)

        future = self.daemon._result_verifications.bulk.submit(claim["claim_id"], "reuse_producer_observation", read)
        if future is not None:
            self._producer_reads[key] = _PendingProducerRead(token, future)

    def detach_graph(self, run_uri: str, operation_id: str) -> None:
        self.daemon._result_verifications.bulk.discard(("run", run_uri))
        self.daemon._result_verifications.bulk.discard(("dispatch", run_uri))
        self.daemon._preparations.discard_verification_reports(run_uri)
        for work in (self._contexts, self._reuse_proofs, self._producer_reads):
            for key in tuple(work):
                if key[0] == run_uri:
                    del work[key]
        for key in tuple(self._pending):
            if key[0] == run_uri:
                self._pending.pop(key, None)
        for claim in self.store.detach_graph(run_uri, operation_id):
            if claim["attempt_id"] is not None:
                self.execution._authority_store(
                    claim["owner_run_uri"]
                ).release_action_producer(
                    claim["owner_run_uri"], self._producer_binding(claim)
                )

    def discard_terminal_contexts(self) -> None:
        for work in (self._contexts, self._reuse_proofs, self._producer_reads):
            for key, pending in tuple(work.items()):
                if pending.future is not None and not pending.future.done():
                    continue
                with self.daemon._connection() as conn:
                    row = conn.execute(
                        "SELECT state FROM managed_admissions WHERE run_uri = ?", (key[0],),
                    ).fetchone()
                if row is None or row[0] in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
                    del work[key]

    def reconcile_cancellations(self) -> None:
        """Reconstruct every demand detachment before resuming retained workers."""
        with self.daemon._connection() as conn:
            pending = tuple(
                conn.execute(
                    "SELECT run_uri, cancellation_operation_id FROM managed_admissions WHERE cancellation_operation_id IS NOT NULL"
                )
            )
        for row in pending:
            self.detach_graph(str(row[0]), str(row[1]))

    @staticmethod
    def _producer_binding(claim: Mapping[str, Any]) -> ActionProducerBinding:
        return ActionProducerBinding(
            claim["claim_id"], claim["owner_node"], claim["attempt_id"]
        )

    def attach_fence(self, run_uri: str, fence: Any) -> None:
        snapshot = self.execution._authority_store(run_uri).open_run(run_uri)
        stage = next(
            (
                stage
                for stage in snapshot.stages
                if any(
                    attempt.attempt_id == fence.attempt_id for attempt in stage.attempts
                )
            ),
            None,
        )
        if stage is None:
            raise QueueConflictError("action producer attempt is unavailable")
        claim = self.store.owner(run_uri, stage.stage_name)
        if claim is not None:
            self.store.attach_fence(
                claim["claim_id"],
                run_uri=run_uri,
                node=stage.stage_name,
                attempt_id=fence.attempt_id,
                assignment_id=fence.assignment_id,
                fencing_token=fence.fencing_token,
            )

    def resolve(
        self,
        admission: Any,
        intent: Any,
        authority: Any,
        stage_plan: Any,
        readiness: Any,
        revision: Any,
        snapshot: AuthoritativeRunSnapshot,
    ) -> Any:
        timings = PhaseTimings()
        try:
            with timings.measure("reuse_resolution"):
                return self._resolve(admission, intent, authority, stage_plan, readiness, revision, snapshot, timings)
        finally:
            if len(timings.spans) > 2 or timings.related:
                try:
                    # Audit writes happen after the revision-guarded transition.
                    authority.defer_event(
                        self.execution._event_observers, admission.run_uri,
                        event_type="stage.reuse_timing", stage_name=stage_plan.stage_name,
                        revision=replace(revision, created_at=datetime.now(timezone.utc).isoformat()),
                        identity=uuid4().hex, payload=timings.payload(),
                    )
                except Exception:
                    pass  # Diagnostics do not authorize or reject action reuse.

    def _resolve(
        self, admission: Any, intent: Any, authority: Any, stage_plan: Any,
        readiness: Any, revision: Any, snapshot: AuthoritativeRunSnapshot, timings: PhaseTimings,
    ) -> Any:
        # Context loading already captured this retained document, including
        # its absence. Runs without project contracts cannot use action reuse;
        # they need no per-stage bulk operation merely to rediscover that fact.
        if not getattr(intent, "project_contracts_present", True):
            return None
        run_uri, node = admission.run_uri, stage_plan.stage_name
        key = (run_uri, node)
        readiness_binding = (
            admission.intent_digest, readiness.next_attempt,
            readiness.retry_decision_id, readiness.expected_stage_status,
        )
        pending = self._pending.pop(key, None)
        if (
            pending is not None and pending.readiness == readiness_binding
            and monotonic() < pending.recheck_at
        ):
            with timings.measure("reuse_verifier_observation"):
                still_pending = self.store.verification_demand_current(
                    run_uri, node, pending.claim_id, pending.claim_revision
                ) and self.daemon._preparations.action_verification_pending(pending.child)
            if still_pending:
                self._pending[key] = pending
                timings.related.update(
                    verification_operation_id=pending.child.operation_id,
                    verification_run_uri=pending.child.run_uri,
                )
                return revision
        # Recheck periodically even when a child cannot finish: unavailable
        # original bytes can prevent verifier input materialization indefinitely.
        # Completion or changed bindings also take this full path before adoption.
        token = (
            self.daemon._epoch, self.daemon._scheduling_epoch,
            readiness_binding, admission.cancellation_operation_id,
            _reuse_authority_binding(snapshot, stage_plan),
        )
        context: _ReuseContext | None = None
        proof = self._reuse_proofs.get(key)
        if proof is not None and proof.context_token != token:
            if proof.future is not None and not proof.future.done():
                return revision
            del self._reuse_proofs[key]
            proof = None
        if proof is not None:
            if proof.future is not None and not proof.future.done():
                return revision
            context = proof.context
        else:
            context_pending = self._contexts.get(key)
            if context_pending is not None:
                if not context_pending.future.done():
                    return revision
                del self._contexts[key]
                if context_pending.token == token:
                    timings.observe(context_pending.timings.payload())
                    try:
                        context = context_pending.future.result()
                    except _InputUnavailable as exc:
                        stages = {stage.stage_name: stage for stage in snapshot.stages}
                        return authority.transition_stage(
                            run_uri, node,
                            from_status=None if node not in stages else stages[node].status,
                            to_status=StageStatus.FAILED, expected_revision=revision,
                            reason=LifecycleReason(code="action.input_unavailable", detail=exc.detail),
                        ).revision
                    if context is None:
                        return None
            if context is None:
                if len(self._contexts) >= 2:
                    return revision
                worker_timings = PhaseTimings()
                future = self.daemon._result_verifications.bulk.submit(
                    run_uri + ":" + node, "reuse_context_preparation", self._load_reuse_context,
                    run_uri, intent, stage_plan, snapshot, worker_timings,
                )
                if future is not None:
                    self._contexts[key] = _PendingReuseContext(token, future, worker_timings)
                return revision
        spec = intent.pipeline.get_stage(node)
        implementation, contract, identity = context.implementation, context.contract, context.identity
        report = {"operation_id": context.operation_id}
        with self.daemon._connection() as conn:
            source = conn.execute(
                "SELECT principal_id, selected_json FROM preparation_operations WHERE operation_id = ?",
                (report["operation_id"],),
            ).fetchone()
        if source is None:
            raise QueueConflictError("action preparation scope is unavailable")
        scope = {
            "principal_id": str(source["principal_id"]),
            "authority": coordinator_authority_identity(
                self.daemon.config.coordinator_authority_factory
            ),
            "store_root": self.daemon.config.run_store_root.as_uri(),
            "installation": dict(implementation),
        }
        selected = timings.call("reuse_lookup", self.store.select,
            run_uri=run_uri,
            node=node,
            scope=scope,
            identity=identity,
            attempt_id=f"{node}-{readiness.next_attempt}",
            retry_authorized=readiness.retry_decision_id is not None
            or readiness.expected_stage_status is StageStatus.STALE,
        )
        claim = selected["claim"]
        timings.call("reuse_retention", self._retain, claim)
        if selected["decision"] == "owner":
            self._reuse_proofs.pop(key, None)
            timings.call("reuse_producer_binding", authority.bind_action_producer, run_uri, self._producer_binding(claim))
            return None
        if selected["decision"] == "wait":
            timings.call("reuse_producer_observation", self._observe_waiting_producer, key, claim)
            selected = timings.call("reuse_lookup", self.store.select,
                run_uri=run_uri, node=node, scope=scope, identity=identity
            )
            claim = selected["claim"]
        if selected["decision"] == "wait":
            self._reuse_proofs.pop(key, None)
            return revision
        if selected["decision"] == "failed":
            self._reuse_proofs.pop(key, None)
            return self._reject(
                authority, snapshot, run_uri, node, revision, claim, "action.producer_failed"
            )
        if selected["decision"] == "bound":
            try:
                if not self._verify_reuse_async(
                    key, token, context, claim, plain_mapping(selected["binding"]["result"]), timings,
                ):
                    return revision
            except (ArtifactStoreError, OSError, QueueConflictError):
                return self._reject(
                    authority, snapshot,
                    run_uri,
                    node,
                    revision,
                    claim,
                    "action.candidate_unavailable",
                )
            return timings.call("reuse_authority_binding", authority.bind_action_result,
                run_uri,
                node,
                ActionResultBinding.from_dict(selected["binding"]),
                expected_revision=revision,
            )
        result = plain_mapping(json.loads(claim["result_json"]))
        try:
            if not self._verify_reuse_async(key, token, context, claim, result, timings):
                return revision
        except (ArtifactStoreError, OSError, QueueConflictError):
            return self._reject(
                authority, snapshot,
                run_uri,
                node,
                revision,
                claim,
                "action.candidate_unavailable",
            )
        candidate: dict[str, PlainData] = {
            "schema_version": 1,
            "namespace": plain_mapping(contract)["namespace"],
            "semantic_key": plain_mapping(contract)["semantic_key"],
            "execution_key": claim["execution_key"],
            "producer": {
                "run_uri": claim["owner_run_uri"],
                "node_id": claim["owner_node"],
                "attempt_id": claim["attempt_id"],
                "assignment_id": claim["assignment_id"],
                "fencing_token": claim["fencing_token"],
            },
            "result": result,
            "output_contracts": {
                port: _output_spec_identity(output)
                for port, output in spec.outputs.items()
            },
            "installation": dict(implementation),
            "access": {
                "mode": "read_only",
                "artifact_root": str(
                    self.execution.run_store.local_artifact_root(claim["owner_run_uri"])
                ),
            },
        }
        from loom.pipeline._project_contracts import CONTRACTS, report_entry
        from loom.pipeline.stores.shared_artifacts import binding as shared_binding
        reports = {}
        for label, source_uri in (("producer", claim["owner_run_uri"]), ("desired", run_uri)):
            prepared = self.execution.run_store.read_prepared_run(source_uri)
            reference = report_entry(prepared["metadata"][CONTRACTS])["report_ref"]
            if shared_binding(ArtifactRef.from_dict(reference).metadata) is not None:
                reports[label] = reference
        if reports:
            candidate["access"] = {**plain_mapping(candidate["access"]), "project_reports": reports}
        candidate["candidate_digest"] = hash_mapping(candidate)
        candidate = action_candidate(candidate)
        verification = timings.call("reuse_verifier_observation", self.daemon._preparations.verify_action_result,
            source_operation_id=cast(str, report["operation_id"]),
            consumer_run_uri=run_uri,
            node_id=node,
            contract=plain_mapping(contract),
            candidate=candidate,
            timings=timings,
        )
        if isinstance(verification, _PendingActionVerification):
            if len(self._pending) >= 256:
                self._pending.pop(next(iter(self._pending)))
            self._pending[key] = _PendingReuse(
                readiness_binding, claim["claim_id"], claim["revision"], verification,
                monotonic() + 30.0,
            )
            return revision
        if verification["failure_code"] is not None:
            return self._reject(
                authority, snapshot, run_uri, node, revision, claim, "action.verification_invalid"
            )
        verdict = action_verification_response(verification["verification"], candidate)
        if verdict["verdict"] == "rejected":
            return self._reject(
                authority, snapshot,
                run_uri,
                node,
                revision,
                claim,
                "action.project_rejected",
                {"namespace": candidate["namespace"], "reason": verdict["reason"]},
            )
        # This resolution has just consumed a fresh byte audit. A pending
        # project verifier returns above and requires a new audit on resumption.
        # Recheck mutable authority, retention and principal before binding.
        try:
            self._checked_result_outputs(claim, result, timings=timings)
        except (ArtifactStoreError, OSError, QueueConflictError):
            return self._reject(
                authority, snapshot,
                run_uri,
                node,
                revision,
                claim,
                "action.candidate_unavailable",
            )
        with self.daemon._connection() as conn:
            current = conn.execute(
                "SELECT principal_id FROM preparation_operations WHERE operation_id = ?",
                (report["operation_id"],),
            ).fetchone()
        if current is None or current["principal_id"] != source["principal_id"]:
            raise QueueConflictError("action authorization changed before binding")
        binding = timings.call("reuse_binding", self.store.bind,
            run_uri=run_uri,
            node=node,
            claim_id=claim["claim_id"],
            expected_revision=claim["revision"],
            result=result,
            verification=verdict,
        )
        return timings.call("reuse_authority_binding", authority.bind_action_result,
            run_uri,
            node,
            ActionResultBinding.from_dict(binding),
            expected_revision=revision,
        )

    def _load_reuse_context(
        self, run_uri: str, intent: Any, stage_plan: Any, snapshot: Any,
        timings: PhaseTimings,
    ) -> _ReuseContext | None:
        node = stage_plan.stage_name
        spec = intent.pipeline.get_stage(node)
        report = timings.call("reuse_contract_loading", load_contract_report, self.execution.run_store, run_uri, config=self.execution.run_store, local_paths=self.execution.run_store)
        if report is None:
            return None
        implementation = _report_implementation(report, intent.execution_requirements[node], spec)
        if implementation is None:
            return None
        contract = _worker_contract_metadata(report, spec)[
            CONTRACT
        ]
        stages = {stage.stage_name: stage for stage in snapshot.stages}
        inputs = {}
        for input_ in (*stage_plan.bound_inputs.values(), *stage_plan.pending_inputs):
            source = stages.get(input_.source_stage)
            if source is None or source.latest_commit is None:
                return None
            fact = next(
                (
                    fact
                    for fact in source.artifact_facts
                    if fact.artifact_name == input_.source_output
                ),
                None,
            )
            if fact is None:
                raise QueueConflictError("action input has no original output fact")
            try:
                timings.call("reuse_artifact_verification", self._verify_artifact, fact.artifact)
            except (ArtifactStoreError, OSError, QueueConflictError):
                raise _InputUnavailable(input_.input_name, fact.artifact) from None
            inputs[input_.input_name] = {
                "commit": source.latest_commit.to_dict(),
                "output_port": input_.source_output,
                "artifact": fact.artifact.to_dict(),
            }
        identity = action_execution_identity(
            spec,
            plain_mapping(contract),
            implementation=implementation,
            inputs=inputs,
            generation=cast(
                str, plain_mapping(report.get("generations", {})).get(node, "default")
            ),
        )
        if identity is None:
            return None
        return _ReuseContext(
            cast(str, report["operation_id"]), implementation, plain_mapping(contract), identity,
        )

    def _observe(self, claim: Mapping[str, Any], authority: Any, snapshot: AuthoritativeRunSnapshot | None) -> None:
        if snapshot is not None:
            self._observe_result(claim, authority, snapshot)
        current = self.store.claim(claim["claim_id"])
        if (current["state"] != "owned" and current["attempt_id"] is not None
                and current["attempt_id"] == claim["attempt_id"]):
            authority.release_action_producer(
                current["owner_run_uri"], self._producer_binding(current)
            )

    def _observe_result(self, claim: Mapping[str, Any], authority: Any, snapshot: AuthoritativeRunSnapshot) -> None:
        if claim["state"] not in {"owned", "settling"}:
            return
        stage = next(
            (
                stage
                for stage in snapshot.stages
                if stage.stage_name == claim["owner_node"]
            ),
            None,
        )
        if stage is None:
            return
        if (
            snapshot.status in {RunStatus.FAILED, RunStatus.INTERRUPTED}
            and stage.status is StageStatus.PENDING
        ):
            # Authority settles the exact unstarted attempt with its permission,
            # so ordinary explicit retry can create a successor consistently.
            authority.release_action_producer(
                claim["owner_run_uri"], self._producer_binding(claim)
            )
            self.store.fail(
                claim["claim_id"],
                {"code": "producer_abandoned"},
                expected_revision=claim["revision"],
            )
            return
        if stage.status is StageStatus.SUCCEEDED and stage.latest_commit is not None:
            result = {
                "commit": stage.latest_commit.to_dict(),
                "artifact_facts": [fact.to_dict() for fact in stage.artifact_facts],
            }
            try:
                outputs = self._checked_result_outputs(claim, result, snapshot=snapshot)
            except (ArtifactStoreError, OSError, QueueConflictError):
                self.store.fail(claim["claim_id"], {"code": "candidate_unavailable"},
                                expected_revision=claim["revision"])
                return
            self.daemon._result_verifications.submit(
                claim, (self.daemon._epoch, self.daemon._scheduling_epoch), result,
                outputs, self._verify_artifacts,
            )
        elif stage.status in {StageStatus.FAILED, StageStatus.CANCELLED}:
            self.store.fail(
                claim["claim_id"],
                {"code": "producer_failed"},
                expected_revision=claim["revision"],
            )

    def _retain(self, claim: Mapping[str, Any]) -> None:
        retain_preparation_path(
            self.execution.run_store.local_run_dir(claim["owner_run_uri"]),
            coordinator_id=self.execution.coordinator_id,
            operation_id="action-" + claim["claim_id"],
        )

    def _verify_reuse_async(
        self, key: tuple[str, str], token: tuple[Any, ...], context: _ReuseContext,
        claim: Mapping[str, Any], result: Mapping[str, PlainData], timings: PhaseTimings,
    ) -> bool:
        claim_token = tuple(claim[name] for name in (
            "claim_id", "revision", "owner_run_uri", "owner_node",
            "attempt_id", "assignment_id", "fencing_token",
        )) + (result,)
        pending = self._reuse_proofs.get(key)
        if pending is not None and pending.future is not None:
            if not pending.future.done():
                return False
            del self._reuse_proofs[key]
            if pending.context_token == token and pending.claim_token == claim_token:
                timings.observe(pending.timings.payload())
                pending.future.result()
                return True
        if key not in self._reuse_proofs and len(self._reuse_proofs) >= 2:
            return False
        worker_timings = PhaseTimings()
        def verify():
            outputs = self._checked_result_outputs(claim, result, timings=worker_timings)
            worker_timings.call("reuse_artifact_verification", self._verify_artifacts, outputs)
            # Bytes and original authority can change independently during the
            # audit. A completed proof includes a fresh retention/commit check.
            self._checked_result_outputs(claim, result, timings=worker_timings)

        future = self.daemon._result_verifications.bulk.submit(
            key[0] + ":" + key[1], "reuse_result_verification", verify,
        )
        self._reuse_proofs[key] = _PendingReuseProof(token, context, claim_token, future, worker_timings)
        return False

    def complete_verifications(self) -> None:
        self.daemon._result_verifications.advance(self._apply_verified_producer)

    def _apply_verified_producer(self, completed: PendingResult) -> None:
        from ._coordinator_transactions import short_write

        claim, result = completed.claim, completed.result
        def current_owner():
            return (self.daemon._execution is self.execution and not self.daemon._stop.is_set()
                    and completed.epochs == (self.daemon._epoch, self.daemon._scheduling_epoch))

        with phase("action_result_completion_apply", operation_id=str(claim["claim_id"])):
            if not current_owner() or self.store.claim(claim["claim_id"])["revision"] != claim["revision"]:
                return
            try:
                completed.future.result()
                self._checked_result_outputs(claim, result)
                failure = None
            except (ArtifactStoreError, OSError, QueueConflictError):
                failure = {"code": "candidate_unavailable", "original_result": result}

            def commit(conn):
                # Reload, shutdown, demand detachment, or retry can win during
                # verification. No filesystem or authority read runs in this guard.
                if current_owner():
                    self.store.settle_verified_in(conn, claim, result, failure)

            short_write(self.daemon, commit)

    def _checked_result_outputs(
        self, claim: Mapping[str, Any], result: Mapping[str, PlainData],
        *, timings: PhaseTimings | None = None, snapshot: AuthoritativeRunSnapshot | None = None,
    ) -> dict[str, ArtifactRef]:
        with phase("action_result_verification"):
            timings = timings or PhaseTimings()
            uri = claim["owner_run_uri"]
            if not preparation_path_is_retained(
                self.execution.run_store.local_run_dir(uri)
            ):
                raise QueueConflictError("action result retention is unavailable")
            if snapshot is None:
                snapshot = timings.call("reuse_authority_read", self.execution._authority_store(uri).open_run, uri)
            assert snapshot is not None
            stage = next(
                (
                    stage
                    for stage in snapshot.stages
                    if stage.stage_name == claim["owner_node"]
                ),
                None,
            )
            if (
                stage is None
                or stage.status is not StageStatus.SUCCEEDED
                or stage.result_binding is not None
                or stage.latest_commit is None
                or stage.latest_commit.attempt_id != claim["attempt_id"]
            ):
                raise QueueConflictError(
                    "action candidate has no original successful producer"
                )
            if {
                "commit": stage.latest_commit.to_dict(),
                "artifact_facts": [fact.to_dict() for fact in stage.artifact_facts],
            } != result:
                raise QueueConflictError("action candidate original authority changed")
            return {fact.artifact_name: fact.artifact for fact in stage.artifact_facts}

    def _verify_artifacts(self, outputs: Mapping[str, ArtifactRef]) -> None:
        from ._shared_publication import verify_outputs

        verify_outputs(outputs)
        for ref in outputs.values():
            if shared_binding(ref.metadata) is None:
                self._verify_artifact(ref)

    def _verify_artifact(self, ref: ArtifactRef) -> None:
        path = uri_to_path(ref.uri)
        if shared_binding(ref.metadata) is not None:
            verify_ref(ref, path)
        elif not LocalArtifactStore(self.daemon.config.run_store_root).verify_checksum(
            ref
        ):
            raise QueueConflictError("action artifact integrity is unavailable")

    @staticmethod
    def _reject(
        authority: Any,
        snapshot: AuthoritativeRunSnapshot,
        run_uri: str,
        node: str,
        revision: Any,
        claim: Mapping[str, Any],
        code: str,
        detail: Mapping[str, PlainData] | None = None,
    ) -> Any:
        current = next(
            (
                stage.status
                for stage in snapshot.stages
                if stage.stage_name == node
            ),
            None,
        )
        return authority.transition_stage(
            run_uri,
            node,
            from_status=current,
            to_status=StageStatus.FAILED,
            expected_revision=revision,
            reason=LifecycleReason(
                code=code,
                detail={
                    "claim_id": claim["claim_id"],
                    "origin_run_uri": claim["owner_run_uri"],
                    "origin_node_id": claim["owner_node"],
                    "original_result": None
                    if claim["result_json"] is None
                    else json.loads(claim["result_json"]),
                    "producer_failure": None
                    if claim["failure_json"] is None
                    else json.loads(claim["failure_json"]),
                    **dict(detail or {}),
                },
            ),
        ).revision


def _reuse_authority_binding(snapshot: Any, stage_plan: Any) -> tuple[Any, ...]:
    # Run-wide revisions include diagnostic events and unrelated stage work.
    # Only the desired stage and its scientific input producers qualify this read.
    names = {stage_plan.stage_name} | {
        item.source_stage for item in (*stage_plan.bound_inputs.values(), *stage_plan.pending_inputs)
    }
    stages = {stage.stage_name: stage for stage in snapshot.stages}
    return (snapshot.status, tuple(
        (name, StageStatus.PENDING, (), None, (), None) if (stage := stages.get(name)) is None
        else (name, stage.status, stage.attempts, stage.latest_commit, stage.artifact_facts, stage.result_binding)
        for name in sorted(names)
    ))


def _report_implementation(report: Mapping[str, PlainData], requirement: Any, stage: Any) -> dict[str, PlainData] | None:
    """Join committed preparation implementation to this admitted action."""
    from .submitted_execution import SUBMITTED_EXECUTION_SCOPE, submitted_binding, submitted_implementation

    if "execution" in report:
        binding = {key: report[key] for key in ("execution", "container_capability")}
        execution, capability = submitted_binding(binding)
        from .submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
        if execution.worker_contract == SELECTED_INPUT_WORKER_CONTRACT:
            from .shared_execution import SHARED_EXECUTION_SCOPE
            selected = plain_mapping(stage.fingerprint_fields[SHARED_EXECUTION_SCOPE])
            capability = capability.select_roots(plain_mapping(selected["roots"]))
        if requirement != capability.requirement(execution) or submitted_binding(stage.fingerprint_fields.get(SUBMITTED_EXECUTION_SCOPE)) != (execution, capability):
            raise QueueConflictError("action implementation differs from admitted execution")
        if execution.project_integration != plain_mapping(report["project_preparation"])["processor"]:
            raise QueueConflictError("action integration differs from submitted execution")
        return submitted_implementation(execution, capability)
    descriptor = plain_mapping(report["profile_descriptor"])
    if not descriptor.get("action_reuse_qualified", False):
        return None
    required = requirement.to_dict()
    if any(descriptor[key] != value for key, value in required.items()):
        raise QueueConflictError("action installation differs from admitted execution")
    return {**required, "processor": plain_mapping(report["project_preparation"])["processor"]}
