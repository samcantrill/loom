"""Fleet text and JSON present the same host selection and native evidence."""

from contextlib import nullcontext
from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from loom.cli.main import main
from loom.fleet import administration
from loom.queue.operations import OperatorObservation
from tests.integration.fleet.test_configuration import inventory

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def invoke(command, path, *args):
    output, error = io.StringIO(), io.StringIO()
    code = main(["fleet", command, "--fleet", str(path), *args], stdout=output, stderr=error)
    assert not error.getvalue(), error.getvalue()
    return code, output.getvalue()


def capture_acquisition(monkeypatch, module, name):
    acquire = getattr(module, name)
    reports = []

    def capture(*args, **kwargs):
        report = acquire(*args, **kwargs)
        reports.append(deepcopy(report))
        return report

    monkeypatch.setattr(module, name, capture)
    return reports


def test_fleet_status_displays_native_freshness_and_independent_declaration_failures(tmp_path, monkeypatch):
    path = inventory(tmp_path)
    config = json.loads(path.read_text())
    config["agents"]["gpu02"] = dict(config["agents"]["gpu01"], host="second-ssh")
    path.write_text(json.dumps(config))
    when = "2026-06-05T12:00:00Z"

    def observation(name, value, freshness="current", reason=None):
        return OperatorObservation(name, when, "revision-3", freshness, "available", value, reason)

    def agent(name):
        if name == "gpu02":
            return observation(name, {"state": "ACTIVE"}, "retained", "observation_stale")
        return observation(name, {"state": "ACTIVE"})

    operator = SimpleNamespace(observe_status=lambda: observation("coord-id", {"service_health": "healthy"}),
                               observe_agent=agent)
    monkeypatch.setattr(administration, "load_coordinator_connection_file",
                        lambda _: SimpleNamespace(expected_coordinator_id="coord-id"))
    monkeypatch.setattr(administration.CoordinatorOperatorClient, "from_connection_file",
                        lambda *a, **kw: nullcontext(operator))
    reports = capture_acquisition(monkeypatch, administration, "observe")
    monkeypatch.setenv("COLUMNS", "150")
    args = ("--connection", "selected", "--profile", "missing")
    code, output = invoke("status", path, *args)
    assert code == 0
    assert "Qualification: failed" in output
    for name, state, freshness in (("coordinator", "healthy", "current"), ("gpu01", "ACTIVE", "current"),
                                   ("gpu02", "ACTIVE", "retained")):
        line = next(line for line in output.splitlines() if line.startswith(name))
        assert state in line and freshness in line
    assert "observation_stale" in output
    assert output.index("gpu02") < output.index("Declaration: invalid_or_unavailable_native_declaration")
    assert "Profile missing: unavailable_or_ambiguous_identity" in output
    assert "revision-3" not in output
    code, explained = invoke("status", path, *args, "--explain")
    assert code == 0
    for value in (when, "owner=coord-id", "revision=revision-3", "host_installation_unavailable",
                  "host_storage_unavailable"):
        assert value in explained

    code, original = invoke("status", path, *args, "--format", "json")
    assert code == 0 and json.loads(original) == reports[-1]
    monkeypatch.setenv("COLUMNS", "32")
    code, narrow = invoke("status", path)
    assert code == 0
    assert "HEALTH / SESSION: unknown" in narrow
    assert "operator_connection_not_selected" in narrow.replace("\n", "").replace(" ", "")
    assert len(reports) == 4
