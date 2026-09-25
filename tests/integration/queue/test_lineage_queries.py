"""Exact multi-run traversal and native adapter equivalence."""

from dataclasses import replace
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.input_lineage import AttemptInputBinding
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue._lineage import lineage_operation
from loom.runs import CollectionScope, LineageQuery, OutputLocator
from loom.runs.query import InvalidCursorError
from tests.contracts.test_attempt_input_lineage_contract import prepare
from tests.integration.authority.test_action_result_binding import _consumer, _producer

pytestmark = pytest.mark.integration


def graph(tmp_path):
    root = tmp_path / "runs"
    producer, adopted = _producer(root)
    uri, consumer, _, _ = _consumer(root, "embedded")
    assert isinstance(consumer, SQLitePerRunAuthorityStore)
    consumer.bind_action_result(uri, "reused", adopted)
    LocalRunStore(root).ensure_run(uri)
    LocalRunStore(root).ensure_run(adopted.commit.run_uri)
    locator = OutputLocator(
        adopted.commit.run_uri, "original", adopted.commit.commit_id, "out"
    )
    first = AttemptInputBinding(
        "data", "reused", "out", adopted.artifact_facts[0].artifact, locator, "produced"
    )
    outputs = []
    for stage, bindings, upstream in (
        ("transform", (first,), {"reused": locator.commit_id}),
        ("branch", (first,), {"reused": locator.commit_id}),
    ):
        receipt = prepare(
            consumer, uri, stage=stage, bindings=bindings, upstream=upstream
        )
        consumer.bind_prepared_attempt(
            uri, assignment_id=stage, attempt_id=receipt.attempt.attempt_id
        )
        fence = consumer.grant_prepared_attempt(
            uri, assignment_id=stage, attempt_id=receipt.attempt.attempt_id
        )
        consumer.confirm_execution_started(uri, fence=fence)
        outputs.append(
            consumer.record_output_commit(
                uri,
                stage,
                attempt_id=fence.attempt_id,
                assignment_id=stage,
                fencing_token=fence.fencing_token,
                outputs={
                    "out": ArtifactRef(
                        artifact_id=stage,
                        uri="s3://external/" + stage,
                        artifact_type="intermediate",
                    )
                },
            )
        )
    bindings = tuple(
        AttemptInputBinding(
            str(i),
            output.commit.stage_name,
            "out",
            output.artifact_facts[0].artifact,
            OutputLocator(
                uri, output.commit.stage_name, output.commit.commit_id, "out"
            ),
            "produced",
        )
        for i, output in enumerate(outputs)
    )
    receipt = prepare(
        consumer,
        uri,
        stage="summary",
        bindings=bindings,
        upstream={
            output.commit.stage_name: output.commit.commit_id for output in outputs
        },
    )
    consumer.bind_prepared_attempt(
        uri, assignment_id="summary", attempt_id=receipt.attempt.attempt_id
    )
    fence = consumer.grant_prepared_attempt(
        uri, assignment_id="summary", attempt_id=receipt.attempt.attempt_id
    )
    consumer.confirm_execution_started(uri, fence=fence)
    consumer.record_output_commit(
        uri,
        "summary",
        attempt_id=fence.attempt_id,
        assignment_id="summary",
        fencing_token=fence.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="summary",
                uri="s3://external/summary",
                artifact_type="summary",
            )
        },
    )
    unrelated = (root / "unrelated").as_uri()
    LocalRunStore(root).ensure_run(unrelated)
    other = SQLitePerRunAuthorityStore(unrelated)
    other.create_run(unrelated)
    independent = other.allocate_stage_attempt(unrelated, "independent", owner_id="worker", lease_ttl_seconds=60)
    assert independent.lease is not None
    other.record_output_commit(unrelated, "independent", attempt_id=independent.attempt.attempt_id,
                               fencing_token=independent.lease.fencing_token,
                               outputs={"out": adopted.artifact_facts[0].artifact})
    daemon = SimpleNamespace(
        config=SimpleNamespace(
            run_store_root=root,
            coordinator_authority_factory=SQLitePerRunAuthorityStore,
        ),
        _require_started=lambda: "coordinator",
    )
    return daemon, producer, consumer, uri, locator


