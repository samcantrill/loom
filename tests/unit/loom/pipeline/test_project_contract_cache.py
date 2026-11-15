import pytest

from loom.pipeline._project_contract_cache import WorkerContractCache
from loom.queue.errors import QueueConflictError


def test_projection_cache_reloads_evicted_or_oversized_evidence():
    cache = WorkerContractCache(max_entries=1, max_bytes=32)
    calls = []

    def load(key, value):
        def checked():
            calls.append(key)
            return {"value": value}
        return cache.load(key, lambda: key, checked)

    assert load("one", 1) == load("one", 1)
    assert calls == ["one"]
    load("two", 2)
    load("one", 1)
    assert calls == ["one", "two", "one"]
    load("large", "x" * 64)
    load("large", "x" * 64)
    assert calls[-2:] == ["large", "large"]


def test_changed_evidence_during_validation_is_not_cached():
    cache = WorkerContractCache()
    version = [1]

    def changing_loader():
        version[0] = 2
        return {"value": "obsolete"}

    with pytest.raises(QueueConflictError, match="changed while loading"):
        cache.load("run", lambda: version[0], changing_loader)
    assert cache.load("run", lambda: version[0], lambda: {"value": "current"}) == {"value": "current"}
