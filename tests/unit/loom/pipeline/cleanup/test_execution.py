"""Unit tests for intent-gated cleanup execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.cleanup import (
    CleanupDeleteIntent,
    CleanupError,
    CleanupManagedRoot,
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupResult,
    CleanupResultOutcome,
    CleanupTargetKind,
    CleanupTargetRef,
    execute_cleanup,
)
from loom.pipeline.event_sinks import EventSinkContext, EventSinkRegistry
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.execution.eventing import RuntimeEventDispatcher
from loom.pipeline.stores import (
    BackendRevision,
    CleanupResultFact,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.serialization import PlainData, thaw_plain_data


pytestmark = pytest.mark.unit


@dataclass(slots=True)
class ExecutionStore:
    cleanup_results: list[CleanupResultFact] = field(default_factory=list)
    events: list[PipelineEventRecord] = field(default_factory=list)
    failures: list[object] = field(default_factory=list)
    links: list[object] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)

    def append_cleanup_result(
        self,
        run_uri: str,
        result: CleanupResult,
    ) -> CleanupResultFact:
        self.operations.append("result")
        fact = CleanupResultFact(
            result=result,
            recorded_at="2020-01-01T00:00:06Z",
            revision=BackendRevision(
                sequence=len(self.cleanup_results) + 1,
                token=f"rev-{len(self.cleanup_results) + 1}",
            ),
        )
        self.cleanup_results.append(fact)
        return fact

    def append_audit_event(
        self,
        run_uri: str,
        event: PipelineEvent,
    ) -> PipelineEventRecord:
        self.operations.append("event")
        record = PipelineEventRecord(
            run_uri=run_uri,
            sequence=len(self.events) + 1,
            timestamp=event.timestamp,
            scope=event.scope,
            event_type=event.event_type,
            payload=cast(
                dict[str, PlainData],
                thaw_plain_data(event.payload, path="event.payload"),
            ),
        )
        self.events.append(record)
        return record

    def append_event_sink_failure(self, run_uri: str, failure: object) -> object:
        self.operations.append("failure")
        self.failures.append(failure)
        return BackendRevision(sequence=100, token="failure")

    def append_event_observer_link(self, run_uri: str, link: object) -> object:
        self.operations.append("link")
        self.links.append(link)
        return BackendRevision(sequence=101, token="link")


def test_execute_cleanup_deletes_selected_target_records_result_then_event(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    target = run_root / "tmp" / "payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("payload", encoding="utf-8")
    store = ExecutionStore()

    fact = execute_cleanup(
        cast(PerRunAuthorityStore, store),
        path_to_run_uri(run_root),
        _report(run_root, target),
        _intent(candidate_ids=("candidate-1",)),
        managed_roots=(_managed_root(run_root),),
        result_id="result-1",
        created_at="2020-01-01T00:00:05Z",
    )

    assert not target.exists()
    assert store.operations == ["result", "event"]
    assert fact.result.summary == {
        "candidates": 1,
        "deleted": 1,
        "skipped": 0,
        "rejected": 0,
        "failed": 0,
    }
    assert fact.result.entries[0].outcome is CleanupResultOutcome.DELETED
    assert store.events[0].event_type == "cleanup.result.recorded"
    assert store.events[0].payload["result_id"] == "result-1"


def test_execute_cleanup_requires_structured_delete_intent(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    target = run_root / "tmp" / "payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("payload", encoding="utf-8")

    with pytest.raises(CleanupError, match="intent"):
        execute_cleanup(
            cast(PerRunAuthorityStore, ExecutionStore()),
            path_to_run_uri(run_root),
            _report(run_root, target),
            True,  # type: ignore[arg-type]
            managed_roots=(_managed_root(run_root),),
        )


def test_execute_cleanup_rechecks_safety_and_rejects_unsafe_target(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    outside = tmp_path / "outside" / "payload.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("payload", encoding="utf-8")
    store = ExecutionStore()

    fact = execute_cleanup(
        cast(PerRunAuthorityStore, store),
        path_to_run_uri(run_root),
        _report(run_root, outside),
        _intent(),
        managed_roots=(_managed_root(run_root),),
        result_id="result-1",
        created_at="2020-01-01T00:00:05Z",
        emit_event=False,
    )

    assert outside.exists()
    assert fact.result.entries[0].outcome is CleanupResultOutcome.REJECTED
    assert fact.result.entries[0].reason_code == "outside_managed_root"
    assert store.operations == ["result"]


def test_execute_cleanup_sink_failures_do_not_fail_cleanup(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    target = run_root / "tmp" / "payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("payload", encoding="utf-8")
    store = ExecutionStore()
    registry = EventSinkRegistry()

    def failing_sink(event: object, context: EventSinkContext) -> None:
        raise RuntimeError("sink unavailable")

    registry.register("audit.fail", failing_sink)

    fact = execute_cleanup(
        cast(PerRunAuthorityStore, store),
        path_to_run_uri(run_root),
        _report(run_root, target),
        _intent(),
        managed_roots=(_managed_root(run_root),),
        result_id="result-1",
        created_at="2020-01-01T00:00:05Z",
        event_dispatcher=RuntimeEventDispatcher(registry=registry),
    )

    assert fact.result.entries[0].outcome is CleanupResultOutcome.DELETED
    assert store.operations == ["result", "event", "failure"]
    assert len(store.failures) == 1


def _report(run_root: Path, target: Path) -> CleanupReport:
    return CleanupReport(
        report_id="report-1",
        run_uri=path_to_run_uri(run_root),
        created_at="2020-01-01T00:00:00Z",
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=CleanupTargetRef(
                    kind=CleanupTargetKind.LOCAL_PATH,
                    uri=path_to_run_uri(target),
                    target_id="target-1",
                    ownership_key="run-r1",
                    metadata={"purpose": "test"},
                ),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
    )


def _intent(
    *,
    candidate_ids: tuple[str, ...] = (),
) -> CleanupDeleteIntent:
    return CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:04Z",
        reason="unit test cleanup",
        candidate_ids=candidate_ids,
    )


def _managed_root(path: Path) -> CleanupManagedRoot:
    return CleanupManagedRoot(
        root_id="run-root",
        uri=path_to_run_uri(path),
        ownership_key="run-r1",
    )
