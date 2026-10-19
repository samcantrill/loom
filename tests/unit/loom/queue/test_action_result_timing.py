"""Reuse timing cannot replace a resolution result or its original failure."""

from types import SimpleNamespace

import pytest

from loom.pipeline.stores.read_models import BackendRevision
from loom.queue._action_result_resolution import ActionResultResolution


@pytest.mark.parametrize("failed", [False, True])
def test_timing_delivery_failure_preserves_resolution(monkeypatch, failed):
    owner = object.__new__(ActionResultResolution)
    emitted = []
    result, error = object(), RuntimeError("original resolution failure")

    def unavailable(*args, **kwargs):
        emitted.append(kwargs)
        raise OSError("audit storage unavailable")

    owner.execution = SimpleNamespace(
        _authority_for_run=lambda uri: object(),
        _event_observers=SimpleNamespace(defer_emit=unavailable),
    )

    def resolve(*args):
        timings = args[-1]
        for phase in ("reuse_lookup", "reuse_authority_read"):
            with timings.measure(phase):
                pass
        if failed:
            raise error
        return result

    monkeypatch.setattr(owner, "_resolve", resolve)
    args = (SimpleNamespace(run_uri="file:///runs/example"), None, None,
            SimpleNamespace(stage_name="fit"), None, BackendRevision(1, "same"))
    if failed:
        with pytest.raises(RuntimeError) as observed:
            owner.resolve(*args)
        assert observed.value is error
    else:
        assert owner.resolve(*args) is result
    assert emitted[0]["event_type"] == "stage.reuse_timing"