def test_multihop_fanin_fanout_history_filter_paging_and_limits(tmp_path):
    daemon, producer, _, uri, locator = graph(tmp_path)
    query = LineageQuery(
        start=locator.to_dict(),
        direction="downstream",
        scope=CollectionScope(),
        artifact_type="summary",
    ).checked()
    page = lineage_operation(daemon, query)
    output_nodes = [v for v in page.items if v.get("entity") == "output"]
    assert {v["identity"]["stage_name"] for v in output_nodes} == {
        "original",
        "transform",
        "branch",
        "summary",
    }
    assert {v["identity"]["stage_name"] for v in output_nodes if v["selected"]} == {
        "summary"
    }
    assert len([v for v in page.items if v.get("relation") == "consumed_input"]) == 4
    assert any(v.get("relation") == "reused_output" for v in page.items)
    assert all(
        v.get("identity", {}).get("run_uri", uri).split("/")[-1] != "unrelated"
        for v in page.items
    )
    rows, cursors = [], set()
    small = replace(query, limit=2)
    while True:
        part = lineage_operation(daemon, small)
        rows.extend(part.items)
        if part.next_cursor is None:
            break
        assert part.next_cursor not in cursors
        cursors.add(part.next_cursor)
        small = replace(small, cursor=part.next_cursor)
    assert rows == list(page.items)
    with pytest.raises(InvalidCursorError):
        lineage_operation(daemon, replace(small, direction="upstream"))
    shallow = lineage_operation(daemon, replace(query, max_depth=0))
    assert not shallow.complete and any(
        w["code"] == "depth_limit" for w in shallow.warnings
    )
    from loom.pipeline.status import StageStatus
    from loom.pipeline.transition_policy import TransitionIntent
    producer.transition_stage(locator.run_uri, "original", from_status=StageStatus.SUCCEEDED,
                              to_status=StageStatus.STALE, intent=TransitionIntent.RESUME)
    successor = producer.allocate_stage_attempt(locator.run_uri, "original", owner_id="successor", lease_ttl_seconds=60)
    assert successor.lease is not None
    producer.record_output_commit(locator.run_uri, "original", attempt_id=successor.attempt.attempt_id,
                                  fencing_token=successor.lease.fencing_token,
                                  supersedes_commit_id=locator.commit_id,
                                  outputs={"out": ArtifactRef(artifact_id="successor", uri="s3://external/successor", artifact_type="json")})
    assert lineage_operation(daemon, query).items == page.items
    producer_query = replace(query, start={"run_uri": locator.run_uri, "stage_name": "original"}, direction="upstream")
    current = lineage_operation(daemon, producer_query)
    assert not any(v.get("identity") == locator.to_dict() for v in current.items)
    historical = lineage_operation(daemon, replace(producer_query, history="all"))
    assert any(v.get("identity") == locator.to_dict() for v in historical.items)
    summary = next(
        v["identity"] for v in output_nodes if v["identity"]["stage_name"] == "summary"
    )
    upstream = lineage_operation(
        daemon, replace(query, start=summary, direction="upstream")
    )
    assert any(v.get("identity") == locator.to_dict() for v in upstream.items)
    adopted = lineage_operation(daemon, replace(query, start={"run_uri": uri, "stage_name": "reused"}, direction="upstream"))
    assert any(v.get("relation") == "reused_output" for v in adopted.items)
    assert any(v.get("identity") == locator.to_dict() for v in adopted.items)


