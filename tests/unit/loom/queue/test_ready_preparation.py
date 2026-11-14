"""An obsolete writer cannot overwrite a newer attempt's stage workspace."""

from threading import Event

import pytest

from loom.queue._ready_preparation import ReadyPreparationPool

pytestmark = pytest.mark.unit


def test_successor_waits_for_old_writer_and_finished_work_is_bounded():
    entered, release, woke = Event(), Event(), Event()
    writes = []
    pool = ReadyPreparationPool(woke.set)

    def first():
        entered.set()
        assert release.wait(10)
        writes.append("old")
        return "old"

    def second():
        writes.append("new")
        return "new"

    try:
        assert pool.poll(("run", "stage"), "old", first) == (None, "stage_preparation_pending")
        assert entered.wait(10)
        assert pool.poll(("run", "stage"), "new", second) == (None, "stage_preparation_superseded")
        assert writes == []
        release.set()
        assert woke.wait(10)
        woke.clear()
        pool.poll(("run", "stage"), "new", second)
        assert woke.wait(10)
        assert pool.poll(("run", "stage"), "new", second) == ("new", None)
        assert writes == ["old", "new"]
        for index in range(10):
            woke.clear()
            pool.poll(("run", str(index)), str(index), second)
            assert woke.wait(10)
        assert len(pool._pending) == 8
    finally:
        release.set()
        pool.close()
