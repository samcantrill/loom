"""Actual Unix and authenticated HTTPS byte transfers without source mappings."""

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.contracts.test_artifact_access_contract import (
    SCOPE,
    local_ref,
    publish,
    shared_ref,
)
from tests.integration.mcp.test_stdio import _coordinator

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("https", [False, True])
def test_real_complete_tree_transport_and_cli_query_role(tmp_path, https, capsys, download_root):
    from loom.cli.main import main

    with _coordinator(tmp_path, https=https) as (service, daemon, _):
        uri = (daemon.config.run_store_root / "artifact-source").as_uri()
        authority = SQLitePerRunAuthorityStore(uri)
        authority.create_run(uri)
        daemon.config = replace(
            daemon.config, coordinator_authority_factory=lambda address: authority
        )
        ref, tree = shared_ref(daemon, uri)
        locator = publish(authority, uri, ref)
        client = (
            CoordinatorClient.from_connection_file(tmp_path / "client.json")
            if https
            else CoordinatorClient.from_unix_socket(service.daemon.endpoint)
        )
        connection = (
            ["--connection", str(tmp_path / "client.json")]
            if https
            else ["--endpoint", str(service.daemon.endpoint)]
        )
        with client:
            assert "artifact-read-v1" in client.describe_connection().capabilities
            description = client.describe_artifact(locator, scope=SCOPE)
            assert description["outcome"] == "available", description
            assert description["total_bytes"] > 256 * 1024
            result = client.fetch_artifacts(
                [{"locator": locator.to_dict()}], download_root / "destination", scope=SCOPE
            )
            assert result["success_count"] == 1, result
            destination = Path(result["items"][0]["local_path"])
            for member in description["members"]:
                assert (destination / member["path"]).read_bytes() == (
                    tree / member["path"]
                ).read_bytes()
            assert (
                main(
                    [
                        "artifacts",
                        "describe",
                        "--request",
                        json.dumps({"locator": locator.to_dict(), "scope": SCOPE}),
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert (
                json.loads(capsys.readouterr().out)["result"]["declaration"]
                == description["declaration"]
            )
            chunk_args: dict[str, Any] = dict(
                scope=SCOPE,
                declaration=description["declaration"],
                member=description["primary"],
                offset=0,
                length=256 * 1024,
            )
            chunk = client.read_artifact_chunk(locator, **chunk_args)
            assert chunk == client.read_artifact_chunk(locator, **chunk_args)
            with pytest.raises(CoordinatorClientError) as wrong_owner:
                client.describe_artifact(
                    locator, scope=SCOPE, expected_coordinator_id="wrong"
                )
            assert wrong_owner.value.code == "conflict"
            with pytest.raises(CoordinatorClientError) as oversized:
                client.read_artifact_chunk(
                    locator, **{**chunk_args, "length": 256 * 1024 + 1}
                )
            assert oversized.value.code == "invalid_request"
            if https:
                from loom.queue.agent_session_transport import (
                    RunInspectionHttpClient,
                    RunInspectionTlsClientConfig,
                )

                url = json.loads((tmp_path / "client.json").read_text())["transport"][
                    "url"
                ]
                tls = tmp_path / "tls"
                query = RunInspectionHttpClient(
                    RunInspectionTlsClientConfig(
                        url, tls / "ca.crt", tls / "query.crt", tls / "query.key"
                    )
                )
                assert (
                    query.describe_artifact(locator, scope=SCOPE)["declaration"]
                    == description["declaration"]
                )
                assert (
                    query.read_artifact_chunk(locator, **chunk_args)["data"]
                    == chunk["data"]
                )
                assert query.read_artifact(
                    locator, scope=SCOPE, format="bytes", limit=10
                )["truncated"]
            local, _ = local_ref(uri)
            local_locator = publish(authority, uri, local, "local")
            assert client.read_artifact(local_locator, scope=SCOPE, format="json")[
                "content"
            ] == {"value": 1}
            assert (
                main(
                    [
                        "artifacts",
                        "read",
                        "--request",
                        json.dumps(
                            {
                                "locator": local_locator.to_dict(),
                                "scope": SCOPE,
                                "format": "json",
                            }
                        ),
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert json.loads(capsys.readouterr().out)["result"]["content"] == {
                "value": 1
            }
            assert (
                main(
                    [
                        "artifacts",
                        "fetch",
                        "--request",
                        json.dumps(
                            {
                                "selections": [{"locator": local_locator.to_dict()}],
                                    "destination": str(download_root / "cli-fetch"),
                                "scope": SCOPE,
                            }
                        ),
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert json.loads(capsys.readouterr().out)["result"]["success_count"] == 1


def test_https_transfer_reuses_authenticated_ranges_and_renegotiates_on_change(tmp_path, download_root, monkeypatch):
    from loom._artifact_ranges import CHUNK_BYTES, RANGE_WINDOW
    from loom.queue import agent_session_transport as transport
    from loom.queue._coordinator_transport import HttpsControlTransport

    with _coordinator(tmp_path, https=True) as (_, daemon, _):
        uri = (daemon.config.run_store_root / "range-source").as_uri()
        authority = SQLitePerRunAuthorityStore(uri)
        authority.create_run(uri)
        daemon.config = replace(daemon.config, coordinator_authority_factory=lambda _: authority)
        ref, _ = local_ref(uri, b"r" * (12 * CHUNK_BYTES))
        locator = publish(authority, uri, ref)
        calls = []
        dispatch = transport._Handler._dispatch_post
        def count(handler):
            calls.append((handler.client_address, handler.path.rsplit("/", 1)[-1]))
            return dispatch(handler)
        monkeypatch.setattr(transport._Handler, "_dispatch_post", count)
        with CoordinatorClient.from_connection_file(tmp_path / "client.json") as client:
            result = client.fetch_artifacts([{"locator": locator.to_dict()}], download_root / "ranges", scope=SCOPE)
            assert result["success_count"] == 1, result
            ports = {peer for peer, name in calls if name == "read_artifact_chunk"}
            assert 1 <= len(ports) <= RANGE_WINDOW
            assert sum(name == "read_artifact_chunk" for _, name in calls) == 12
            for peer in ports:
                requests = [name for origin, name in calls if origin == peer]
                assert requests[0] == "handshake" and requests.count("handshake") == 1

            tls = client._transport
            assert isinstance(tls, HttpsControlTransport)
            declaration = result["items"][0]["declaration"]
            assert isinstance(declaration, str)

            def read_first_chunk():
                return client.read_artifact_chunk(
                    locator, scope=SCOPE, declaration=declaration, member="result.json",
                    offset=0, length=1, expected_coordinator_id=daemon._coordinator_id,
                )
            directory = tmp_path / "tls"
            with tls.range_reads():
                assert read_first_chunk()["outcome"] == "available"
                previous = calls[-1][0]
                for extension in ("crt", "key"):
                    (directory / ("other." + extension)).write_bytes((directory / ("query." + extension)).read_bytes())
                with pytest.raises(CoordinatorClientError):
                    read_first_chunk()
                assert calls[-1][1] == "handshake" and calls[-1][0] != previous


def test_https_peer_closing_after_negotiation_preserves_single_range_fallback(tmp_path, download_root, monkeypatch):
    from loom.queue import agent_session_transport as transport

    with _coordinator(tmp_path, https=True) as (_, daemon, _):
        uri = (daemon.config.run_store_root / "close-source").as_uri()
        authority = SQLitePerRunAuthorityStore(uri)
        authority.create_run(uri)
        daemon.config = replace(daemon.config, coordinator_authority_factory=lambda _: authority)
        ref, _ = local_ref(uri)
        locator = publish(authority, uri, ref)
        headers = transport._Handler.end_headers
        def close_handshake(handler):
            if handler.path.endswith("/handshake"):
                handler.send_header("Connection", "close")
                handler.close_connection = True
            return headers(handler)
        monkeypatch.setattr(transport._Handler, "end_headers", close_handshake)
        with CoordinatorClient.from_connection_file(tmp_path / "client.json") as client:
            result = client.fetch_artifacts([{"locator": locator.to_dict()}], download_root / "fetch", scope=SCOPE)
            assert result["success_count"] == 1, result
