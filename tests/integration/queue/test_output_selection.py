"""Native Unix, HTTPS, QUERY, and CLI output selection share authority facts."""

from dataclasses import replace
import json
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.runs import CollectionScope, OutputLocator, OutputSelection, RunQuery, Compare, Field

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("https", [False, True])
def test_warning_heavy_output_pages_retain_every_selector(tmp_path, https, monkeypatch):
    from tests.integration.mcp.test_stdio import _coordinator
    from loom.queue._coordinator_control import MAX_RESPONSE_BYTES, encode_wire

    def unavailable(_):
        raise OSError("authority offline")

    with _coordinator(tmp_path, https=https) as (service, daemon, _):
        # A valid deep collection path amplifies each per-selector warning.
        root = tmp_path.joinpath(*("r" * 200 for _ in range(17)))
        uri = (root / "producer").as_uri()
        monkeypatch.setattr(
            daemon,
            "config",
            replace(
                daemon.config,
                run_store_root=root,
                coordinator_authority_factory=unavailable,
            ),
        )
        client = (
            CoordinatorClient.from_connection_file(tmp_path / "client.json")
            if https
            else CoordinatorClient.from_unix_socket(service.daemon.endpoint)
        )
        stages = tuple(f"stage-{index:03}" for index in range(200))
        with client:
            for operation in (client.select_outputs, client.list_output_commits):
                selection = OutputSelection(
                    run_uris=(uri,), stage_names=stages, scope=CollectionScope(), limit=200
                )
                outcomes = []
                cursors = set()
                while True:
                    page = operation(selection)
                    assert len(encode_wire({"ok": True, "result": page.to_dict()})) <= MAX_RESPONSE_BYTES
                    assert page.items and not page.complete
                    assert all(row["outcome"] == "authority_unavailable" for row in page.items)
                    assert all(row["matched_run_uri"] == uri for row in page.items)
                    assert page.warnings
                    assert all(warning == {"code": "authority_unavailable", "run_uri": uri} for warning in page.warnings)
                    outcomes.extend(row["matched_stage_name"] for row in page.items)
                    if page.next_cursor is None:
                        break
                    assert page.next_cursor not in cursors
                    cursors.add(page.next_cursor)
                    selection = replace(selection, cursor=page.next_cursor)
                assert cursors
                assert outcomes == list(stages)


@pytest.mark.parametrize("https", [False, True])
def test_native_output_routes_and_adapters(tmp_path, https, capsys, monkeypatch):
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.queue.test_preparation_operations import _request
    from loom.cli.main import main

    with _coordinator(tmp_path, https=https) as (service, daemon, _):
        connection = (
            ["--connection", str(tmp_path / "client.json")]
            if https
            else ["--endpoint", str(service.daemon.endpoint)]
        )
        client = (
            CoordinatorClient.from_connection_file(tmp_path / "client.json")
            if https
            else CoordinatorClient.from_unix_socket(service.daemon.endpoint)
        )
        with client:
            assert "output-query-v1" in client.describe_connection().capabilities
            request = RunRequest(_request(), "output-run")
            client.start_run(request)
            operation = daemon.wait_operation(
                request.preparation.operation_id, timeout=90
            ).operation
            assert operation.state == "applied", operation
            uri = cast(Any, operation.result)["prepared_run"]["run_uri"]
            daemon._wait("output-run", timeout_seconds=60)
            selection = OutputSelection(run_uris=(uri,))
            page = client.select_outputs(selection)
            assert page.complete and page.items
            item = page.items[0]
            assert item["outcome"] == "selected"
            assert item["locator"]["run_uri"] == uri
            assert item["availability"] == "not_checked"
            locator = OutputLocator.from_dict(item["locator"])
            exact = client.select_outputs(OutputSelection(locator=locator))
            assert exact.items[0]["artifact"] == item["artifact"]
            history = client.list_output_commits(selection)
            assert history.items[0]["commit"]["commit_id"] == locator.commit_id
            assert history.items[0]["outputs"][0]["artifact"] == item["artifact"]
            query = OutputSelection(
                query=RunQuery(where=Compare(Field("native", ("run_uri",)), "eq", uri))
            )
            assert client.select_outputs(query).items[0]["locator"] == item["locator"]
            empty = client.select_outputs(
                OutputSelection(
                    query=RunQuery(
                        where=Compare(
                            Field("native", ("run_uri",)), "eq", "file:///missing"
                        )
                    )
                )
            )
            assert empty.items == () and empty.complete
            explicit = client.select_outputs(
                OutputSelection(run_uris=("file:///missing",))
            )
            assert explicit.items[0]["outcome"] == "run_not_found"
            assert (
                main(
                    [
                        "runs",
                        "outputs",
                        "--run-uri",
                        uri,
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            cli = json.loads(capsys.readouterr().out)
            assert cli["result"]["items"][0]["locator"] == item["locator"]
            with pytest.raises(CoordinatorClientError) as wrong_owner:
                client.select_outputs(
                    selection, expected_coordinator_id="not-this-owner"
                )
            assert wrong_owner.value.code == "conflict"
            with pytest.raises(CoordinatorClientError) as invalid:
                client._native_call(
                    "select_outputs",
                    {
                        "selection": {
                            "locator": {**locator.to_dict(), "uri": "/etc/passwd"}
                        }
                    },
                    None,
                )
            assert invalid.value.code == "invalid_request"
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
                result = cast(Any, reader.select_outputs(selection))
                assert result["items"][0]["locator"] == item["locator"]
                assert (
                    cast(Any, reader.list_output_commits(selection))["items"][0][
                        "commit"
                    ]["commit_id"]
                    == locator.commit_id
                )
                filtered = cast(
                    Any,
                    reader.select_outputs(replace(selection, metadata={"ratio": 0.5})),
                )
                assert filtered["items"][0]["outcome"] == "no_matching_output"

            def unavailable(_):
                raise OSError("authority offline")

            monkeypatch.setattr(
                daemon,
                "config",
                replace(daemon.config, coordinator_authority_factory=unavailable),
            )
            failed = client.select_outputs(selection)
            assert failed.items[0]["outcome"] == "authority_unavailable"
            assert not failed.complete
