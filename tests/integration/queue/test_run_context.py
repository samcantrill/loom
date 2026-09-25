"""Context crosses the real preparation journal, authority and native adapters."""

from dataclasses import replace
import json
import sqlite3
from threading import Event
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.diagnostics.run_inspection import RunInspectionProjection
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.runs import SubmissionContext
from loom.io.uris import uri_to_path
from tests.integration.queue.test_preparation_operations import _service, _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("case", ["authored", "merged", "payload", "boundary"])
def test_initial_effective_tag_limits_precede_binding_and_execution(tmp_path, case):
    service = _service(tmp_path)
    path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(path.read_text())
    tags = {str(i): "v" for i in range(129 if case == "authored" else 128)}
    context = SubmissionContext(tags={"extra": "v"}) if case == "merged" else None
    if case == "payload":
        tags = {str(i): "x" * 1024 for i in range(48)}
    elif case == "boundary":
        tags.pop("127")
        tags["é" * 64] = "é" * 512
    config["runtime"]["tags"] = tags
    path.write_text(json.dumps(config))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = RunRequest(replace(_request(), context=context), "tag-limit-run")
        daemon.start_run(request, principal_id="caller")
        operation: Any = daemon.wait_operation(request.preparation.operation_id, timeout=90).operation
        if case == "boundary":
            assert operation.state == "applied", operation
            uri = operation.result["prepared_run"]["run_uri"]
            factory = service.daemon.coordinator_authority_factory
            assert factory is not None
            annotations = factory(uri).read_run_annotations(uri)
            assert annotations is not None and annotations.tags == tags
            daemon._wait("tag-limit-run", timeout_seconds=60)
        else:
            assert operation.state == "failed", operation
            assert operation.code == "invalid_context"
            assert operation.result["prepared_run"] is None
            assert operation.result.get("binding") is None
            with daemon._connection() as conn:
                assert conn.execute("SELECT 1 FROM managed_admissions WHERE queue_item_id = ?", ("tag-limit-run",)).fetchone() is None
            # Publication can precede validation, but target lifecycle and outputs cannot.
            uri = (service.daemon.run_store_root / "target-1").as_uri()
            authority = SQLitePerRunAuthorityStore(uri)
            assert authority.read_run_annotations(uri) is None
            assert authority.open_run(uri).status.value in {"CREATED", "PLANNED"}
            assert all(stage.status.value == "PENDING" for stage in authority.open_run(uri).stages)
    finally:
        daemon.stop()


