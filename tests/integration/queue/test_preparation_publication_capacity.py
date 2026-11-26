"""Observe report retention while completed annotations await application."""
from dataclasses import replace
from threading import Event

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from tests.integration.queue.test_preparation_operations import _request, _service

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_report_capacity_during_delayed_annotation_completion(tmp_path, monkeypatch):
    """A finished publication still owns one hydrated report until its completion is applied."""
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    owner = daemon._preparations
    requests = [replace(_request(), operation_id=f"retained-{i}", run_name=f"retained-{i}") for i in range(3)]
    held = {request.operation_id for request in requests[:2]}
    both_done, observed, release = Event(), Event(), Event()
    observations = []
    complete = owner._complete_publication
    read_report = owner._read_report_async

    def defer_completed_annotations(row):
        key = row["operation_id"]
        if key in held and not release.is_set() and key in owner._annotations and owner._annotations[key][1].done():
            if all(k in owner._annotations and owner._annotations[k][1].done()
                   and owner._publications[k].future.done() for k in held):
                both_done.set()
            return True
        return complete(row)

    def observe_third_report(row, config, admission, request, binding, token):
        result = read_report(row, config, admission, request, binding, token)
        if request.operation_id == requests[2].operation_id and not release.is_set():
            active = sum(not future.done() for future in daemon._result_verifications.bulk._active)
            if active < 2:
                observations.append((len(owner._publications), request.operation_id in owner._reports, result))
                observed.set()
        return result

    monkeypatch.setattr(owner, "_complete_publication", defer_completed_annotations)
    monkeypatch.setattr(owner, "_read_report_async", observe_third_report)
    try:
        for request in requests[:2]:
            daemon.prepare_run(request, principal_id="caller")
        assert both_done.wait(60)
        daemon.prepare_run(requests[2], principal_id="caller")
        assert observed.wait(45)
        assert observations[0] == (2, False, None)
        release.set()
        daemon._wake.set()
        for request in requests:
            assert daemon.wait_operation(request.operation_id, timeout=45).operation.state == "applied"
    finally:
        release.set()
        daemon.stop()
