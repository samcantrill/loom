"""Two caller vocabularies compose discovery, lineage, retrieval and annotation."""

from dataclasses import replace
from typing import Any

import pytest

from loom.artifacts import ArtifactRef
from loom.coordinator import CoordinatorClient, RunRequest
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.input_lineage import AttemptInputBinding
from loom.pipeline.stores.read_models import ActionResultBinding
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.runs import (
    CollectionScope,
    Compare,
    Field,
    LineageQuery,
    OutputLocator,
    OutputSelection,
    RunQuery,
    SubmissionContext,
)
from tests.contracts.test_artifact_access_contract import local_ref
from tests.contracts.test_attempt_input_lineage_contract import prepare
from tests.integration.mcp.test_stdio import _coordinator
from tests.integration.queue.test_preparation_operations import _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def collect(method, query):
    items, warnings = [], []
    while True:
        page = method(query)
        items.extend(page.items)
        warnings.extend(page.warnings)
        if page.next_cursor is None:
            return items, warnings
        query = replace(query, cursor=page.next_cursor)


@pytest.mark.parametrize(
    "tag,value,kind",
    [
        ("study", "kernel", "summary_manifest"),
        ("customer", "example-company", "invoice_report"),
    ],
)
def test_composed_workflow_preserves_source_targets_and_partial_results(
    tmp_path, tag, value, kind
):
    with _coordinator(tmp_path) as (service, daemon, _):
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            request = RunRequest(
                replace(
                    _request(),
                    context=SubmissionContext("caller motivation", {tag: value}),
                ),
                "source",
            )
            client.start_run(request)
            operation: Any = daemon.wait_operation(
                request.preparation.operation_id, timeout=90
            ).operation
            assert operation.state == "applied", operation
            source = operation.result["prepared_run"]["run_uri"]
            daemon._wait("source", timeout_seconds=60)
            selected = client.select_outputs(OutputSelection(run_uris=(source,))).items[
                0
            ]
            source_locator = OutputLocator.from_dict(selected["locator"])
            consumer_uri = (daemon.config.run_store_root / "consumer").as_uri()
            LocalRunStore(daemon.config.run_store_root).ensure_run(consumer_uri)
            authority = SQLitePerRunAuthorityStore(consumer_uri)
            authority.create_run(consumer_uri)
            from loom.queue._output_selection import _authority

            original = _authority(daemon, source).list_output_commits(
                source, stage_name=source_locator.stage_name
            )[0]
            authority.bind_action_result(
                consumer_uri,
                source_locator.stage_name,
                ActionResultBinding(
                    claim_id="qualified-source",
                    execution_key="sha256:" + "a" * 64,
                    commit=original.commit,
                    artifact_facts=original.artifact_facts,
                    verification={
                        "schema_version": 1,
                        "candidate_digest": "sha256:" + "b" * 64,
                        "verdict": "verified",
                    },
                ),
            )
            previous_ref = ArtifactRef.from_dict(selected["artifact"])
            previous_locator = source_locator
            for stage in ("transform", "report"):
                binding = AttemptInputBinding(
                    "data",
                    previous_locator.stage_name,
                    previous_locator.output_name,
                    previous_ref,
                    previous_locator,
                    "produced",
                )
                receipt = prepare(
                    authority, consumer_uri, stage=stage, bindings=(binding,)
                )
                authority.bind_prepared_attempt(
                    consumer_uri,
                    assignment_id=stage,
                    attempt_id=receipt.attempt.attempt_id,
                )
                fence = authority.grant_prepared_attempt(
                    consumer_uri,
                    assignment_id=stage,
                    attempt_id=receipt.attempt.attempt_id,
                )
                authority.confirm_execution_started(consumer_uri, fence=fence)
                ref, _ = local_ref(consumer_uri, name=stage + ".json")
                ref = replace(
                    ref, artifact_type=kind if stage == "report" else "intermediate"
                )
                outputs = {"out": ref}
                if stage == "report":
                    outputs["remote"] = ArtifactRef(
                        "remote", "s3://unsupported/report", kind
                    )
                commit = authority.record_output_commit(
                    consumer_uri,
                    stage,
                    attempt_id=fence.attempt_id,
                    assignment_id=stage,
                    fencing_token=fence.fencing_token,
                    outputs=outputs,
                )
                previous_ref = ref
                previous_locator = OutputLocator(
                    consumer_uri, stage, commit.commit.commit_id, "out"
                )
            runs, warnings = collect(
                client.search_runs,
                RunQuery(where=Compare(Field("tags", (tag,)), "eq", value), limit=1),
            )
            assert [r["identity"] for r in runs] == [source]
            assert (
                runs[0]["sources"]["submission.context"]["description"]
                == "caller motivation"
            )
            graph, graph_warnings = collect(
                client.trace_lineage,
                LineageQuery(
                    start=source_locator.to_dict(),
                    direction="downstream",
                    scope=CollectionScope(),
                    artifact_type=kind,
                    limit=2,
                ),
            )
            warnings.extend(graph_warnings)
            report_uris = {
                row["identity"]["run_uri"]
                for row in graph
                if row.get("entity") == "output" and row.get("selected")
            }
            assert report_uris == {consumer_uri}
            outputs, output_warnings = collect(
                client.select_outputs,
                OutputSelection(
                    run_uris=tuple(report_uris),
                    artifact_type=kind,
                    scope=CollectionScope(),
                    limit=1,
                ),
            )
            warnings.extend(output_warnings)
            assert len(outputs) == 4
            assert sum(row["outcome"] == "no_matching_output" for row in outputs) == 2
            preview = client.read_artifact(
                previous_locator, scope=CollectionScope(), format="json"
            )
            assert preview["content"] == {"value": 1}
            batch = client.fetch_artifacts(
                outputs, tmp_path / "retrieved", scope=CollectionScope()
            )
            assert (
                batch["complete"]
                and batch["success_count"] == 1
                and batch["failure_count"] == 3
            )
            assert {r["outcome"] for r in batch["items"]} == {
                "available",
                "unsupported_backend",
                "no_matching_output",
            }
            before = client.get_run_context(source).annotations
            assert before is not None and "review" not in before.tags
            # The caller explicitly chooses source runs, separately from fetch.
            approved_sources = {source}
            if batch["success_count"]:
                for uri in approved_sources:
                    client.patch_run_annotations(
                        uri,
                        mutation_id="review-ready",
                        expected_revision=before.revision,
                        set_tags={"review": "ready"},
                    )
            after = client.get_run_context(source).annotations
            assert after is not None and after.tags["review"] == "ready"
            assert consumer_uri not in approved_sources
            assert isinstance(warnings, list)