def test_oversized_legacy_projection_is_partial_and_nonmutating(tmp_path):
    from loom.queue._run_context import get_run_context

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = _request()
        daemon.prepare_run(request, principal_id="caller")
        operation: Any = daemon.wait_operation(request.operation_id, timeout=60).operation
        assert operation.state == "applied", operation
        uri = operation.result["prepared_run"]["run_uri"]
        run_dir = uri_to_path(uri)
        database = run_dir / ".loom" / "authority.sqlite3"
        with sqlite3.connect(database) as conn:
            conn.execute("DELETE FROM run_annotations")
        store = LocalRunStore(service.daemon.run_store_root)
        legacy = {"tags": {str(i): "value" for i in range(129)}, "notes": ["retained legacy note"]}
        store.write_runtime_metadata(uri, legacy)
        runtime_before = (run_dir / "runtime.json").read_bytes()
        authority_before = SQLitePerRunAuthorityStore(uri).open_run(uri).to_dict()
        context = get_run_context(daemon, uri, None)
        assert context.annotations is None
        assert "legacy_runtime_annotations_unrepresentable" in context.unavailable
        assert context.initializer_submission is None
        assert (run_dir / "runtime.json").read_bytes() == runtime_before
        assert store.read_runtime_metadata(uri) == legacy
        assert SQLitePerRunAuthorityStore(uri).open_run(uri).to_dict() == authority_before
        with sqlite3.connect(database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM run_annotations").fetchone()[0] == 0
        from loom.queue._run_context import annotation_operation

        store.write_runtime_metadata(uri, {"tags": {"legacy": "retained"}, "notes": ["old observation"]})
        legacy_bytes = (run_dir / "runtime.json").read_bytes()
        changed = cast(Any, annotation_operation(daemon, "patch_run_annotations",
            {"run_uri": uri, "mutation_id": "first-write", "patch": {"expected_revision": 0, "set_tags": {"new": "label"}}}, "native-caller"))
        assert changed.revision == 1 and changed.tags == {"legacy": "retained", "new": "label"}
        notes = cast(Any, annotation_operation(daemon, "list_run_notes", {"run_uri": uri, "limit": 50, "cursor": None}, "native-caller"))
        assert notes.notes[0].source == "legacy_runtime"
        assert notes.notes[0].author is notes.notes[0].created_at is None
        assert (run_dir / "runtime.json").read_bytes() == legacy_bytes
        assert SQLitePerRunAuthorityStore(uri).open_run(uri).to_dict() == authority_before
    finally:
        daemon.stop()


@pytest.mark.parametrize("late_failure", [False, True])
def test_native_context_replay_cli_and_inert_inspection(tmp_path, capsys, late_failure):
    from loom.cli.main import main

    service = _service(tmp_path)
    config = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(config.read_text())
    authored["runtime"]["tags"] = {"model": "authored", "baseline": "kept"}
    if late_failure:
        first = authored["pipeline"]["stages"][0]
        authored["pipeline"]["stages"].append(
            {
                **first,
                "name": "later",
                "depends_on": ["produce"],
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.FailingStage"
                },
                "config": {},
            }
        )
    config.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    inspection = RunInspectionProjection(
        run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon
    )
    server = LocalDaemonSocketServer(
        daemon,
        service.daemon.endpoint,
        inspect_run=lambda uri: inspection.inspect(uri).to_dict(),
    )
    server.start()
    try:
        request: Any = RunRequest(
            replace(
                _request(),
                context=SubmissionContext(
                    "reason",
                    {"model": "caller", "study": "example"},
                    {
                        "revision": 3,
                        "status": "caller-only",
                        "_target_": "never.import.this",
                    },
                ),
            ),
            "context-run",
        )
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            accepted: Any = client.start_run(request)
            original = accepted.result["submission"]
            assert original["accepted_at"]
            assert original["principal_id"] != "caller-only"
            assert cast(Any, client.start_run(request).result)["submission"] == original
            with pytest.raises(CoordinatorClientError) as error:
                client.start_run(
                    replace(
                        request,
                        preparation=replace(
                            request.preparation, context=SubmissionContext("changed")
                        ),
                    )
                )
            assert error.value.code == "conflict"
            operation: Any = daemon.wait_operation(
                request.preparation.operation_id, timeout=60
            ).operation
            assert operation.state == "applied", operation
            uri = operation.result["prepared_run"]["run_uri"]
            daemon._wait("context-run", timeout_seconds=60)
            context: Any = client.get_run_context(uri)
            assert context.annotations.description == "reason"
            assert context.annotations.tags["model"] == "caller"
            assert context.annotations.tags["baseline"] == "kept"
            assert context.annotations.metadata["revision"] == 3
            assert (
                context.initializer_submission["context"]
                == request.preparation.context.to_dict()
            )
            assert context.submission_count == 1
            assert context.inspection is not None
            if late_failure:
                assert {
                    stage["stage_name"]: stage["state"]
                    for stage in context.inspection["stages"]
                } == {"produce": "SUCCEEDED", "later": "FAILED"}
                assert any(
                    location["kind"] == "artifact"
                    for location in context.inspection["locations"]
                )
            assert context.unavailable == ()
            assert (
                main(
                    [
                        "runs",
                        "context",
                        uri,
                        "--endpoint",
                        str(service.daemon.endpoint),
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            output = json.loads(capsys.readouterr().out)
            assert output["result"]["annotations"]["description"] == "reason"
            snapshot = SQLitePerRunAuthorityStore(uri).open_run(uri).to_dict()
            client.patch_run_annotations(uri, mutation_id="post-completion", expected_revision=1, set_tags={"review": "pending"})
            client.append_run_note(uri, mutation_id="post-completion-note", text="Observed committed results")
            after_inspection = client.get_run_context(uri).inspection
            assert after_inspection is not None
            assert after_inspection["stages"] == context.inspection["stages"]
            assert after_inspection["locations"] == context.inspection["locations"]
            assert SQLitePerRunAuthorityStore(uri).open_run(uri).to_dict() == snapshot
    finally:
        server.stop()
        daemon.stop()


def test_restart_after_authority_initialization_before_binding(tmp_path, monkeypatch):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    persisted = Event()
    resume = Event()
    initialize = SQLitePerRunAuthorityStore.initialize_run_annotations

    def interrupted(self, *args, **kwargs):
        result = initialize(self, *args, **kwargs)
        persisted.set()
        if not resume.is_set():
            raise OSError("lost annotation acknowledgement")
        return result

    monkeypatch.setattr(
        SQLitePerRunAuthorityStore, "initialize_run_annotations", interrupted
    )
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    request = RunRequest(
        replace(_request(), context=SubmissionContext("retained")), "context-run"
    )
    try:
        daemon.start_run(request, principal_id="caller")
        assert persisted.wait(60)
        # The authority effect may exist; target admission must still await binding.
        operation: Any = daemon.operation(request.preparation.operation_id)
        assert operation.result["prepared_run"] is None
    finally:
        daemon.stop()
    resume.set()
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        operation = daemon.wait_operation(
            request.preparation.operation_id, timeout=60
        ).operation
        assert operation.state == "applied", operation
        uri = operation.result["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        annotation: Any = factory(uri).read_run_annotations(uri)
        assert annotation.description == "retained"
        assert annotation.initializer_operation_id == request.preparation.operation_id
        assert annotation.revision == 1
    finally:
        daemon.stop()


def test_failed_preparation_keeps_original_intent_without_run(tmp_path):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = replace(
            _request(),
            config_path="missing.yaml",
            context=SubmissionContext("failed reason", {"customer": "example"}),
        )
        daemon.prepare_run(request, principal_id="authenticated-caller")
        operation: Any = daemon.wait_operation(
            request.operation_id, timeout=60
        ).operation
        assert operation.state == "failed", operation
        assert operation.result["prepared_run"] is None
        assert (
            operation.result["submission"]["context"]["description"] == "failed reason"
        )
        assert operation.result["submission"]["principal_id"] == "authenticated-caller"
    finally:
        daemon.stop()


def test_reconciled_submissions_retain_reasons_without_relabeling(tmp_path):
    from tests.integration.queue.test_reconciled_runs import (
        _reconciled_service,
        _reconciled_request,
    )
    from loom.queue._run_context import get_run_context

    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        uris = []
        for operation_id, reason in (
            ("first", "initial reason"),
            ("second", "second reason"),
        ):
            request = _reconciled_request(operation_id)
            request = replace(
                request,
                preparation=replace(
                    request.preparation,
                    context=SubmissionContext(reason, {"purpose": reason}),
                ),
            )
            daemon.start_run(request, principal_id="caller")
            operation: Any = daemon.wait_operation(operation_id, timeout=90).operation
            assert operation.state == "applied", operation
            uris.append(operation.result["prepared_run"]["run_uri"])
            assert operation.result["submission"]["context"]["description"] == reason
            daemon._wait(operation.result["queue_item_id"], timeout_seconds=60)
        assert uris[0] == uris[1]
        context: Any = get_run_context(daemon, uris[0], None)
        assert context.annotations.description == "initial reason"
        assert context.annotations.tags["purpose"] == "initial reason"
        assert context.submission_count == 2
        assert {item["operation_id"] for item in context.submissions} == {
            "first",
            "second",
        }
        authority = SQLitePerRunAuthorityStore(uris[0])
        snapshot = authority.open_run(uris[0]).to_dict()
        authority.mutate_run_annotations(uris[0], "caller", "reused-review", "patch_run_annotations",
            {"expected_revision": 1, "set_tags": {"review": "done"}}, SubmissionContext())
        authority.mutate_run_annotations(uris[0], "caller", "reused-note", "append_run_note", {"text": "Reviewed reused output"}, SubmissionContext())
        assert authority.open_run(uris[0]).to_dict() == snapshot
        assert get_run_context(daemon, uris[0], None).initializer_submission == context.initializer_submission
    finally:
        daemon.stop()


@pytest.mark.parametrize("backend,https", [("embedded", False), ("embedded", True), ("authenticated", False), ("authenticated", True)])
def test_native_annotation_concurrency_lost_reply_restart_and_cli(tmp_path, monkeypatch, capsys, backend, https):
    from concurrent.futures import ThreadPoolExecutor
    from loom.cli.main import main
    from loom.queue._coordinator_control import dispatch_control
    from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.authority.test_coordinator_authority_api import _authority_factory

    factory = _authority_factory(tmp_path)[1] if backend == "authenticated" else None
    with _coordinator(tmp_path, https=https, authority_factory=factory) as (service, daemon, _):
        def connect():
            return CoordinatorClient.from_connection_file(tmp_path / "client.json") if https else CoordinatorClient.from_unix_socket(service.daemon.endpoint)

        with connect() as client:
            request = replace(_request(), context=SubmissionContext("original", {"keep": "yes"}, {"n": 3}))
            client.prepare_run(request)
            operation: Any = daemon.wait_operation(request.operation_id, timeout=60).operation
            assert operation.state == "applied", operation
            uri = operation.result["prepared_run"]["run_uri"]
            selected_factory = service.daemon.coordinator_authority_factory
            assert selected_factory is not None
            authority = selected_factory(uri)
            before = authority.open_run(uri).to_dict()
            run_dir = uri_to_path(uri)
            fingerprints = {path.relative_to(run_dir): path.read_bytes() for path in run_dir.rglob("*.json") if ".loom" not in path.parts}
            original_context = client.get_run_context(uri)

            def patch(name):
                with connect() as other:
                    try:
                        return other.patch_run_annotations(uri, mutation_id=name, expected_revision=1, set_tags={name: "yes"})
                    except CoordinatorClientError as exc:
                        return exc

            with ThreadPoolExecutor(2) as pool:
                values = list(pool.map(patch, ["a", "b"]))
            winner = next(item for item in values if not isinstance(item, CoordinatorClientError))
            loser = next(item for item in values if isinstance(item, CoordinatorClientError))
            assert loser.code == "conflict" and loser.ids["current_revision"] == 2
            assert loser.mutation_outcome == "not_applied"
            result = client.patch_run_annotations(uri, mutation_id="rebase", expected_revision=2,
                set_tags={"b" if "a" in winner.tags else "a": "yes"}, set_metadata={"null": None}, description=None)
            assert result.tags == {"keep": "yes", "a": "yes", "b": "yes"}
            assert result.metadata == {"n": 3, "null": None} and result.description is None
            transport = client._transport
            call = transport.call

            def lose_response(operation, payload, *args, **kwargs):
                response = call(operation, payload, *args, **kwargs)
                if operation == "append_run_note":
                    return {"ok": True, "result": {"acknowledgement": "lost"}}
                return response

            monkeypatch.setattr(transport, "call", lose_response)
            with pytest.raises(CoordinatorClientError) as lost:
                client.append_run_note(uri, mutation_id="lost-note", text="retained")
            assert lost.value.mutation_outcome == "unknown"
            assert lost.value.code == "invalid_response"
            assert lost.value.ids["mutation_id"] == "lost-note"
            monkeypatch.setattr(transport, "call", call)
            daemon.stop()
            daemon.start()
            note = client.append_run_note(uri, mutation_id="lost-note", text="retained")
            assert note.author and note.created_at and note.text == "retained"
            assert client.list_run_notes(uri).notes == (note,)
            if https:
                from loom.queue.agent_session_transport import RunInspectionHttpClient, RunInspectionTlsClientConfig, LocalDaemonAgentHttpClient, AgentTlsClientConfig
                from loom.queue.errors import QueueServiceError

                address = json.loads((tmp_path / "client.json").read_text())["transport"]["url"]
                tls = tmp_path / "tls"
                query_client = RunInspectionHttpClient(RunInspectionTlsClientConfig(address, tls / "ca.crt", tls / "query.crt", tls / "query.key"))
                assert query_client.list_run_notes(uri)["notes"] == [note.to_dict()]
                unauthorized = LocalDaemonAgentHttpClient(AgentTlsClientConfig(address, tls / "ca.crt", tls / "query.crt", tls / "query.key"))
                try:
                    with pytest.raises(QueueServiceError):
                        unauthorized._call("append_run_note", {"run_uri": uri, "mutation_id": "query-write", "text": "denied"}, role="query")
                finally:
                    unauthorized.close()
                assert client.list_run_notes(uri).notes == (note,)
            with pytest.raises(CoordinatorClientError) as conflict:
                client.patch_run_annotations(uri, mutation_id="lost-note", expected_revision=3)
            assert conflict.value.code == "conflict"
            with pytest.raises(CoordinatorClientError) as spoofed:
                client._native_call("append_run_note", {"run_uri": uri, "mutation_id": "spoof", "text": "note", "author": "admin"}, None)
            assert spoofed.value.code == "invalid_request"
            query = LocalDaemonPrincipal("readonly", LocalDaemonRole.QUERY)
            with pytest.raises(CoordinatorClientError) as denied:
                dispatch_control(daemon, query, "append_run_note", {"run_uri": uri, "mutation_id": "denied", "text": "no"}, transport="https", wait_slice=5, inspect_run=None)
            assert denied.value.code == "unauthorized" and denied.value.mutation_outcome == "not_applied"
            connection = ["--connection", str(tmp_path / "client.json")] if https else ["--endpoint", str(service.daemon.endpoint)]
            assert main(["runs", "annotate", uri, "--mutation-id", "cli-patch", "--patch", json.dumps({"expected_revision": 3, "remove_metadata": ["n"]}), *connection, "--format", "json"]) == 0
            assert json.loads(capsys.readouterr().out)["result"]["metadata"] == {"null": None}
            assert main(["runs", "notes", uri, "--mutation-id", "cli-note", "--text", "CLI observation", *connection, "--format", "json"]) == 0
            cli_note = json.loads(capsys.readouterr().out)["result"]
            assert cli_note["author"] == note.author
            assert main(["runs", "notes", uri, "--limit", "1", *connection, "--format", "json"]) == 0
            page = json.loads(capsys.readouterr().out)["result"]
            assert page["notes"] == [note.to_dict()] and page["next_cursor"]
            with pytest.raises(CoordinatorClientError) as oversized:
                client.patch_run_annotations(uri, mutation_id="oversized-result", expected_revision=4,
                    set_tags={str(index): "v" for index in range(126)})
            assert oversized.value.code == "invalid_request"
            assert oversized.value.mutation_outcome == "not_applied"
            unchanged = client.get_run_context(uri).annotations
            assert unchanged is not None and unchanged.revision == 4
            from loom.pipeline.stores.authority import AuthorityStoreError

            owner_type = type(authority)
            original_mutate = owner_type.mutate_run_annotations

            def lose_authority_acknowledgement(self, *args, **kwargs):
                result = original_mutate(self, *args, **kwargs)
                if args[2] == "lost-owner-note":
                    raise AuthorityStoreError("authority reply lost after commit")
                return result

            with monkeypatch.context() as patcher:
                patcher.setattr(owner_type, "mutate_run_annotations", lose_authority_acknowledgement)
                with pytest.raises(CoordinatorClientError) as uncertain:
                    client.append_run_note(uri, mutation_id="lost-owner-note", text="Owner acknowledgement lost")
                assert uncertain.value.code == "unavailable"
                assert uncertain.value.mutation_outcome == "unknown"
            replay = client.append_run_note(uri, mutation_id="lost-owner-note", text="Owner acknowledgement lost")
            assert sum(entry.note_id == replay.note_id for entry in client.list_run_notes(uri).notes) == 1
            assert authority.open_run(uri).to_dict() == before
            assert all((run_dir / path).read_bytes() == data for path, data in fingerprints.items())
            assert client.get_run_context(uri).initializer_submission == original_context.initializer_submission
