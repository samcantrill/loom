"""Tests for opt-in downstream contract support."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from loom.pipeline.event_sinks import EventSinkContext
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
    check_resource_validator_contract,
)


pytestmark = pytest.mark.unit


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


def test_resource_validator_contract_records_rejection_and_prerequisite_failures() -> None:
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
        "event_sink.invoke",
    ]
    assert {finding.status for finding in report.findings} == {"fail"}
