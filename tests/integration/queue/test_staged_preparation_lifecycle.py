"""Cancellation at the staged capture/publication boundary."""

from pathlib import Path
from threading import Event

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue.local_daemon import LocalDaemon
import loom.queue.preparation as preparation_inputs
from tests.integration.queue.test_preparation_operations import _request, _result, _service


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_cancellation_during_archive_capture_prevents_child_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, mode="staged")
    captured, finish_capture = Event(), Event()
    write_archive = preparation_inputs._write_staged_archive

    def held_archive(path, manifest, contents):
        write_archive(path, manifest, contents)
        captured.set()
        assert finish_capture.wait(25)

    monkeypatch.setattr(preparation_inputs, "_write_staged_archive", held_archive)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = _request("staged")
        daemon.prepare_run(request, principal_id="caller")
        assert captured.wait(25)
        pending = daemon.cancel_preparation(request.operation_id, principal_id="caller")
        assert pending.state == "pending"
        assert _result(pending)["input_receipt"] is None
        assert not daemon.admissions().admissions
        finish_capture.set()
        cancelled = daemon.wait_operation(request.operation_id, timeout=25).operation
        assert cancelled.state == "cancelled", cancelled
        assert not daemon.admissions().admissions
        assert not (service.daemon.run_store_root / request.run_name).exists()
        assert daemon.prepare_run(request, principal_id="caller") == cancelled
        assert not tuple((service.daemon.coordinator_root / "preparation-inputs").glob(".*.tmp-*.tar"))
    finally:
        finish_capture.set()
        daemon.stop()
