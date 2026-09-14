"""The native run request remains plain, exact and distinct from pipeline execution."""

from dataclasses import replace

import pytest

from loom.coordinator import RunRequest
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue._coordinator_control import request_ids, validate_request
from loom.queue.errors import QueueServiceError

pytestmark = pytest.mark.contract


def test_run_intent_round_trip_preserves_exact_native_identities():
    preparation = PrepareRunRequest(
        "operation",
        "target",
        PreparationSource("shared", "project", ".", ("pipeline.yaml",)),
        "pipeline.yaml",
        "profile",
    )
    request = RunRequest(preparation, "admission")
    assert RunRequest.from_dict(request.to_dict()) == request
    assert validate_request("start_run", {"request": request.to_dict()}) == {
        "request": request
    }
    assert request_ids({"request": request.to_dict()}) == {
        "queue_item_id": "admission",
        "operation_id": "operation",
    }
    assert replace(request, queue_item_id="different") != request
    assert "retry_failed_revision" not in request.to_dict()
    with pytest.raises(QueueServiceError):
        RunRequest.from_dict({**request.to_dict(), "retry_failed_revision": 1})
    with pytest.raises(QueueServiceError):
        RunRequest(preparation, "")
