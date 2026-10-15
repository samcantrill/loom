"""Authorized native log reads preserve attempt identity and bounded payloads."""

from __future__ import annotations

from dataclasses import replace
from typing import cast, Any
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.cli.main import main
from loom.coordinator import CoordinatorClient, CoordinatorClientError
from loom.pipeline.stores import LocalRunStore
from loom.queue._coordinator_control import dispatch_control, decode_result
from loom.queue._remote_logs import MAX_LOG_BYTES, _tail
from loom.queue.local_daemon import (
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonOperation,
)
from tests.integration.config.test_cli_run_observation import _owner, _run, _counts
from tests.integration.queue.test_agent_session_transport import (
    native_control_endpoint as native_control_endpoint,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.fixture(scope="module")
def _completed(tmp_path_factory):
    with _owner(tmp_path_factory.mktemp("remote-logs")) as (selection, daemon):
        code, _, errors = _run(selection, identity="log-run")
        assert code == 0, errors.getvalue()
        operation = daemon.wait_operation("log-run", timeout=60).operation
        assert operation.state == "applied"
        retained = cast(Any, operation.result)["admission"]
        admission = daemon._wait(retained["queue_item_id"], timeout_seconds=60)
        assert admission.state.value == "SUCCEEDED"
        store = LocalRunStore(daemon.config.run_store_root)
        result = store.read_stage_worker_result(admission.run_uri, "produce", attempt=1)
        assert result is not None
        yield selection, daemon, admission, store, result


@pytest.fixture
def completed(_completed):
    for stream in ("stdout", "stderr"):
        path = Path(_completed[4][f"{stream}_path"])
        path.unlink(missing_ok=True)
        path.write_text(f"{stream} old\n{stream} recent\n")
    return _completed


def _client(completed):
    return CoordinatorClient.from_unix_socket(completed[1].config.endpoint)


def test_real_retained_attempt_cli_streams_and_read_only(completed, monkeypatch):
    selection, daemon, admission, store, worker = completed
    before = _counts(daemon)
    for stream in ("stdout", "stderr"):
        Path(worker[f"{stream}_path"]).write_text(f"{stream} old\n{stream} recent\n")
    # A stale local projection must never override the current retained source.
    store.write_stage_log(admission.run_uri, "produce", "stdout", "stale projection\n")
    with _client(completed) as client:
        both = client.read_run_logs("log-run", stage="produce", tail=1)
        for stream in ("stdout", "stderr"):
            single = client.read_run_logs(
                "log-run", stage="produce", stream=stream, tail=1
            )
            assert single["streams"] == [
                next(e for e in both["streams"] if e["stream"] == stream)
            ]
    assert both["attempt"] == 1
    assert both["admission_id"] == admission.admission_id
    assert all(
        e["text"].endswith("recent\n") and e["truncated"] for e in both["streams"]
    )
    assert str(daemon.config.run_store_root.parent) not in json.dumps(both)

    def no_start(*args, **kwargs):
        raise AssertionError("observation must not initialize services")

    monkeypatch.setattr(type(daemon), "initialize_deployment", no_start)
    for fmt in ("text", "json"):
        output, errors = io.StringIO(), io.StringIO()
        assert (
            main(
                [
                    "runs",
                    "logs",
                    "--deployment",
                    str(selection),
                    "--operation-id",
                    "log-run",
                    "--stage",
                    "produce",
                    "--stream",
                    "stderr",
                    "--tail",
                    "1",
                    "--format",
                    fmt,
                ],
                stdout=output,
                stderr=errors,
            )
            == 0
        ), errors.getvalue()
        if fmt == "json":
            assert (
                json.loads(output.getvalue())["result"]["streams"][0]["text"]
                == "stderr recent\n"
            )
        else:
            assert (
                "truncated=True" in output.getvalue()
                and "stderr recent" in output.getvalue()
            )
    assert _counts(daemon) == before


@pytest.mark.parametrize(
    "stage", ["unknown", "../secrets", "/etc/passwd", "..", "a\\b"]
)
def test_unknown_and_pathlike_stages_never_open_logs(completed, monkeypatch, stage):
    import loom.queue._remote_logs as logs

    monkeypatch.setattr(
        logs, "_tail", lambda *a: pytest.fail("invalid stage opened a log")
    )
    with _client(completed) as client, pytest.raises(CoordinatorClientError) as error:
        client.read_run_logs("log-run", stage=stage)
    assert error.value.code == (
        "not_found" if stage == "unknown" else "invalid_request"
    )


def test_missing_operation_and_non_run_operation(completed, monkeypatch):
    daemon = completed[1]
    with (
        _client(completed) as client,
        pytest.raises(CoordinatorClientError, match="not_found"),
    ):
        client.read_run_logs("absent", stage="produce")
    monkeypatch.setattr(
        daemon,
        "operation",
        lambda _: LocalDaemonOperation("other", "preparation", "applied", None, {}),
    )
    with (
        _client(completed) as client,
        pytest.raises(CoordinatorClientError, match="invalid_request"),
    ):
        client.read_run_logs("other", stage="produce")


def test_forbidden_role_and_unmanaged_run_do_not_read(completed, monkeypatch):
    import loom.queue._remote_logs as logs
    from loom.queue.local_daemon import AdmissionNotFoundError

    daemon = completed[1]
    payload = {
        "operation_id": "log-run",
        "stage": "produce",
        "stream": "both",
        "tail": 1,
    }
    monkeypatch.setattr(logs, "_tail", lambda *a: pytest.fail("unauthorized file read"))
    with pytest.raises(CoordinatorClientError) as error:
        dispatch_control(
            daemon,
            LocalDaemonPrincipal("agent", LocalDaemonRole.AGENT),
            "read_run_logs",
            payload,
            transport="https",
            wait_slice=1,
            inspect_run=None,
        )
    assert error.value.code == "unauthorized"

    def missing(_):
        raise AdmissionNotFoundError("unmanaged")

    monkeypatch.setattr(daemon, "admission_for_run_uri", missing)
    with _client(completed) as client, pytest.raises(CoordinatorClientError) as error:
        client.read_run_logs("log-run", stage="produce")
    assert error.value.code == "not_found"


@pytest.mark.parametrize("tail", [0, -1, True, 1.5])
def test_positive_tail_required(completed, tail):
    with (
        _client(completed) as client,
        pytest.raises(CoordinatorClientError, match="invalid_request"),
    ):
        client.read_run_logs("log-run", stage="produce", tail=tail)


def test_bounded_before_read_huge_line_and_replacement(tmp_path, monkeypatch):
    import loom.queue._remote_logs as logs

    path = tmp_path / "stdout"
    path.write_bytes(b"x" * (MAX_LOG_BYTES * 10))
    original = logs.os.pread
    calls = []

    def bounded(fd, count, offset):
        calls.append((count, offset))
        assert count <= MAX_LOG_BYTES
        return original(fd, count, offset)

    monkeypatch.setattr(logs.os, "pread", bounded)
    result = _tail(path, 100000)
    assert result["text"] == "x" * MAX_LOG_BYTES and result["truncated"]
    assert calls == [(MAX_LOG_BYTES, MAX_LOG_BYTES * 9)]
    path.write_bytes(b"\xff" * MAX_LOG_BYTES + b"END")
    result = _tail(path, 100)
    assert result["decoding_replaced"] and result["truncated"]
    assert result["text"].endswith("END") and "\ufffd" in result["text"]
    assert len(result["text"].encode()) <= MAX_LOG_BYTES
    path.write_bytes(b"a\nb\nc\n")
    assert _tail(path, 2)["text"] == "b\nc\n"
    path.write_bytes(b"")
    assert _tail(path, 1) == {
        "availability": "available",
        "text": "",
        "truncated": False,
        "decoding_replaced": False,
    }


def test_missing_pending_unavailable_and_attempt_mismatch(completed, monkeypatch):
    import loom.queue._remote_logs as logs

    daemon, worker = completed[1], completed[4]
    with monkeypatch.context() as patch:
        patch.setattr(
            daemon,
            "operation",
            lambda _: LocalDaemonOperation("pending", "run", "pending", None, {}),
        )
        with _client(completed) as client:
            pending = client.read_run_logs("pending", stage="produce")
        assert all(
            e["availability"] == "pending" and e["text"] is None
            for e in pending["streams"]
        )
    with monkeypatch.context() as patch:
        patch.setattr(
            logs, "_authority", lambda *a: (_ for _ in ()).throw(OSError("owner down"))
        )
        with _client(completed) as client:
            unavailable = client.read_run_logs("log-run", stage="produce")
        assert all(e["availability"] == "unavailable" for e in unavailable["streams"])
    path = Path(worker["stdout_path"])
    path.unlink(missing_ok=True)
    with _client(completed) as client:
        missing = client.read_run_logs("log-run", stage="produce", stream="stdout")
    assert missing["streams"][0]["availability"] == "missing"
    assert missing["streams"][0]["log_id"] is not None
    with monkeypatch.context() as patch:
        authority = logs._authority(daemon, completed[2].run_uri)
        snapshot = authority.open_run(completed[2].run_uri)
        stage = snapshot.stages[0]
        changed = SimpleNamespace(
            revision=snapshot.revision,
            stages=[
                SimpleNamespace(
                    stage_name=stage.stage_name,
                    status=stage.status,
                    attempts=[SimpleNamespace(attempt=2)],
                )
            ],
        )
        patch.setattr(
            logs, "_authority", lambda *a: SimpleNamespace(open_run=lambda _: changed)
        )
        with _client(completed) as client:
            mismatch = client.read_run_logs("log-run", stage="produce")
        assert mismatch["attempt"] == 2
        assert all(
            e["availability"] == "unavailable" and e["text"] is None
            for e in mismatch["streams"]
        )


def test_older_peer_refused_before_log_dispatch(completed, monkeypatch):
    import loom.queue._coordinator_control as control

    original = control._connection_description
    monkeypatch.setattr(
        control,
        "_connection_description",
        lambda *args: replace(original(*args), capabilities=("daemon-control-v1",)),
    )
    monkeypatch.setattr(
        completed[1], "operation", lambda _: pytest.fail("old peer dispatched logs")
    )
    with _client(completed) as client, pytest.raises(CoordinatorClientError) as error:
        client.read_run_logs("log-run", stage="produce")
    assert error.value.code == "unsupported_capability"
    assert error.value.ids["missing_capability"] == "bounded-run-logs-v1"


def test_new_codec_rejects_unbounded_or_path_augmented_reply(completed):
    with _client(completed) as client:
        value = client.read_run_logs("log-run", stage="produce")
    assert decode_result("read_run_logs", value) == value
    for invalid in (
        {**value, "path": "/private"},
        {
            **value,
            "streams": [
                {
                    **value["streams"][0],
                    "availability": "available",
                    "log_id": "a" * 64,
                    "text": "x" * (MAX_LOG_BYTES + 1),
                }
            ],
        },
    ):
        with pytest.raises(ValueError):
            decode_result("read_run_logs", invalid)


def test_https_real_authorization_and_codec(
    native_control_endpoint, completed, monkeypatch
):
    daemon, _, connection, _ = native_control_endpoint
    source = completed[1]
    # The real TLS principal/role and codecs surround the same retained owners.
    monkeypatch.setattr(daemon, "operation", source.operation)
    monkeypatch.setattr(daemon, "admission", source.admission)
    monkeypatch.setattr(daemon, "admission_for_run_uri", source.admission_for_run_uri)
    import loom.queue._remote_logs as logs

    original = logs._authority
    monkeypatch.setattr(logs, "_authority", lambda _, uri: original(source, uri))
    qualify = logs._qualified_path
    monkeypatch.setattr(logs, "_qualified_path", lambda _, store, attempt, stream, ref: qualify(source, store, attempt, stream, ref))
    with CoordinatorClient.from_connection_file(connection) as client:
        result = client.read_run_logs(
            "log-run", stage="produce", stream="stderr", tail=1
        )
    assert result["attempt"] == 1
    assert result["streams"][0]["text"] == "stderr recent\n"
    assert result["streams"][0]["availability"] == "available"


def test_unpublished_stage_and_absent_terminal_reference(completed, monkeypatch):
    import loom.queue._remote_logs as logs

    daemon, _, store = completed[1:4]
    monkeypatch.setattr(
        type(store), "read_stage_worker_result", lambda *args, **kw: None
    )
    with _client(completed) as client:
        result = client.read_run_logs("log-run", stage="produce")
    assert all(
        e["availability"] == "missing" and e["log_id"] is None
        for e in result["streams"]
    )
    snapshot = logs._authority(daemon, completed[2].run_uri).open_run(
        completed[2].run_uri
    )
    stage = snapshot.stages[0]
    snapshot = SimpleNamespace(
        revision=snapshot.revision,
        stages=[
            SimpleNamespace(
                stage_name=stage.stage_name,
                status=SimpleNamespace(value="RUNNING"),
                attempts=stage.attempts,
            )
        ],
    )
    monkeypatch.setattr(
        logs, "_authority", lambda *a: SimpleNamespace(open_run=lambda _: snapshot)
    )
    with _client(completed) as client:
        result = client.read_run_logs("log-run", stage="produce")
    assert all(
        e["availability"] == "pending" and e["text"] is None for e in result["streams"]
    )


def test_retained_symlink_cannot_expose_private_file(completed, tmp_path):
    secret = tmp_path / "connection-key"
    secret.write_text("PRIVATE CREDENTIAL")
    path = Path(completed[4]["stdout_path"])
    path.unlink()
    path.symlink_to(secret)
    try:
        with _client(completed) as client:
            result = client.read_run_logs("log-run", stage="produce", stream="stdout")
        assert result["streams"][0]["availability"] == "unavailable"
        assert "PRIVATE" not in json.dumps(result)
    finally:
        path.unlink()


def test_wire_huge_invalid_utf8_and_strict_request(completed):
    Path(completed[4]["stderr_path"]).write_bytes(b"\xff" * (MAX_LOG_BYTES * 3))
    with _client(completed) as client:
        result = client.read_run_logs("log-run", stage="produce", stream="stderr")
        entry = result["streams"][0]
        assert entry["availability"] == "available"
        assert entry["decoding_replaced"] and entry["truncated"]
        assert len(entry["text"].encode()) <= MAX_LOG_BYTES
        with pytest.raises(CoordinatorClientError, match="invalid_request"):
            client._native_call(
                "read_run_logs",
                {
                    "operation_id": "log-run",
                    "stage": "produce",
                    "stream": "stdout",
                    "tail": 1,
                    "path": "/private",
                },
            )


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_executor_result_cannot_authorize_unrelated_regular_file(
    completed, tmp_path, monkeypatch, stream
):
    import loom.queue._remote_logs as logs

    _, _, admission, store, worker = completed
    secret = tmp_path / "coordinator-connection.json"
    secret.write_text("PRIVATE CONNECTION CREDENTIAL")
    # StageExecutionResult can choose stdout_path/stderr_path; the native
    # _result_from_execution_result and publication preserve that ordinary field.
    changed = {**worker, f"{stream}_path": str(secret)}
    store.write_stage_worker_result(admission.run_uri, "produce", changed, attempt=1)
    original = logs._tail

    def checked(path, lines):
        assert path != secret, "unqualified result reference reached the file reader"
        return original(path, lines)

    monkeypatch.setattr(logs, "_tail", checked)
    try:
        with _client(completed) as client:
            result = client.read_run_logs("log-run", stage="produce", stream=stream)
        assert result["streams"][0]["availability"] == "unavailable"
        assert result["streams"][0]["text"] is None
        assert "PRIVATE" not in json.dumps(result)
        assert str(secret) not in json.dumps(result)
    finally:
        store.write_stage_worker_result(admission.run_uri, "produce", worker, attempt=1)


def test_resident_source_requires_owning_assignment(completed, monkeypatch):
    import loom.queue._remote_logs as logs
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace

    original = _ResidentAssignmentWorkspace.read_request

    def other_attempt(path):
        return replace(original(path), attempt_id="another-native-attempt")

    monkeypatch.setattr(_ResidentAssignmentWorkspace, "read_request", other_attempt)
    monkeypatch.setattr(logs, "_tail", lambda *a: pytest.fail("unowned source opened"))
    with _client(completed) as client:
        result = client.read_run_logs("log-run", stage="produce")
    assert all(e["availability"] == "unavailable" for e in result["streams"])
