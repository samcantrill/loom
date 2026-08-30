"""Unit coverage for private queue selection helpers."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from loom.queue import (
    LaunchContract,
    QueueItem,
    QueueSelectionCandidate,
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
    RunIntent,
)
from loom.queue.errors import QueueValidationError
from loom.queue.selection import _bind_selection_policy, _evaluate_selection


def test_selection_records_are_immutable_and_validate_the_public_boundary() -> None:
    candidate = QueueSelectionCandidate(
        queue_item_id="item-1",
        enqueued_at="2020-01-01T00:00:00Z",
        dispatch_attempt=1,
        resources={"gpu": 1},
    )
    context = QueueSelectionContext(
        pool_name="gpu",
        candidates=(candidate,),
        advisory_available_resources={"gpu": 1},
    )

    assert isinstance(candidate.resources, MappingProxyType)
    assert isinstance(context.advisory_available_resources, MappingProxyType)
    with pytest.raises(TypeError):
        candidate.resources["gpu"] = 2  # type: ignore[index]
    with pytest.raises(QueueValidationError, match="unique"):
        QueueSelectionContext("gpu", (candidate, candidate), {"gpu": 1})
    with pytest.raises(QueueValidationError, match="must not include"):
        QueueSelectionDecision(QueueSelectionDisposition.STOPPED, "stopped", "item-1")


def test_selection_evaluator_filters_before_default_or_custom_preference() -> None:
    older_large = _item("b-needs-two", "gpu", "2020-01-01T00:00:00Z")
    older_large = replace(
        older_large,
        launch_contract=LaunchContract(
            adapter="local", entrypoint="entry", resources={"gpu": 2}
        ),
        admission_digest=None,
    )
    younger_small = _item("a-needs-one", "gpu", "2020-01-01T00:00:01Z")
    younger_small = replace(
        younger_small,
        launch_contract=LaunchContract(
            adapter="local", entrypoint="entry", resources={"gpu": 1}
        ),
        admission_digest=None,
    )
    policy = _ChoosingPolicy()

    default = _evaluate_selection(
        (older_large, younger_small),
        pool_name="gpu",
        advisory_available_resources={"gpu": 1},
        policy=None,
    )
    custom = _evaluate_selection(
        (older_large, younger_small),
        pool_name="gpu",
        advisory_available_resources={"gpu": 1},
        policy=_bind_selection_policy(policy),
    )

    assert default.decision.queue_item_id == "a-needs-one"
    assert default.preference_id == "queue_selection.default"
    assert custom.decision.queue_item_id == "a-needs-one"
    assert policy.context is not None
    assert [candidate.queue_item_id for candidate in policy.context.candidates] == [
        "a-needs-one"
    ]
    assert set(policy.context.candidates[0].__dataclass_fields__) == {
        "queue_item_id",
        "enqueued_at",
        "dispatch_attempt",
        "resources",
    }


def test_selection_evaluator_stops_safely_for_invalid_policy_output_or_error() -> None:
    item = _item("item-1", "gpu", "2020-01-01T00:00:00Z")

    invalid = _evaluate_selection(
        (item,),
        pool_name="gpu",
        advisory_available_resources={},
        policy=_bind_selection_policy(_InvalidPolicy()),
    )
    failed = _evaluate_selection(
        (item,),
        pool_name="gpu",
        advisory_available_resources={},
        policy=_bind_selection_policy(_FailingPolicy()),
    )

    assert invalid.decision == QueueSelectionDecision(
        QueueSelectionDisposition.STOPPED, "queue_selection.invalid_decision"
    )
    assert failed.decision == QueueSelectionDecision(
        QueueSelectionDisposition.STOPPED, "queue_selection.policy_error"
    )


def _item(item_id: str, pool_name: str, enqueued_at: str) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name=f"{pool_name}-queue",
        pool_name=pool_name,
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(adapter="local", entrypoint="entry"),
        enqueued_at=enqueued_at,
        updated_at=enqueued_at,
    )


class _ChoosingPolicy:
    policy_id = "test.choosing"

    def __init__(self) -> None:
        self.context: QueueSelectionContext | None = None

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        self.context = context
        return QueueSelectionDecision(
            QueueSelectionDisposition.SELECTED,
            "test.chosen",
            context.candidates[-1].queue_item_id,
        )


class _InvalidPolicy:
    policy_id = "test.invalid"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        return QueueSelectionDecision(
            QueueSelectionDisposition.SELECTED, "test.invalid", "not-present"
        )


class _FailingPolicy:
    policy_id = "test.failing"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        raise RuntimeError("private policy detail")
