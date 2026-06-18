"""In-memory conformance stores for v9 authority contract tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.event_sinks import EventObserverLinkRecord, EventSinkFailureRecord
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.pipeline.stores import (
    AUTHORITY_SCHEMA_VERSION,
    AttemptAllocation,
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    CleanupCandidate,
    CleanupReportFact,
    CleanupResultFact,
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    OutputCommit,
    OutputCommitRecord,
    PerRunAuthorityStore,
    RecoveryKind,
    RecoveryRecord,
    ReliabilityPolicyFact,
    ResourceLeaseRecord,
    StageAttempt,
    StageLifecycleSnapshot,
    StatusTransition,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    WorkspaceCoordinationStore,
    WorkspaceIdentity,
    check_authority_schema_version,
)
from loom.pipeline.stores.reliability_facts import (
    reliability_payload_matches,
    reliability_policy_fact_key,
    reliability_record_stage_name,
    reliability_status_detail_key,
    validate_policy_fact_run,
    validate_retry_decision_run,
    validate_status_detail_run,
    validate_timeout_outcome_run,
    validate_transaction_run,
)
from loom.serialization import PlainData


@dataclass(slots=True)
class _RunState:
    run_uri: str
    status: RunStatus
    revision: BackendRevision
    stage_statuses: dict[str, StageStatus] = field(default_factory=dict)
    attempts: dict[str, list[StageAttempt]] = field(default_factory=dict)
    leases: dict[str, LeaseRecord] = field(default_factory=dict)
    submitted: dict[str, SubmittedOperationRecord] = field(default_factory=dict)
    commits: dict[str, OutputCommitRecord] = field(default_factory=dict)
    facts: dict[str, list[ArtifactFactRecord]] = field(default_factory=dict)
    cleanup: list[CleanupCandidate] = field(default_factory=list)
    cleanup_reports: dict[str, CleanupReportFact] = field(default_factory=dict)
    cleanup_results: dict[str, CleanupResultFact] = field(default_factory=dict)
    events: list[PipelineEventRecord] = field(default_factory=list)
    event_sink_failures: list[EventSinkFailureRecord] = field(default_factory=list)
    event_observer_links: list[EventObserverLinkRecord] = field(default_factory=list)
    reliability_policy_facts: dict[str, ReliabilityPolicyFact] = field(
        default_factory=dict
    )
    reliability_status_details: dict[str, ReliabilityStatusDetail] = field(
        default_factory=dict
    )
    reliability_transactions: dict[str, StageAttemptTransaction] = field(
        default_factory=dict
    )
    retry_decisions: dict[str, RetryDecisionRecord] = field(default_factory=dict)
    timeout_outcomes: dict[str, TimeoutOutcomeRecord] = field(default_factory=dict)


class InMemoryPerRunAuthorityStore(PerRunAuthorityStore):
    def __init__(self) -> None:
        self._runs: dict[str, _RunState] = {}
        self._revision = 0
        self._tick = 0
        self._lease_expiry_ticks: dict[str, int] = {}

    def capabilities(self) -> BackendCapabilitySet:
        return BackendCapabilitySet(
            backend_name="in-memory-authority-test-store",
            records=tuple(
                BackendCapabilityRecord(
                    capability=capability,
                    scope=CapabilityScope.PER_RUN,
                )
                for capability in (
                    BackendCapability.RUN_ADMISSION,
                    BackendCapability.ATOMIC_TRANSITIONS,
                    BackendCapability.ATTEMPT_ALLOCATION,
                    BackendCapability.RUN_LEASES,
                    BackendCapability.STAGE_LEASES,
                    BackendCapability.LEASE_TTL,
                    BackendCapability.FENCING_TOKENS,
                    BackendCapability.BACKEND_LEASE_TIME,
                    BackendCapability.ATOMIC_OUTPUT_COMMIT,
                    BackendCapability.ARTIFACT_FACTS,
                    BackendCapability.RELIABILITY_FACTS,
                    BackendCapability.SUBMITTED_OPERATIONS,
                    BackendCapability.REVISIONED_SNAPSHOTS,
                    BackendCapability.MONOTONIC_REVISIONS,
                    BackendCapability.RECOVERY_SCANS,
                    BackendCapability.CONSISTENT_READS,
                    BackendCapability.TRANSACTION_ISOLATION,
                    BackendCapability.CLOCK_SEMANTICS,
                    BackendCapability.MATERIALIZATION_REFS,
                    BackendCapability.AUDIT_EVENTS,
                    BackendCapability.PER_RUN_COORDINATION,
                    BackendCapability.SINGLE_HOST_AUTHORITY,
                )
            ),
        )

    def check_schema(self, run_uri: str):
        self._require_run(run_uri)
        return check_authority_schema_version(
            {"schema_version": AUTHORITY_SCHEMA_VERSION}
        )

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision:
        if run_uri in self._runs:
            raise ValueError(f"run already exists: {run_uri}")
        revision = self._next_revision()
        self._runs[run_uri] = _RunState(run_uri, RunStatus(status), revision)
        return revision

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return self.snapshot(run_uri)

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        state = self._require_run(run_uri)
        if state.status is not from_status:
            raise ValueError("stale run transition")
        previous = state.status
        state.status = to_status
        state.revision = self._next_revision()
        return StatusTransition(
            run_uri=run_uri,
            previous_status=previous,
            status=to_status,
            revision=state.revision,
            reason=reason,
        )

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        state = self._require_run(run_uri)
        current = state.stage_statuses.get(stage_name)
        if current is not from_status:
            raise ValueError("stale stage transition")
        state.stage_statuses[stage_name] = to_status
        state.revision = self._next_revision()
        return StatusTransition(
            run_uri=run_uri,
            stage_name=stage_name,
            previous_status=current,
            status=to_status,
            revision=state.revision,
            reason=reason,
        )

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        state = self._require_run(run_uri)
        if (
            lease_ttl_seconds is not None
            and self._active_stage_lease(state, stage_name) is not None
        ):
            raise ValueError("stage already has an active lease")
        attempt_number = len(state.attempts.get(stage_name, ())) + 1
        revision = self._next_revision()
        attempt = StageAttempt(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt_number,
            attempt_id=f"{stage_name}-{attempt_number}",
            status=StageStatus.RUNNING,
            revision=revision,
            created_at=self._now(),
            owner=owner_id,
        )
        state.attempts.setdefault(stage_name, []).append(attempt)
        state.stage_statuses[stage_name] = StageStatus.RUNNING
        lease = None
        if lease_ttl_seconds is not None:
            lease = self._new_lease(
                state,
                kind=LeaseKind.STAGE,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                stage_name=stage_name,
                attempt_id=attempt.attempt_id,
            )
        return AttemptAllocation(attempt=attempt, lease=lease)

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        state = self._require_run(run_uri)
        return self._new_lease(
            state,
            kind=LeaseKind.CONTROLLER,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        state, lease = self._require_lease(lease_id, owner_id, fencing_token)
        renewed = self._replace_lease(
            state,
            lease,
            renewed_at=self._now(),
            expires_at=self._at_tick(self._tick + lease_ttl_seconds),
            revision=self._next_revision(),
        )
        self._lease_expiry_ticks[lease_id] = self._tick + lease_ttl_seconds
        return renewed

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        state, lease = self._require_lease(lease_id, owner_id, fencing_token)
        return self._replace_lease(
            state,
            lease,
            state_value=LeaseState.RELEASED,
            revision=self._next_revision(),
            reason=reason,
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        state, lease = self._require_lease(lease_id, owner_id, fencing_token)
        return self._replace_lease(
            state,
            lease,
            state_value=LeaseState.FAILED,
            revision=self._next_revision(),
            reason=reason,
        )

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        state.submitted[record.submission_id] = record
        state.revision = self._next_revision()
        return state.revision

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        return self._require_run(run_uri).submitted.get(submission_id)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        return tuple(self._require_run(run_uri).submitted.values())

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        validate_policy_fact_run(fact, run_uri)
        return self._store_immutable_reliability_fact(
            state.reliability_policy_facts,
            reliability_policy_fact_key(fact),
            fact,
            state,
        )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        facts = self._require_run(run_uri).reliability_policy_facts.values()
        return tuple(
            sorted(
                (
                    fact
                    for fact in facts
                    if stage_name is None or fact.stage_name == stage_name
                ),
                key=lambda fact: (
                    fact.scope.value,
                    fact.stage_name or "",
                    fact.attempt or 0,
                    fact.recorded_at,
                ),
            )
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        validate_status_detail_run(detail, run_uri)
        return self._store_immutable_reliability_fact(
            state.reliability_status_details,
            reliability_status_detail_key(detail),
            detail,
            state,
        )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._stage_reliability_records(
            self._require_run(run_uri).reliability_status_details.values(),
            stage_name=stage_name,
            sort_key=lambda detail: (detail.stage_id, detail.attempt, detail.created_at),
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        validate_transaction_run(transaction, run_uri)
        return self._store_immutable_reliability_fact(
            state.reliability_transactions,
            transaction.transaction_id,
            transaction,
            state,
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        transactions = self._require_run(run_uri).reliability_transactions
        current = transactions.get(transaction_id)
        if current is None:
            return ()
        chain: list[StageAttemptTransaction] = []
        seen: set[str] = set()
        while current is not None:
            if current.transaction_id in seen:
                raise ValueError("reliability transaction chain contains a cycle")
            seen.add(current.transaction_id)
            chain.append(current)
            parent_id = current.causal_parent_id
            current = None if parent_id is None else transactions.get(parent_id)
        return tuple(reversed(chain))

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._stage_reliability_records(
            self._require_run(run_uri).reliability_transactions.values(),
            stage_name=stage_name,
            sort_key=lambda transaction: (
                transaction.stage_id,
                transaction.attempt,
                transaction.transaction_id,
            ),
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        validate_retry_decision_run(decision, run_uri)
        return self._store_immutable_reliability_fact(
            state.retry_decisions,
            decision.decision_id,
            decision,
            state,
        )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return self._stage_reliability_records(
            self._require_run(run_uri).retry_decisions.values(),
            stage_name=stage_name,
            sort_key=lambda decision: (
                decision.status.stage_id,
                decision.status.attempt,
                decision.decision_id,
            ),
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        validate_timeout_outcome_run(outcome, run_uri)
        return self._store_immutable_reliability_fact(
            state.timeout_outcomes,
            outcome.outcome_id,
            outcome,
            state,
        )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._stage_reliability_records(
            self._require_run(run_uri).timeout_outcomes.values(),
            stage_name=stage_name,
            sort_key=lambda outcome: (
                outcome.status.stage_id,
                outcome.status.attempt,
                outcome.outcome_id,
            ),
        )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        state = self._require_run(run_uri)
        self._require_stage_fence(state, stage_name, attempt_id, fencing_token)
        revision = self._next_revision()
        commit = OutputCommitRecord(
            commit_id=f"{stage_name}-{attempt_id}-commit",
            run_uri=run_uri,
            stage_name=stage_name,
            attempt_id=attempt_id,
            committed_at=self._now(),
            revision=revision,
            output_names=tuple(outputs),
        )
        facts = tuple(
            ArtifactFactRecord(
                artifact_name=name,
                artifact=artifact,
                commit_id=commit.commit_id,
                revision=revision,
            )
            for name, artifact in outputs.items()
        )
        state.commits[stage_name] = commit
        state.facts[stage_name] = list(facts)
        state.attempts[stage_name] = [
            StageAttempt(
                run_uri=attempt.run_uri,
                stage_name=attempt.stage_name,
                attempt=attempt.attempt,
                attempt_id=attempt.attempt_id,
                status=StageStatus.SUCCEEDED
                if attempt.attempt_id == attempt_id
                else attempt.status,
                revision=revision
                if attempt.attempt_id == attempt_id
                else attempt.revision,
                created_at=attempt.created_at,
                owner=attempt.owner,
                reason=reason if attempt.attempt_id == attempt_id else attempt.reason,
            )
            for attempt in state.attempts.get(stage_name, ())
        ]
        state.stage_statuses[stage_name] = StageStatus.SUCCEEDED
        state.revision = revision
        return OutputCommit(commit=commit, artifact_facts=facts)

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord:
        state = self._require_run(run_uri)
        record = PipelineEventRecord(
            run_uri=run_uri,
            sequence=len(state.events) + 1,
            timestamp=self._now(),
            scope=event.scope,
            event_type=event.event_type,
            payload=event.payload,
        )
        state.events.append(record)
        state.revision = self._next_revision()
        return record

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        if failure.run_uri != run_uri:
            raise ValueError("event sink failure run_uri does not match run")
        state.event_sink_failures.append(failure)
        state.revision = self._next_revision()
        return state.revision

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]:
        return tuple(self._require_run(run_uri).event_sink_failures)

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> BackendRevision:
        state = self._require_run(run_uri)
        if link.run_uri != run_uri:
            raise ValueError("event observer link run_uri does not match run")
        state.event_observer_links.append(link)
        state.revision = self._next_revision()
        return state.revision

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]:
        return tuple(self._require_run(run_uri).event_observer_links)

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        state = self._require_run(run_uri)
        stage_names = set(state.stage_statuses)
        stage_names.update(state.attempts)
        stage_names.update(state.commits)
        stage_names.update(
            fact.stage_name
            for fact in state.reliability_policy_facts.values()
            if fact.stage_name is not None
        )
        stage_names.update(
            detail.stage_id for detail in state.reliability_status_details.values()
        )
        stage_names.update(
            transaction.stage_id
            for transaction in state.reliability_transactions.values()
        )
        stage_names.update(
            decision.status.stage_id for decision in state.retry_decisions.values()
        )
        stage_names.update(
            outcome.status.stage_id for outcome in state.timeout_outcomes.values()
        )
        stages = tuple(
            StageLifecycleSnapshot(
                stage_name=stage_name,
                status=state.stage_statuses.get(stage_name, StageStatus.PENDING),
                revision=state.revision,
                attempts=tuple(state.attempts.get(stage_name, ())),
                active_lease=self._active_stage_lease(state, stage_name),
                latest_commit=state.commits.get(stage_name),
                artifact_facts=tuple(state.facts.get(stage_name, ())),
                reliability_policy_facts=self.list_reliability_policy_facts(
                    run_uri,
                    stage_name=stage_name,
                ),
                reliability_status_details=self.list_reliability_status_details(
                    run_uri,
                    stage_name=stage_name,
                ),
                reliability_transactions=self.list_stage_attempt_transactions(
                    run_uri,
                    stage_name=stage_name,
                ),
                retry_decisions=self.list_retry_decisions(
                    run_uri,
                    stage_name=stage_name,
                ),
                timeout_outcomes=self.list_timeout_outcomes(
                    run_uri,
                    stage_name=stage_name,
                ),
            )
            for stage_name in sorted(stage_names)
        )
        return AuthoritativeRunSnapshot(
            run_uri=run_uri,
            status=state.status,
            schema_version=AUTHORITY_SCHEMA_VERSION,
            revision=state.revision,
            stages=stages,
            submitted_operations=tuple(state.submitted.values()),
            cleanup_candidates=tuple(state.cleanup),
            cleanup_reports=tuple(state.cleanup_reports.values()),
            cleanup_results=tuple(state.cleanup_results.values()),
            reliability_policy_facts=tuple(
                fact
                for fact in self.list_reliability_policy_facts(run_uri)
                if fact.stage_name is None
            ),
        )

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        state = self._require_run(run_uri)
        records: list[RecoveryRecord] = []
        for lease_id, lease in state.leases.items():
            if lease.state is LeaseState.ACTIVE and (
                self._lease_expiry_ticks.get(lease_id, self._tick + 1) <= self._tick
            ):
                records.append(
                    RecoveryRecord(
                        recovery_id=f"expired-{lease_id}",
                        kind=RecoveryKind.EXPIRED_LEASE,
                        reason=LifecycleReason(code="lease_expired"),
                        detected_at=self._now(),
                        revision=state.revision,
                        run_uri=run_uri,
                        stage_name=lease.stage_name,
                        attempt_id=lease.attempt_id,
                    )
                )
        return tuple(records)

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        return tuple(self._require_run(run_uri).cleanup)

    def append_cleanup_report(
        self, run_uri: str, report: CleanupReport
    ) -> CleanupReportFact:
        if not isinstance(report, CleanupReport):
            raise ValueError("report must be a CleanupReport")
        if report.run_uri != run_uri:
            raise ValueError("cleanup report run_uri does not match run")
        state = self._require_run(run_uri)
        existing = state.cleanup_reports.get(report.report_id)
        if existing is not None:
            if existing.report.to_dict() == report.to_dict():
                return existing
            raise ValueError("conflicting cleanup report already exists")
        state.revision = self._next_revision()
        fact = CleanupReportFact(
            report=report,
            recorded_at=self._now(),
            revision=state.revision,
        )
        state.cleanup_reports[report.report_id] = fact
        return fact

    def list_cleanup_reports(self, run_uri: str) -> tuple[CleanupReportFact, ...]:
        return tuple(self._require_run(run_uri).cleanup_reports.values())

    def append_cleanup_result(
        self, run_uri: str, result: CleanupResult
    ) -> CleanupResultFact:
        if not isinstance(result, CleanupResult):
            raise ValueError("result must be a CleanupResult")
        if result.run_uri != run_uri:
            raise ValueError("cleanup result run_uri does not match run")
        state = self._require_run(run_uri)
        existing = state.cleanup_results.get(result.result_id)
        if existing is not None:
            if existing.result.to_dict() == result.to_dict():
                return existing
            raise ValueError("conflicting cleanup result already exists")
        state.revision = self._next_revision()
        fact = CleanupResultFact(
            result=result,
            recorded_at=self._now(),
            revision=state.revision,
        )
        state.cleanup_results[result.result_id] = fact
        return fact

    def list_cleanup_results(self, run_uri: str) -> tuple[CleanupResultFact, ...]:
        return tuple(self._require_run(run_uri).cleanup_results.values())

    def advance_time(self, seconds: int) -> None:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._tick += seconds

    def _store_immutable_reliability_fact[T](
        self,
        records: dict[str, T],
        key: str,
        record: T,
        state: _RunState,
    ) -> BackendRevision:
        existing = records.get(key)
        if existing is not None:
            existing_payload = getattr(existing, "to_dict")()
            record_payload = getattr(record, "to_dict")()
            if reliability_payload_matches(existing_payload, record_payload):
                return state.revision
            raise ValueError("conflicting reliability fact already exists")
        records[key] = record
        state.revision = self._next_revision()
        return state.revision

    def _stage_reliability_records[T](
        self,
        records: object,
        *,
        stage_name: str | None,
        sort_key: Callable[[T], tuple[object, ...]],
    ) -> tuple[T, ...]:
        values = tuple(cast(tuple[T, ...], records))
        filtered = (
            record
            for record in values
            if stage_name is None
            or reliability_record_stage_name(
                cast(
                    ReliabilityStatusDetail
                    | StageAttemptTransaction
                    | RetryDecisionRecord
                    | TimeoutOutcomeRecord,
                    record,
                )
            )
            == stage_name
        )
        return tuple(sorted(filtered, key=sort_key))

    def _require_run(self, run_uri: str) -> _RunState:
        try:
            return self._runs[run_uri]
        except KeyError as exc:
            raise ValueError(f"unknown run: {run_uri}") from exc

    def _next_revision(self) -> BackendRevision:
        self._revision += 1
        return BackendRevision(
            sequence=self._revision,
            token=f"rev-{self._revision}",
            created_at=self._now(),
        )

    def _new_lease(
        self,
        state: _RunState,
        *,
        kind: LeaseKind,
        owner_id: str,
        lease_ttl_seconds: int,
        stage_name: str | None = None,
        attempt_id: str | None = None,
    ) -> LeaseRecord:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        revision = self._next_revision()
        lease_id = f"lease-{revision.sequence}"
        lease = LeaseRecord(
            lease_id=lease_id,
            kind=kind,
            owner_id=owner_id,
            fencing_token=f"fence-{revision.sequence}",
            acquired_at=self._now(),
            renewed_at=self._now(),
            expires_at=self._at_tick(self._tick + lease_ttl_seconds),
            revision=revision,
            run_uri=state.run_uri,
            stage_name=stage_name,
            attempt_id=attempt_id,
        )
        state.leases[lease_id] = lease
        self._lease_expiry_ticks[lease_id] = self._tick + lease_ttl_seconds
        state.revision = revision
        return lease

    def _require_lease(
        self, lease_id: str, owner_id: str, fencing_token: str
    ) -> tuple[_RunState, LeaseRecord]:
        for state in self._runs.values():
            lease = state.leases.get(lease_id)
            if lease is None:
                continue
            if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
                raise ValueError("stale or foreign lease token")
            if lease.state is not LeaseState.ACTIVE:
                raise ValueError("lease is not active")
            if self._lease_expired(lease):
                raise ValueError("lease has expired")
            return state, lease
        raise ValueError(f"unknown lease: {lease_id}")

    def _replace_lease(
        self,
        state: _RunState,
        lease: LeaseRecord,
        *,
        renewed_at: str | None = None,
        expires_at: str | None = None,
        revision: BackendRevision,
        state_value: LeaseState | None = None,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        updated = LeaseRecord(
            lease_id=lease.lease_id,
            kind=lease.kind,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            renewed_at=renewed_at or lease.renewed_at,
            expires_at=expires_at or lease.expires_at,
            revision=revision,
            state=state_value or lease.state,
            run_uri=lease.run_uri,
            stage_name=lease.stage_name,
            attempt_id=lease.attempt_id,
            reason=reason or lease.reason,
        )
        state.leases[lease.lease_id] = updated
        state.revision = revision
        return updated

    def _require_stage_fence(
        self,
        state: _RunState,
        stage_name: str,
        attempt_id: str,
        fencing_token: str,
    ) -> None:
        for lease in state.leases.values():
            if (
                lease.kind is LeaseKind.STAGE
                and lease.stage_name == stage_name
                and lease.attempt_id == attempt_id
                and lease.fencing_token == fencing_token
            ):
                if self._lease_expired(lease):
                    raise ValueError("stage lease has expired")
                if lease.state is not LeaseState.ACTIVE:
                    raise ValueError("stage lease is not active")
                return
        raise ValueError("missing active stage lease for output commit")

    def _active_stage_lease(
        self, state: _RunState, stage_name: str
    ) -> LeaseRecord | None:
        for lease in state.leases.values():
            if (
                lease.kind is LeaseKind.STAGE
                and lease.stage_name == stage_name
                and lease.state is LeaseState.ACTIVE
                and not self._lease_expired(lease)
            ):
                return lease
        return None

    def _lease_expired(self, lease: LeaseRecord) -> bool:
        return (
            self._lease_expiry_ticks.get(lease.lease_id, self._tick + 1) <= self._tick
        )

    def _now(self) -> str:
        return self._at_tick(self._tick)

    @staticmethod
    def _at_tick(tick: int) -> str:
        value = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=tick)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class InMemoryWorkspaceCoordinationStore(WorkspaceCoordinationStore):
    def __init__(self) -> None:
        self._revision = 0
        self._tick = 0
        self._workspaces: dict[str, WorkspaceIdentity] = {}
        self._sweeps: dict[str, SweepIdentity] = {}
        self._trials: dict[str, dict[str, TrialReference]] = {}
        self._leases: dict[str, LeaseRecord] = {}
        self._trial_leases: dict[str, TrialLeaseRecord] = {}
        self._resource_leases: dict[str, ResourceLeaseRecord] = {}
        self._lease_expiry_ticks: dict[str, int] = {}
        self._counters: dict[tuple[str, str], ConcurrencyCounter] = {}
        self._resource_limits: dict[tuple[str, str], int] = {}
        self._resource_limit_revisions: dict[tuple[str, str], BackendRevision] = {}

    def capabilities(self) -> BackendCapabilitySet:
        return BackendCapabilitySet(
            backend_name="in-memory-workspace-test-store",
            records=tuple(
                BackendCapabilityRecord(
                    capability=capability,
                    scope=CapabilityScope.CROSS_RUN,
                )
                for capability in (
                    BackendCapability.CROSS_RUN_COORDINATION,
                    BackendCapability.RECOVERY_SCANS,
                    BackendCapability.GLOBAL_COUNTERS,
                    BackendCapability.BACKEND_LEASE_TIME,
                    BackendCapability.CONSISTENT_READS,
                    BackendCapability.REVISIONED_SNAPSHOTS,
                )
            ),
        )

    def check_schema(self):
        return check_authority_schema_version(
            {"schema_version": AUTHORITY_SCHEMA_VERSION}
        )

    def create_workspace(self, identity: WorkspaceIdentity) -> BackendRevision:
        if identity.workspace_id in self._workspaces:
            raise ValueError(f"workspace already exists: {identity.workspace_id}")
        self._workspaces[identity.workspace_id] = identity
        return self._next_revision()

    def create_sweep(self, identity: SweepIdentity) -> BackendRevision:
        if identity.workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        if identity.sweep_id in self._sweeps:
            raise ValueError(f"sweep already exists: {identity.sweep_id}")
        self._sweeps[identity.sweep_id] = identity
        self._trials.setdefault(identity.sweep_id, {})
        return self._next_revision()

    def record_trial(self, trial: TrialReference) -> BackendRevision:
        if trial.sweep_id not in self._sweeps:
            raise ValueError("unknown sweep")
        self._trials.setdefault(trial.sweep_id, {})[trial.trial_id] = trial
        return self._next_revision()

    def list_trials(self, sweep_id: str) -> tuple[TrialReference, ...]:
        if sweep_id not in self._sweeps:
            raise ValueError("unknown sweep")
        return tuple(self._trials.get(sweep_id, {}).values())

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> TrialLeaseRecord:
        if trial_id not in self._trials.get(sweep_id, {}):
            raise ValueError("unknown trial")
        if self._active_trial_lease(sweep_id, trial_id) is not None:
            raise ValueError("trial already has an active lease")
        sweep = self._sweeps[sweep_id]
        lease = self._new_lease(
            kind=LeaseKind.TRIAL,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        record = TrialLeaseRecord(
            workspace_id=sweep.workspace_id,
            sweep_id=sweep_id,
            trial_id=trial_id,
            lease=lease,
        )
        self._trial_leases[lease.lease_id] = record
        return record

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
    ) -> ResourceLeaseRecord:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        resource_limit = self._resource_limits.get((workspace_id, resource_key))
        active_amount = self._active_resource_amount(workspace_id, resource_key)
        if resource_limit is not None and active_amount + amount > resource_limit:
            raise ValueError("resource limit exceeded")
        lease = self._new_lease(
            kind=LeaseKind.RESOURCE,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        record = ResourceLeaseRecord(
            workspace_id=workspace_id,
            resource_key=resource_key,
            lease=lease,
            amount=amount,
        )
        self._resource_leases[lease.lease_id] = record
        return record

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        lease = self._require_coordination_lease(lease_id, owner_id, fencing_token)
        renewed = LeaseRecord(
            lease_id=lease.lease_id,
            kind=lease.kind,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            renewed_at=self._now(),
            expires_at=self._at_tick(self._tick + lease_ttl_seconds),
            revision=self._next_revision(),
            state=lease.state,
            reason=lease.reason,
        )
        self._leases[lease_id] = renewed
        self._lease_expiry_ticks[lease_id] = self._tick + lease_ttl_seconds
        self._replace_coordination_lease(renewed)
        return renewed

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        lease = self._require_coordination_lease(lease_id, owner_id, fencing_token)
        updated = LeaseRecord(
            lease_id=lease.lease_id,
            kind=lease.kind,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            renewed_at=lease.renewed_at,
            expires_at=lease.expires_at,
            revision=self._next_revision(),
            state=LeaseState.RELEASED,
            reason=reason,
        )
        self._leases[lease_id] = updated
        self._replace_coordination_lease(updated)
        return updated

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        lease = self._require_coordination_lease(lease_id, owner_id, fencing_token)
        updated = LeaseRecord(
            lease_id=lease.lease_id,
            kind=lease.kind,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            renewed_at=lease.renewed_at,
            expires_at=lease.expires_at,
            revision=self._next_revision(),
            state=LeaseState.FAILED,
            reason=reason,
        )
        self._leases[lease_id] = updated
        self._replace_coordination_lease(updated)
        return updated

    def set_resource_limit(
        self, workspace_id: str, resource_key: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        active_amount = self._active_resource_amount(workspace_id, resource_key)
        revision = self._next_revision()
        key = (workspace_id, resource_key)
        if limit is None:
            self._resource_limits.pop(key, None)
            self._resource_limit_revisions.pop(key, None)
        else:
            if limit <= 0:
                raise ValueError("limit must be positive")
            if active_amount > limit:
                raise ValueError("resource limit is below active lease usage")
            self._resource_limits[key] = limit
            self._resource_limit_revisions[key] = revision
        return ConcurrencyCounter(
            counter_name=f"resource:{resource_key}",
            value=active_amount,
            limit=limit,
            revision=revision,
        )

    def read_resource_limit(
        self, workspace_id: str, resource_key: str
    ) -> ConcurrencyCounter | None:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        key = (workspace_id, resource_key)
        limit = self._resource_limits.get(key)
        if limit is None:
            return None
        revision = self._resource_limit_revisions[key]
        return ConcurrencyCounter(
            counter_name=f"resource:{resource_key}",
            value=self._active_resource_amount(workspace_id, resource_key),
            limit=limit,
            revision=revision,
        )

    def set_counter_limit(
        self, workspace_id: str, counter_name: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        current = self._counters.get((workspace_id, counter_name))
        value = 0 if current is None else current.value
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            if value > limit:
                raise ValueError("counter limit is below current value")
        counter = ConcurrencyCounter(
            counter_name=counter_name,
            value=value,
            limit=limit,
            revision=self._next_revision(),
        )
        self._counters[(workspace_id, counter_name)] = counter
        return counter

    def increment_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        limit: int | None = None,
    ) -> ConcurrencyCounter:
        if amount <= 0:
            raise ValueError("amount must be positive")
        return self._change_counter(
            workspace_id,
            counter_name,
            amount=amount,
            limit=limit,
        )

    def decrement_counter(
        self, workspace_id: str, counter_name: str, *, amount: int = 1
    ) -> ConcurrencyCounter:
        if amount <= 0:
            raise ValueError("amount must be positive")
        return self._change_counter(
            workspace_id,
            counter_name,
            amount=-amount,
            limit=None,
        )

    def _change_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int,
        limit: int | None,
    ) -> ConcurrencyCounter:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        current = self._counters.get((workspace_id, counter_name))
        current_value = 0 if current is None else current.value
        value = current_value + amount
        if value < 0:
            raise ValueError("counter value cannot become negative")
        current_limit = None if current is None else current.limit
        next_limit = limit if limit is not None else current_limit
        if next_limit is not None and value > next_limit:
            raise ValueError("counter limit exceeded")
        counter = ConcurrencyCounter(
            counter_name=counter_name,
            value=value,
            limit=next_limit,
            revision=self._next_revision(),
        )
        self._counters[(workspace_id, counter_name)] = counter
        return counter

    def read_counter(
        self, workspace_id: str, counter_name: str
    ) -> ConcurrencyCounter | None:
        return self._counters.get((workspace_id, counter_name))

    def scan_recovery(
        self, workspace_id: str
    ) -> tuple[CoordinationRecoveryRecord, ...]:
        if workspace_id not in self._workspaces:
            raise ValueError("unknown workspace")
        records: list[CoordinationRecoveryRecord] = []
        for record in self._trial_leases.values():
            if record.workspace_id != workspace_id or not self._lease_expired(
                record.lease
            ):
                continue
            records.append(
                CoordinationRecoveryRecord(
                    workspace_id=record.workspace_id,
                    sweep_id=record.sweep_id,
                    trial_id=record.trial_id,
                    recovery=self._expired_lease_recovery(record.lease),
                )
            )
        for record in self._resource_leases.values():
            if record.workspace_id != workspace_id or not self._lease_expired(
                record.lease
            ):
                continue
            records.append(
                CoordinationRecoveryRecord(
                    workspace_id=record.workspace_id,
                    resource_key=record.resource_key,
                    amount=record.amount,
                    recovery=self._expired_lease_recovery(record.lease),
                )
            )
        return tuple(records)

    def advance_time(self, seconds: int) -> None:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._tick += seconds

    def _new_lease(
        self, *, kind: LeaseKind, owner_id: str, lease_ttl_seconds: int
    ) -> LeaseRecord:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        revision = self._next_revision()
        lease = LeaseRecord(
            lease_id=f"workspace-lease-{revision.sequence}",
            kind=kind,
            owner_id=owner_id,
            fencing_token=f"workspace-fence-{revision.sequence}",
            acquired_at=self._now(),
            renewed_at=self._now(),
            expires_at=self._at_tick(self._tick + lease_ttl_seconds),
            revision=revision,
        )
        self._leases[lease.lease_id] = lease
        self._lease_expiry_ticks[lease.lease_id] = self._tick + lease_ttl_seconds
        return lease

    def _require_coordination_lease(
        self, lease_id: str, owner_id: str, fencing_token: str
    ) -> LeaseRecord:
        lease = self._leases[lease_id]
        if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
            raise ValueError("stale or foreign lease token")
        if lease.state is not LeaseState.ACTIVE:
            raise ValueError("lease is not active")
        if self._lease_expired(lease):
            raise ValueError("lease has expired")
        return lease

    def _replace_coordination_lease(self, lease: LeaseRecord) -> None:
        trial = self._trial_leases.get(lease.lease_id)
        if trial is not None:
            self._trial_leases[lease.lease_id] = TrialLeaseRecord(
                workspace_id=trial.workspace_id,
                sweep_id=trial.sweep_id,
                trial_id=trial.trial_id,
                lease=lease,
            )
            return
        resource = self._resource_leases.get(lease.lease_id)
        if resource is not None:
            self._resource_leases[lease.lease_id] = ResourceLeaseRecord(
                workspace_id=resource.workspace_id,
                resource_key=resource.resource_key,
                lease=lease,
                amount=resource.amount,
            )

    def _lease_expired(self, lease: LeaseRecord) -> bool:
        return (
            lease.state is LeaseState.ACTIVE
            and self._lease_expiry_ticks.get(lease.lease_id, self._tick + 1)
            <= self._tick
        )

    def _active_trial_lease(
        self, sweep_id: str, trial_id: str
    ) -> TrialLeaseRecord | None:
        for record in self._trial_leases.values():
            if (
                record.sweep_id == sweep_id
                and record.trial_id == trial_id
                and not self._lease_expired(record.lease)
                and record.lease.state is LeaseState.ACTIVE
            ):
                return record
        return None

    def _active_resource_amount(self, workspace_id: str, resource_key: str) -> int:
        return sum(
            record.amount
            for record in self._resource_leases.values()
            if record.workspace_id == workspace_id
            and record.resource_key == resource_key
            and record.lease.state is LeaseState.ACTIVE
            and not self._lease_expired(record.lease)
        )

    def _expired_lease_recovery(self, lease: LeaseRecord) -> RecoveryRecord:
        return RecoveryRecord(
            recovery_id=f"expired-{lease.lease_id}",
            kind=RecoveryKind.EXPIRED_LEASE,
            reason=LifecycleReason(code="lease_expired"),
            detected_at=self._now(),
            revision=lease.revision,
        )

    def _next_revision(self) -> BackendRevision:
        self._revision += 1
        return BackendRevision(
            sequence=self._revision,
            token=f"coord-rev-{self._revision}",
            created_at=self._now(),
        )

    def _now(self) -> str:
        return self._at_tick(self._tick)

    @staticmethod
    def _at_tick(tick: int) -> str:
        value = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=tick)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "InMemoryPerRunAuthorityStore",
    "InMemoryWorkspaceCoordinationStore",
]