def test_bound_unknown_external_and_restricted_source_are_not_consumed(tmp_path):
    import sqlite3
    from loom.pipeline.status import StageStatus
    from loom.pipeline.stores.read_models import LifecycleReason

    daemon, _, consumer, uri, locator = graph(tmp_path)
    source = next(s for s in consumer.open_run(uri).stages if s.stage_name == "reused")
    binding = AttemptInputBinding(
        "data", "reused", "out", source.artifact_facts[0].artifact, locator, "produced"
    )
    receipt = prepare(
        consumer,
        uri,
        stage="unstarted",
        bindings=(binding,),
        upstream={"reused": locator.commit_id},
    )
    consumer.bind_prepared_attempt(
        uri, assignment_id="unstarted", attempt_id=receipt.attempt.attempt_id
    )
    fence = consumer.grant_prepared_attempt(
        uri, assignment_id="unstarted", attempt_id=receipt.attempt.attempt_id
    )
    consumer.record_managed_attempt_terminal(
        uri,
        fence=fence,
        status=StageStatus.CANCELLED,
        reason=LifecycleReason(code="test.cancelled"),
    )
    query = LineageQuery(
        start={
            "run_uri": uri,
            "stage_name": "unstarted",
            "attempt_id": receipt.attempt.attempt_id,
        },
        scope=CollectionScope(),
    ).checked()
    page = lineage_operation(daemon, query)
    edge = next(v for v in page.items if v.get("input_name") == "data")
    assert (
        edge["relation"] == "bound_input" and edge["start_evidence"] == "not_confirmed"
    )
    with sqlite3.connect(
        daemon.config.run_store_root / "consumer" / ".loom" / "authority.sqlite3"
    ) as conn:
        conn.execute(
            "UPDATE attempts SET start_confirmed=NULL WHERE attempt_id=?",
            (receipt.attempt.attempt_id,),
        )
    unknown = lineage_operation(daemon, query)
    assert not unknown.complete
    assert (
        next(v for v in unknown.items if v.get("input_name") == "data")[
            "start_evidence"
        ]
        == "unknown"
    )
    assert any(w["code"] == "start_evidence_unknown" for w in unknown.warnings)
    external = replace(binding, producer=None, source_kind="external")
    external_attempt = prepare(consumer, uri, stage="external", bindings=(external,))
    external_page = lineage_operation(
        daemon,
        replace(
            query,
            start={
                "run_uri": uri,
                "stage_name": "external",
                "attempt_id": external_attempt.attempt.attempt_id,
            },
        ),
    )
    assert any(v.get("entity") == "external" for v in external_page.items)
    assert any(w["code"] == "external_boundary" for w in external_page.warnings)
    # Restrict the readable collection to the consumer's parent after moving
    # the source outside the scope is unnecessary: managed membership can
    # independently exclude the producer while retaining the consumer.
    from contextlib import contextmanager

    @contextmanager
    def connection():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE preparation_operations(operation_id, principal_id, accepted_at, state, kind, queue_item_id, result_json)"
        )
        conn.execute("CREATE TABLE managed_admissions(run_uri)")
        conn.execute("INSERT INTO managed_admissions VALUES (?)", (uri,))
        try:
            yield conn
        finally:
            conn.close()

    daemon._connection = connection
    restricted = lineage_operation(daemon, replace(query, scope={"kind": "managed"}))
    assert not restricted.complete and any(
        w["code"] == "restricted_source" for w in restricted.warnings
    )
    assert locator.run_uri not in json.dumps(restricted.to_dict())
    restricted_adoption = lineage_operation(daemon, replace(query, start={"run_uri": uri, "stage_name": "reused"}, scope={"kind": "managed"}))
    assert not restricted_adoption.complete
    assert any(w["code"] == "restricted_source" for w in restricted_adoption.warnings)
    assert locator.run_uri not in json.dumps(restricted_adoption.to_dict())


def test_control_only_dependency_does_not_create_consumed_edge(tmp_path):
    daemon, _, consumer, uri, locator = graph(tmp_path)
    receipt = prepare(consumer, uri, stage="control_only", bindings=(), upstream={"reused": locator.commit_id})
    consumer.bind_prepared_attempt(uri, assignment_id="control", attempt_id=receipt.attempt.attempt_id)
    fence = consumer.grant_prepared_attempt(uri, assignment_id="control", attempt_id=receipt.attempt.attempt_id)
    consumer.confirm_execution_started(uri, fence=fence)
    page = lineage_operation(daemon, LineageQuery(start={"run_uri": uri, "stage_name": "control_only", "attempt_id": receipt.attempt.attempt_id}, scope=CollectionScope()).checked())
    assert page.complete
    assert len(page.items) == 1 and page.items[0]["entity"] == "attempt"


