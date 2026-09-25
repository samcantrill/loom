"""Capability-narrow authority contract used by coordinator execution.

This module deliberately owns only the structural contract. Concrete embedded
and authenticated adapters live with pipeline stores, so queue execution never
constructs a database implementation or gains a generic repository view.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from loom.runs.annotations import RunNote, RunNotePage
from typing import Protocol, runtime_checkable

from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.event_sinks import EventSinkFailureRecord, EventObserverLinkRecord

from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import (
    ActionProducerBinding,
    CancellationEpochReceipt,
    CoordinatorAdmissionRequest,
    LocalDaemonAuthority,
    PreparedAttemptExecutionAuthority,
    StatusTransition,
)
from loom.pipeline.stores.read_models import (
    ActionResultBinding,
    AuthoritativeRunSnapshot,
    BackendRevision,
    LifecycleReason,
    ReliabilityPolicyFact,
)
from loom.pipeline.transition_policy import TransitionIntent
from loom.runs.context import RunAnnotations, SubmissionContext


@runtime_checkable
class CoordinatorAuthorityStore(
    PreparedAttemptExecutionAuthority,
    LocalDaemonAuthority,
    Protocol,
):
    """Exact authority capabilities reached by production coordination.

    The protocol intentionally excludes discovery, schema management, leases,
    arbitrary repository access, and database construction.
    """

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord: ...

    def list_audit_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]: ...

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> BackendRevision: ...

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]: ...

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> BackendRevision: ...

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]: ...

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def initialize_run_annotations(self, run_uri: str, context: SubmissionContext,
                                   operation_id: str | None, coordinator_id: str | None) -> RunAnnotations: ...

    def read_run_annotations(self, run_uri: str) -> RunAnnotations | None: ...

    def mutate_run_annotations(self, run_uri: str, principal: str, mutation_id: str,
                               operation: str, change: Mapping[str, object],
                               legacy_context: SubmissionContext, legacy_notes: tuple[str, ...] = ()) -> RunAnnotations | RunNote: ...

    def list_run_notes(self, run_uri: str, limit: int = 50, cursor: str | None = None,
                       legacy_notes: tuple[str, ...] = ()) -> RunNotePage: ...

    def bind_action_result(
        self, run_uri: str, stage_name: str, binding: ActionResultBinding,
        *, expected_revision: BackendRevision | None = None,
    ) -> BackendRevision: ...

    def bind_action_producer(self, run_uri: str, binding: ActionProducerBinding) -> None: ...

    def release_action_producer(self, run_uri: str, binding: ActionProducerBinding) -> None: ...

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def read_cancellation_epoch_receipt(
        self, run_uri: str, operation_id: str
    ) -> CancellationEpochReceipt | None: ...

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision: ...

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]: ...

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision: ...

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]: ...

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision: ...

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]: ...

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision: ...

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]: ...

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision: ...

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]: ...


CoordinatorAuthorityFactory = Callable[[str], CoordinatorAuthorityStore]


@runtime_checkable
class ManagedAdmissionRetryAuthority(Protocol):
    """Optional atomic continuation capability for the embedded managed owner."""

    def resume_failed_admission(
        self,
        run_uri: str,
        *,
        admission: CoordinatorAdmissionRequest,
        operation_id: str,
        expected_revision: BackendRevision,
        stage_names: tuple[str, ...],
    ) -> BackendRevision: ...


__all__ = [
    "CoordinatorAuthorityFactory",
    "CoordinatorAuthorityStore",
]
