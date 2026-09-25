"""Discovery crosses real Unix/HTTPS authorization and owning metadata readers."""

from dataclasses import replace
import json
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.runs import (
    AllOf,
    AnyOf,
    CollectionScope,
    Compare,
    ContainsText,
    Field,
    JobQuery,
    ManagedScope,
    Not,
    Order,
    RunQuery,
    SubmissionContext,
    SubmissionQuery,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("https", [False, True])
def test_native_query_routes_context_text_scope_and_cli(
    tmp_path, https, capsys, monkeypatch
):
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.queue.test_preparation_operations import _request
    from loom.cli.main import main

    with _coordinator(tmp_path, https=https) as (service, daemon, _):

        def connect():
            return (
                CoordinatorClient.from_connection_file(tmp_path / "client.json")
                if https
                else CoordinatorClient.from_unix_socket(service.daemon.endpoint)
            )

        with connect() as client:
            assert "run-query-v1" in client.describe_connection().capabilities
            assert client.search_runs(RunQuery()).items == ()
            request = RunRequest(
                replace(
                    _request(),
                    context=SubmissionContext(
                        "original motivation",
                        {"dataset.version": "v1"},
                        {"revision": 3, "_target_": "never.import.me"},
                    ),
                ),
                "query-run",
            )
            client.start_run(request)
            operation: Any = daemon.wait_operation(
                request.preparation.operation_id, timeout=90
            ).operation
            assert operation.state == "applied", operation
            uri = operation.result["prepared_run"]["run_uri"]
            daemon._wait("query-run", timeout_seconds=60)
            before = client.search_runs(
                RunQuery(where=Compare(Field("tags", ("dataset.version",)), "eq", "v1"))
            )
            assert [item["identity"] for item in before.items] == [uri]
            assert client.tag_keys().items == ({"key": "dataset.version"},)
            assert client.tag_values(ManagedScope(), "dataset.version").items == (
                {"value": "v1"},
            )
            assert (
                before.items[0]["sources"]["submission.context"]["description"]
                == "original motivation"
            )
            assert (
                before.items[0]["native"]["submitted_at"]
                == operation.result["submission"]["accepted_at"]
            )
            client.patch_run_annotations(
                uri,
                mutation_id="edit",
                expected_revision=1,
                description="current observation",
            )
            note = client.append_run_note(
                uri, mutation_id="note", text="Straße follow-up"
            )
            for field, text, source in [
                (
                    Field("submission.context", ("description",)),
                    "original",
                    "submission.context",
                ),
                (Field("description"), "current", "description"),
                (Field("notes", ("text",)), "STRASSE", "notes"),
            ]:
                page = client.search_runs(RunQuery(where=ContainsText(field, text)))
                assert page.items[0]["matches"][0]["source"] == source
                if source == "notes":
                    assert page.items[0]["matches"][0]["note_id"] == note.note_id
            jobs = client.search_jobs(
                JobQuery(
                    where=Compare(
                        Field("native", ("queue_item_id",)), "eq", "query-run"
                    )
                )
            )
            assert len(jobs.items) == 1 and jobs.items[0]["native"]["run_uri"] == uri
            assert "job_associations" in jobs.items[0]["sources"]
            assignments = jobs.items[0]["sources"]["job_associations"]["assignment"][
                "assignments"
            ]
            assert assignments and assignments[0]["stage_name"] == "produce"
            assert assignments[0]["assignment_id"] and assignments[0]["attempt"] == 1
            submissions = client.search_submissions(
                SubmissionQuery(order_by=(Order("submitted_at", True),))
            )
            assert (
                submissions.items[0]["native"]["operation_id"]
                == request.preparation.operation_id
            )
            chronological = client.search_runs(
                RunQuery(order_by=(Order("submitted_at", True),))
            )
            assert chronological.items[0]["identity"] == uri
            fields: Any = client.query_fields()
            assert "git_commit" in fields["native_fields"]
            with pytest.raises(CoordinatorClientError) as unsupported:
                client._native_call(
                    "search_runs",
                    {
                        "query": {
                            "schema_version": 1,
                            "scope": {
                                "kind": "collection",
                                "name": "/another/deployment",
                            },
                        }
                    },
                    None,
                )
            assert unsupported.value.code == "invalid_request"
            connection = (
                ["--connection", str(tmp_path / "client.json")]
                if https
                else ["--endpoint", str(service.daemon.endpoint)]
            )
            assert (
                main(
                    [
                        "runs",
                        "search",
                        "--tag",
                        "dataset.version=v1",
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert (
                json.loads(capsys.readouterr().out)["result"]["items"][0]["identity"]
                == uri
            )
            if https:
                from loom.queue.agent_session_transport import (
                    RunInspectionHttpClient,
                    RunInspectionTlsClientConfig,
                )

                address = json.loads((tmp_path / "client.json").read_text())[
                    "transport"
                ]["url"]
                tls = tmp_path / "tls"
                reader = RunInspectionHttpClient(
                    RunInspectionTlsClientConfig(
                        address, tls / "ca.crt", tls / "query.crt", tls / "query.key"
                    )
                )
                assert (
                    cast(
                        Any,
                        reader.search_runs(
                            RunQuery(
                                where=Compare(Field("native", ("run_uri",)), "eq", uri)
                            )
                        ),
                    )["items"][0]["identity"]
                    == uri
                )
                assert reader.query_fields()["native_fields"] == fields["native_fields"]
                assert reader.tag_keys(ManagedScope())["items"] == [
                    {"key": "dataset.version"}
                ]
                assert reader.tag_values(ManagedScope(), "dataset.version")[
                    "items"
                ] == [{"value": "v1"}]
            collection = client.search_runs(RunQuery(scope=CollectionScope()))
            assert uri in [item["identity"] for item in collection.items]
            paged = RunQuery(limit=1)
            first = client.search_runs(paged)
            assert first.next_cursor
            live_query = RunQuery(
                limit=1,
                where=AnyOf(
                    (
                        Compare(
                            Field("native", ("run_uri",)),
                            "eq",
                            first.items[0]["identity"],
                        ),
                        Compare(Field("metadata", ("revision",)), "eq", 3),
                    )
                ),
            )
            live_first = client.search_runs(live_query)
            assert live_first.next_cursor
            annotations = client.get_run_context(uri).annotations
            assert annotations is not None
            client.patch_run_annotations(
                uri,
                mutation_id="between-pages",
                expected_revision=annotations.revision,
                set_metadata={"revision": 4},
            )
            live_next = client.search_runs(
                replace(live_query, cursor=live_first.next_cursor)
            )
            assert live_next.items == () and live_next.next_cursor is None
            with pytest.raises(CoordinatorClientError) as changed_query:
                client.search_runs(replace(paged, cursor=first.next_cursor, limit=2))
            assert changed_query.value.code == "invalid_cursor"
            with pytest.raises(CoordinatorClientError) as changed_scope:
                client.search_runs(
                    replace(paged, cursor=first.next_cursor, scope=CollectionScope())
                )
            assert changed_scope.value.code == "invalid_cursor"

            def unavailable_authority(_uri):
                raise OSError("selected authority is disconnected")

            with monkeypatch.context() as patcher:
                patcher.setattr(
                    daemon,
                    "config",
                    replace(
                        daemon.config,
                        coordinator_authority_factory=unavailable_authority,
                    ),
                )
                unknown = client.search_runs(
                    RunQuery(
                        where=Not(
                            Compare(Field("native", ("status",)), "eq", "SUCCEEDED")
                        )
                    )
                )
                assert unknown.items == () and not unknown.complete
                assert any(
                    warning["code"] == "authority_unavailable"
                    for warning in unknown.warnings
                )


def test_disconnected_scope_does_not_start_or_create_services(tmp_path):
    endpoint = tmp_path / "absent" / "coordinator.sock"
    with CoordinatorClient.from_unix_socket(endpoint) as client:
        with pytest.raises(CoordinatorClientError):
            client.search_runs(RunQuery())
    assert not endpoint.parent.exists()


def test_failed_and_unbound_requests_retain_original_context(tmp_path):
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.queue.test_preparation_operations import _request

    with _coordinator(tmp_path) as (service, daemon, _):
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            request = replace(
                _request(),
                config_path="missing.yaml",
                context=SubmissionContext("failed original", {"customer": "example"}),
            )
            client.prepare_run(request)
            assert (
                daemon.wait_operation(request.operation_id, timeout=60).operation.state
                == "failed"
            )
            page = client.search_submissions(
                SubmissionQuery(
                    where=AllOf(
                        (
                            Compare(Field("native", ("state",)), "eq", "failed"),
                            ContainsText(
                                Field("submission.context", ("description",)),
                                "failed original",
                            ),
                        )
                    )
                )
            )
            assert len(page.items) == 1
            assert page.items[0]["native"]["run_uri"] is None
            assert page.items[0]["identity"] == request.operation_id


def test_reconciled_submissions_remain_separate_from_run_initializer(tmp_path):
    from tests.integration.queue.test_reconciled_runs import (
        _reconciled_service,
        _reconciled_request,
    )
    from loom.queue import LocalDaemon
    from loom.preparation import CoordinatorPreparation
    from loom.queue._run_queries import search

    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        uris = []
        for operation_id, reason in (
            ("first", "initial reason"),
            ("second", "later reason"),
        ):
            request = _reconciled_request(operation_id)
            request = replace(
                request,
                preparation=replace(
                    request.preparation, context=SubmissionContext(reason)
                ),
            )
            daemon.start_run(request, principal_id="caller")
            operation: Any = daemon.wait_operation(operation_id, timeout=90).operation
            assert operation.state == "applied", operation
            uris.append(operation.result["prepared_run"]["run_uri"])
            daemon._wait(operation.result["queue_item_id"], timeout_seconds=60)
        assert uris[0] == uris[1]
        submissions = search(daemon, SubmissionQuery().checked())
        assert {item["native"]["operation_id"] for item in submissions.items} == {
            "first",
            "second",
        }
        assert {item["native"]["run_uri"] for item in submissions.items} == {uris[0]}
        assert {
            item["sources"]["submission.context"]["description"]
            for item in submissions.items
        } == {"initial reason", "later reason"}
        original = search(
            daemon,
            RunQuery(
                where=ContainsText(
                    Field("submission.context", ("description",)), "initial reason"
                ),
                order_by=(Order("submitted_at", True),),
            ).checked(),
        )
        assert [item["identity"] for item in original.items] == [uris[0]]
        later = search(
            daemon,
            RunQuery(
                where=ContainsText(
                    Field("submission.context", ("description",)), "later reason"
                )
            ).checked(),
        )
        assert later.items == ()
    finally:
        daemon.stop()