@pytest.mark.optional_dependency
@pytest.mark.parametrize("https", [False, True])
def test_native_lineage_python_cli_and_query_role(tmp_path, https, capsys):
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.queue.test_preparation_operations import _request
    from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
    from loom.cli.main import main

    with _coordinator(tmp_path, https=https) as (service, daemon, _):
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
            assert "lineage-query-v1" in client.describe_connection().capabilities
            request = RunRequest(_request(), "lineage-run")
            client.start_run(request)
            operation = daemon.wait_operation(
                request.preparation.operation_id, timeout=90
            ).operation
            assert operation.state == "applied"
            uri = cast(Any, operation.result)["prepared_run"]["run_uri"]
            daemon._wait("lineage-run", timeout_seconds=60)
            query = LineageQuery(start={"run_uri": uri})
            page = client.trace_lineage(query)
            assert page.items
            assert (
                main(
                    [
                        "runs",
                        "lineage",
                        "--query",
                        json.dumps(query.to_dict()),
                        *connection,
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert json.loads(capsys.readouterr().out)["result"]["items"] == list(
                page.items
            )
            with pytest.raises(CoordinatorClientError) as error:
                client.trace_lineage(query, expected_coordinator_id="wrong")
            assert error.value.code == "conflict"
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
                assert reader.trace_lineage(query)["items"] == list(page.items)


def test_declared_unexecuted_graph_and_entity_budget(tmp_path, monkeypatch):
    from loom.pipeline import PipelineSpec
    from loom.pipeline.planning import plan_pipeline
    from loom.pipeline.stores import LocalArtifactStore
    from loom.pipeline.stores.read_models import StageLifecycleSnapshot
    from loom.pipeline.status import StageStatus
    from loom.queue import _lineage

    root = tmp_path / "runs"
    uri = (root / "declared").as_uri()
    local = LocalRunStore(root)
    local.create_run(uri)
    authority = SQLitePerRunAuthorityStore(uri)
    authority.create_run(uri)
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "source",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                },
                {
                    "name": "consumer",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "inputs": {"input": "source.data"},
                    "outputs": {"data": {"artifact_type": "json"}},
                },
            ]
        }
    )
    plan_pipeline(
        spec,
        run_uri=uri,
        run_store=local,
        artifact_store=LocalArtifactStore(root / "artifacts"),
        persist=True,
    )
    daemon = SimpleNamespace(
        config=SimpleNamespace(
            run_store_root=root,
            coordinator_authority_factory=SQLitePerRunAuthorityStore,
        ),
        _require_started=lambda: "coordinator",
    )
    query = LineageQuery(
        start={"run_uri": uri, "stage_name": "consumer"},
        relations=("declared_dependency",),
        scope=CollectionScope(),
    ).checked()
    page = lineage_operation(daemon, query)
    assert page.complete
    assert {v.get("relation") for v in page.items if v["kind"] == "edge"} == {
        "declared_dependency"
    }
    # A supported large authority snapshot exceeds the advertised acquisition
    # bound; no pagination token falsely promises progress beyond that bound.
    snapshot = authority.open_run(uri)
    large = replace(
        snapshot,
        stages=tuple(
            StageLifecycleSnapshot(f"s{i:04}", StageStatus.SKIPPED, snapshot.revision)
            for i in range(2001)
        ),
    )
    fake = SimpleNamespace(
        open_run=lambda _: large, list_output_commits=lambda *a, **k: ()
    )
    monkeypatch.setattr(_lineage, "_authority", lambda *a: fake)
    limited = lineage_operation(
        daemon, replace(query, start={"run_uri": uri}, relations=("consumed_input",))
    )
    assert not limited.complete and limited.next_cursor is None
    assert any(w["code"] == "traversal_limit" for w in limited.warnings)
