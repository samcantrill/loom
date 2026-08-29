"""Tests for opt-in downstream contract support."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from loom.pipeline.event_sinks import EventSinkContext
from loom.pipeline.event_sinks import EventSinkRegistration, EventSinkSubscription
from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.pipeline.execution.models import StageExecutionRequest, StageExecutionResult
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.status import StageStatus
from loom.testing import (
    ContractFinding,
    ContractReport,
    check_codec_contract,
    check_event_sink_contract,
    check_executor_contract,
    check_hard_constraint_contract,
    check_preference_scorer_contract,
    check_resource_planner_contract,
    check_resource_validator_contract,
    check_scheduling_policy_contract,
)
from loom.pipeline.runtime import CpuResourcePlanner
from loom.scheduling import (
    Candidate,
    CandidateEvaluation,
    CapacityAtom,
    ClaimSearchBudget,
    ExactQuantity,
    FifoSchedulingPolicy,
    HardConstraintSpec,
    NeutralPreferenceScorer,
    PolicyContext,
    PreferenceSpec,
    ResolvedResourceRequest,
    ResourceAvailabilityEnvelope,
    ResourceInventoryEnvelope,
    TargetConstraintEvaluator,
    ValidatedResourceEntryView,
    WorkEvaluation,
    WorkItem,
    WorkSearchState,
)


pytestmark = pytest.mark.unit


def test_scheduling_contract_checks_cover_complete_caller_samples() -> None:
    atom = CapacityAtom("cpu", "shared", ExactQuantity(2), "count", ExactQuantity(1))
    inventory = ResourceInventoryEnvelope("agent", "cpu", "one", atoms=(atom,))
    availability = ResourceAvailabilityEnvelope("agent", "cpu", "one", atoms=(atom,))
    request = ValidatedResourceEntryView("cpu", ExactQuantity(1), "count")
    planner = CpuResourcePlanner()
    planner_report = check_resource_planner_contract(
        planner,
        authored=request,
        runtime=None,
        inventory=inventory,
        availability=availability,
    )
    assert planner_report.ok
    assert "resource_planner.claim" in {
        finding.code for finding in planner_report.findings
    }

    work = WorkItem("work", 1, {"cpu": ResolvedResourceRequest("cpu", request)})
    candidate = Candidate(
        "agent",
        {"cpu": inventory},
        {"cpu": availability},
        attributes={"target": "agent"},
    )
    claim = planner.propose_claims(
        ResolvedResourceRequest("cpu", request),
        planner.validate_opportunity(inventory, availability).opportunity,  # type: ignore[arg-type]
        ClaimSearchBudget(4),
    ).claims[0]
    hard = TargetConstraintEvaluator()
    hard_spec = HardConstraintSpec(
        "target", "target", {"target": "agent"}, hard.descriptor
    )
    scorer = NeutralPreferenceScorer()
    preference_spec = PreferenceSpec("neutral", "neutral", descriptor=scorer.descriptor)
    assert check_hard_constraint_contract(
        hard,
        work=work,
        candidate=candidate,
        claims=(claim,),
        spec=hard_spec,
    ).ok
    assert check_preference_scorer_contract(
        scorer,
        work=work,
        candidate=candidate,
        claims=(claim,),
        spec=preference_spec,
    ).ok
    context = PolicyContext(
        1,
        (
            WorkEvaluation(
                work,
                WorkSearchState.COMPLETE,
                (CandidateEvaluation("work", "agent", (claim,), (0,)),),
            ),
        ),
    )
    assert check_scheduling_policy_contract(FifoSchedulingPolicy(), context=context).ok


class _Codec:
    key = "test.codec"

    def encode(self, value: object, *, metadata: object = None) -> bytes:
        del metadata
        return str(value).encode()

    def decode(self, data: bytes, *, metadata: object = None) -> object:
        del metadata
        return data.decode()


def test_codec_contract_reports_stable_cases_and_plain_data() -> None:
    report = check_codec_contract(
        _Codec(),
        roundtrip_values=("one",),
        metadata_cases=(("two", {"case": "metadata"}),),
    )

    assert report.ok
    assert [finding.code for finding in report.findings] == [
        "codec.protocol",
        "codec.key",
        "codec.encode",
        "codec.decode",
        "codec.roundtrip",
        "codec.encode",
        "codec.decode",
        "codec.roundtrip",
    ]
    assert report.to_dict()["contract_version"] == 1


def test_codec_contract_reports_dependent_failures_without_invocation() -> None:
    report = check_codec_contract(object(), roundtrip_values=("one",))

    assert not report.ok
    assert [finding.code for finding in report.findings] == [
        "codec.protocol",
        "codec.key",
        "codec.encode",
        "codec.decode",
        "codec.roundtrip",
    ]
    assert {finding.status for finding in report.findings} == {"fail"}


def test_resource_validator_contract_records_rejection_and_prerequisite_failures() -> (
    None
):
    def validator(entry: ResourceEntry, path: str) -> None:
        if entry.amount <= 0:
            raise ValueError(path)

    report = check_resource_validator_contract(
        "test.accelerator",
        validator,
        valid_entries=(ResourceEntry(kind="test.accelerator", amount=1),),
        invalid_entries=(ResourceEntry(kind="test.accelerator", amount=0),),
    )

    assert report.ok
    assert [finding.code for finding in report.findings] == [
        "resource_validator.kind",
        "resource_validator.callable",
        "resource_validator.registration",
        "resource_validator.accepts_valid",
        "resource_validator.rejects_invalid",
    ]


def test_resource_validator_contract_does_not_invoke_after_invalid_kind() -> None:
    invoked = False

    def validator(entry: ResourceEntry, path: str) -> None:
        nonlocal invoked
        del entry, path
        invoked = True

    report = check_resource_validator_contract(
        "",
        validator,
        valid_entries=(ResourceEntry(kind="test.accelerator", amount=1),),
        invalid_entries=(ResourceEntry(kind="test.accelerator", amount=0),),
    )

    assert not report.ok
    assert invoked is False
    assert [finding.code for finding in report.findings] == [
        "resource_validator.kind",
        "resource_validator.callable",
        "resource_validator.registration",
        "resource_validator.accepts_valid",
        "resource_validator.rejects_invalid",
    ]


def test_executor_contract_reports_result_identity() -> None:
    request = cast(
        StageExecutionRequest,
        SimpleNamespace(stage=SimpleNamespace(name="stage"), attempt=1),
    )

    class Executor:
        name = "test"

        def execute(self, request: object) -> StageExecutionResult:
            return StageExecutionResult(
                stage_name="stage",
                status=StageStatus.SUCCEEDED,
                outputs={},
                failure=None,
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:01Z",
                executor_name="test",
                attempt=1,
            )

    report = check_executor_contract(Executor(), requests=(request,))

    assert report.ok
    assert [finding.code for finding in report.findings] == [
        "executor.protocol",
        "executor.name",
        "executor.execute",
        "executor.result_type",
        "executor.result_identity",
    ]


def test_executor_contract_reports_each_dependent_failure_without_invocation() -> None:
    request = cast(
        StageExecutionRequest,
        SimpleNamespace(stage=SimpleNamespace(name="stage"), attempt=1),
    )

    report = check_executor_contract(object(), requests=(request,))

    assert not report.ok
    assert [finding.code for finding in report.findings] == [
        "executor.protocol",
        "executor.name",
        "executor.execute",
        "executor.result_type",
        "executor.result_identity",
    ]


def test_event_sink_contract_and_report_error_are_bounded() -> None:
    received: list[object] = []

    def sink(event: object, context: object) -> None:
        del context
        received.append(event)

    event = cast(EventReference, object())
    report = check_event_sink_contract(
        sink,
        events=(event,),
        context_factory=lambda _event: cast(EventSinkContext, object()),
    )

    assert report.ok
    assert report.contract_version == 2
    assert received == [event]
    failure = ContractReport(
        "loom.example",
        1,
        (ContractFinding("example.failure", "fail", "expected failure"),),
    )
    with pytest.raises(AssertionError, match="example.failure"):
        failure.raise_for_errors()


def test_event_sink_contract_does_not_build_context_for_non_callable_sink() -> None:
    event = cast(EventReference, object())

    def fail_context(
        _event: PipelineEventRecord | EventReference,
    ) -> EventSinkContext:
        raise AssertionError("context factory must not be called")

    report = check_event_sink_contract(
        object(),
        events=(event,),
        context_factory=fail_context,
    )

    assert not report.ok
    assert [finding.code for finding in report.findings] == [
        "event_sink.callable",
        "event_sink.subscription",
        "event_sink.invoke",
    ]
    assert [finding.status for finding in report.findings] == ["fail", "pass", "fail"]


def test_event_sink_contract_only_invokes_matching_registration_events() -> None:
    received: list[EventReference] = []
    started = EventReference(
        event_id="started",
        run_uri="run://contract",
        event_type="run.started",
        occurred_at="2020-01-01T00:00:00Z",
        durability="durable",
        sequence=1,
    )
    completed = EventReference(
        event_id="completed",
        run_uri="run://contract",
        event_type="run.completed",
        occurred_at="2020-01-01T00:00:01Z",
        durability="durable",
        sequence=2,
    )
    report = check_event_sink_contract(
        EventSinkRegistration(
            sink=lambda event, context: received.append(cast(EventReference, event)),
            subscription=EventSinkSubscription(event_types=("run.completed",)),
        ),
        events=(started, completed),
        context_factory=lambda _event: cast(EventSinkContext, object()),
    )

    assert report.ok
    assert [finding.code for finding in report.findings] == [
        "event_sink.callable",
        "event_sink.subscription",
        "event_sink.invoke",
    ]
    assert received == [completed]
