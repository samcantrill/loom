"""Discovery crosses real Unix/HTTPS authorization and owning metadata readers."""

from dataclasses import replace
import json
from operator import itemgetter
import sqlite3
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
    collect_pages,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize(
    "store, axes, diagnostic",
    [
        (
            "execution_database",
            {"scheduling", "assignment", "slurm"},
            "execution_store_unavailable",
        ),
        ("agent_journal", {"execution"}, "agent_journal_unavailable"),
    ],
)
def test_job_query_retains_unavailable_owner_coverage(
    tmp_path, monkeypatch, store, axes, diagnostic
):
    from tests.integration.mcp.test_stdio import _coordinator
    from tests.integration.queue.test_preparation_operations import _request

    with _coordinator(tmp_path) as (service, daemon, _):
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            request = RunRequest(_request(), "owner-coverage")
            client.start_run(request)
            operation = daemon.wait_operation(
                request.preparation.operation_id, timeout=90
            ).operation
            assert operation.state == "applied", operation
            daemon._wait("owner-coverage", timeout_seconds=60)
            query = JobQuery()
            healthy = client.search_jobs(query)
            assert healthy.items
            assert healthy.complete and not healthy.warnings
            admission_ids = {item["identity"] for item in healthy.items}
            corrupt = tmp_path / "corrupt-owner.sqlite"
            corrupt.write_bytes(b"not a sqlite database")
            with monkeypatch.context() as patch:
                patch.setattr(type(daemon.config), store, property(lambda self: corrupt))
                assert client.search_runs(RunQuery()).complete
                collection = collect_pages(
                    lambda q: client.search_jobs(cast(JobQuery, q)), query
                )
            page = collection.pages[0]
            assert page.next_cursor is None
            assert not page.complete and not collection.complete
            assert collection.warnings == page.warnings
            assert {warning["admission_id"] for warning in page.warnings} == admission_ids
            assert {warning["axis"] for warning in page.warnings} == axes | {"service"}
            for warning in page.warnings:
                assert warning == {
                    "code": "job_associations_unavailable",
                    "admission_id": warning["admission_id"],
                    "axis": warning["axis"],
                    "diagnostic": (
                        "owner_status_unavailable"
                        if warning["axis"] == "service"
                        else diagnostic
                    ),
                }
            owners = page.items[0]["sources"]["job_associations"]
            assert owners["authority"]["availability"] == "available"
            for axis in axes:
                assert owners[axis]["availability"] == "unavailable"
                assert owners[axis]["diagnostic"] == diagnostic
            if store == "execution_database":
                assert owners["assignment"]["assignments"] == []


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
            job = jobs.items[0]
            assert "admitted_by" not in job["native"]
            owners = job["sources"]["job_associations"]
            exact = cast(Any, client.admission(job["identity"]).to_dict()["owners"])
            assert set(owners) == set(exact)
            for supplemental in ("scheduling_waits", "input_validation", "slurm_storage", "agent_sessions"):
                assert owners[supplemental] == exact[supplemental]
            assert owners["admission"]["revision"] == exact["admission"]["revision"]
            assert owners["authority"]["revision"] == job["observation"]["revision"]
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
            assert "pipeline_fingerprint" not in fields["native_fields"]
            timing = client.search_runs(
                RunQuery(
                    where=Compare(Field("native", ("run_uri",)), "eq", uri),
                    select=(
                        Field("native", ("started_at",)),
                        Field("native", ("finished_at",)),
                    ),
                )
            )
            assert len(timing.items) == 1
            assert timing.items[0]["native"]["started_at"]
            assert timing.items[0]["native"]["finished_at"]
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
            known = {item['identity'] for item in collect_pages(client.search_runs, RunQuery()).items}
            for ordering in ((Order('created_at'),), (Order('created_at', True), Order('submitted_at'))):
                indexed = collect_pages(client.search_runs, RunQuery(order_by=ordering, limit=1))
                assert {item['identity'] for item in indexed.items} == known
                assert len(indexed.items) == len(known)
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


def _insert_terminal_job(daemon, conn, index, run_uri):
    identity = f"job-{index}"
    conn.execute(
        "INSERT INTO managed_admissions "
        "(admission_id,queue_item_id,coordinator_id,run_uri,intent_digest,execution_owner,"
        "state,accepted_at,authority_operation_id,revision,run_priority,enqueue_sequence) "
        "VALUES (?, ?, ?, ?, 'digest', 'managed-stage', 'SUCCEEDED', ?, ?, ?, 0, ?)",
        (identity, identity, daemon._require_started(), run_uri, "2026-01-01T00:00:00Z",
         f"bind-{index}", index + 1, index + 1),
    )


def _insert_corrupt_stage(daemon, job_id, run_uri, payload=b'{}'):
    with sqlite3.connect(daemon.config.execution_database) as conn:
        conn.execute(
            "INSERT INTO stage_work (stage_work_id,admission_id,run_uri,stage_name,attempt_id,"
            "readiness_generation,run_priority,enqueue_sequence,ready_at,ready_order,attempt,"
            "scheduling_state,record_json) VALUES ('w',?,?,'stage','a','g',0,1,1,1,1,'settled',CAST(? AS TEXT))",
            (job_id, run_uri, payload),
        )


def _seed_assignment_jobs(daemon, count):
    from loom.pipeline.status import RunStatus
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from tests.integration.queue.test_local_daemon_production import _persist_sleep_run

    config = daemon.config
    jobs = {}
    assignments = []
    for index in range(count):
        job_id = f"job-{index}"
        uri = _persist_sleep_run(config.run_store_root, run_name=job_id, stage_name="stage")
        SQLitePerRunAuthorityStore(uri).transition_run(
            uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED,
        )
        jobs[job_id] = uri
        identity = {
            "assignment_id": f"assignment-{index}", "run_uri": uri,
            "stage_work_id": f"work-{index}", "stage_name": "stage", "attempt": 1,
            "attempt_id": f"attempt-{index}", "agent_id": daemon._agent_id,
            "session_id": "session", "offer_id": f"offer-{index}", "claim_id": f"claim-{index}",
        }
        assignments.append({**identity, "identity_json": json.dumps(identity)})

    with sqlite3.connect(config.execution_database) as conn:
        conn.executemany(
            "INSERT INTO coordinator_assignments "
            "(assignment_id,identity_json,run_uri,stage_work_id,state,receipt_json,"
            "agent_id,session_id,offer_id,claim_id) VALUES "
            "(:assignment_id,:identity_json,:run_uri,:stage_work_id,'released','{}',"
            ":agent_id,:session_id,:offer_id,:claim_id)", assignments,
        )
    with sqlite3.connect(config.agent_journal) as conn:
        conn.executemany(
            "INSERT INTO assignments (assignment_id,identity_json,request_json,state) "
            "VALUES (:assignment_id,:identity_json,'{}','released')", assignments,
        )
    if count > 1:
        daemon._execution.coordinator.record_event(
            "assignment-1", 1, "assignment-1:definitive_decline",
            {"kind": "definitive_decline", "reason_code": "device_missing"},
        )
    with daemon._connection() as conn:
        for index, uri in enumerate(jobs.values()):
            _insert_terminal_job(daemon, conn, index, uri)
        conn.commit()
    return jobs


def _trace_search_journals(monkeypatch, config):
    from threading import current_thread

    connect = sqlite3.connect
    paths = {}
    traces = {}
    for path in (config.execution_database, config.agent_journal):
        traces[path] = []
        paths[str(path)] = paths[path.resolve().as_uri()] = path

    def traced_connect(database, *args, **kwargs):
        path = paths.get(str(database).partition("?")[0])
        if path is None or current_thread().name != "loom-job-read":
            return connect(database, *args, **kwargs)
        statements = []
        # Count an attempted open even when the configured journal is missing.
        traces[path].append(statements)
        conn = connect(database, *args, **kwargs)

        def observe(sql):
            statements.append((" ".join(sql.lower().split()), conn.in_transaction))

        conn.set_trace_callback(observe)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    return traces


@pytest.mark.parametrize(
    "count,fault",
    [(1, None), (16, None), (16, "missing-agent"), (16, "corrupt-stage"), (16, "invalid-utf8")],
)
def test_job_search_reads_shared_journals_once(tmp_path, monkeypatch, count, fault):
    from tests.integration.mcp.test_stdio import _coordinator

    with _coordinator(tmp_path) as (service, daemon, _):
        config = daemon.config
        jobs = _seed_assignment_jobs(daemon, count)
        if fault == "missing-agent":
            monkeypatch.setattr(type(config), "agent_journal", property(lambda _: tmp_path / "missing.sqlite"))
        corrupt_stage = fault in ("corrupt-stage", "invalid-utf8")
        if corrupt_stage:
            # Invalid UTF-8 fails inside the SQLite driver before it yields the
            # row's indexed run URI. A malformed stage object yields that URI.
            payload = bytes.fromhex("ff") if fault == "invalid-utf8" else b"{}"
            _insert_corrupt_stage(daemon, "job-15", jobs["job-15"], payload)

        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            with monkeypatch.context() as patch:
                traces = _trace_search_journals(patch, config)
                page = client.search_jobs(JobQuery(limit=count))
            assert page.examined == count and page.next_cursor is None
            assert {item["identity"] for item in page.items} == jobs.keys()
            assert page.complete == (fault is None)
            warnings = []
            for row in page.items:
                job_id = row["identity"]
                owners = row["sources"]["job_associations"]
                exact = cast(Any, client.admission(job_id).to_dict()["owners"])
                assert owners["slurm_storage"] == exact["slurm_storage"] == {
                    "availability": "available", "assignments": [],
                }
                for axis in (
                    "assignment", "scheduling", "slurm", "execution", "service",
                    "authority", "admission",
                ):
                    assert owners[axis]["observed_at"]
                    assert {k: v for k, v in owners[axis].items() if k != "observed_at"} == {
                        k: v for k, v in exact[axis].items() if k != "observed_at"
                    }
                assignment_id = job_id.replace("job-", "assignment-")
                bad_row = corrupt_stage and job_id == "job-15"
                affected: dict[str, str] = {}
                if bad_row:
                    affected = dict.fromkeys(("scheduling", "slurm", "assignment"), "execution_store_unavailable")
                    assert owners["assignment"]["assignments"] == []
                else:
                    assignment, = owners["assignment"]["assignments"]
                    assert assignment["run_uri"] == jobs[job_id]
                    assert assignment["assignment_id"] == assignment_id
                    assert assignment["decline_reason_code"] == ("device_missing" if job_id == "job-1" else None)
                    assert owners["scheduling"]["state"] == owners["slurm"]["state"] == "empty"
                if fault == "missing-agent":
                    affected["execution"] = "agent_journal_unavailable"
                elif not bad_row:
                    entry, = owners["execution"]["journal"]
                    assert entry["assignment_id"] == assignment_id
                if affected:
                    affected["service"] = "owner_status_unavailable"
                for axis, diagnostic in affected.items():
                    assert owners[axis]["availability"] == "unavailable"
                    warnings.append({
                        "code": "job_associations_unavailable", "admission_id": job_id,
                        "axis": axis, "diagnostic": diagnostic,
                    })
            order = itemgetter("admission_id", "axis")
            assert sorted(page.warnings, key=order) == sorted(warnings, key=order)
            assert [len(calls) for calls in traces.values()] == [1, 1]
            for path, (statements,) in traces.items():
                if path == config.agent_journal and fault == "missing-agent":
                    assert statements == []
                    continue
                assert [sql for sql, _ in statements if sql.startswith("begin")] == ["begin"]
                selects = [(sql, active) for sql, active in statements if sql.startswith("select")]
                assert selects and all(active for _, active in selects)
                if path == config.execution_database:
                    events = [sql for sql, _ in selects if "coordinator_events" in sql]
                    assert events and all("coordinator_assignments" in sql for sql in events)
                    if fault != "invalid-utf8":
                        assert len(events) == 1
                else:
                    assert sum("from assignments " in sql for sql, _ in selects) == 1


@pytest.mark.parametrize("https", [False, True])
def test_job_page_bounds_stalled_read_and_resumes_after_last_examined(tmp_path, monkeypatch, https):
    from threading import Event
    from time import monotonic

    from loom.queue import _run_queries
    from tests.integration.mcp.test_stdio import _coordinator

    release = Event()
    with _coordinator(tmp_path, https=https) as (service, daemon, _):
        with daemon._connection() as conn:
            for index in range(7):
                _insert_terminal_job(daemon, conn, index, (tmp_path / f"job-{index}").as_uri())
            conn.commit()
        _insert_corrupt_stage(daemon, "job-6", (tmp_path / "job-6").as_uri())

        connection = (
            CoordinatorClient.from_connection_file(tmp_path / "client.json") if https
            else CoordinatorClient.from_unix_socket(service.daemon.endpoint)
        )
        with connection as client:
            exact = {row.admission_id: client.admission(row.admission_id)
                     for row in client.admissions().admissions}
            read = daemon._admission_detail

            def stall(admission, view):
                if admission.admission_id == "job-2":
                    assert release.wait(8), "observer waited for the stalled owner"
                return read(admission, view)

            monkeypatch.setattr(daemon, "_admission_detail", stall)
            monkeypatch.setattr(_run_queries, "_JOB_READ_SECONDS", 0.5)
            try:
                start = monotonic()
                query = JobQuery(limit=5)
                first = client.search_jobs(query)
                assert monotonic() - start < 4
                assert [row["identity"] for row in first.items] == ["job-0", "job-1"]
                assert not first.complete and first.examined == 2 and first.next_cursor
                assert {"code": "job_observation_deadline", "admission_id": "job-2"} in first.warnings
                with pytest.raises(CoordinatorClientError) as stalled:
                    client.search_jobs(replace(query, cursor=first.next_cursor))
                assert stalled.value.code == "job_observation_deadline"
                assert stalled.value.ids["admission_id"] == "job-2"
                if https:
                    from loom.queue.agent_session_transport import RunInspectionHttpClient, RunInspectionTlsClientConfig

                    address = json.loads((tmp_path / "client.json").read_text())["transport"]["url"]
                    tls = tmp_path / "tls"
                    reader = RunInspectionHttpClient(RunInspectionTlsClientConfig(
                        address, tls / "ca.crt", tls / "query.crt", tls / "query.key",
                    ))
                    assert reader.search_jobs(replace(query, cursor=first.next_cursor)) == {
                        "schema_version": 1, "code": "job_observation_deadline",
                    }

                empty = client.search_jobs(JobQuery(where=Compare(Field("tags", ("keep",)), "eq", "yes")))
                assert empty.items == () and empty.examined == 2 and empty.next_cursor
                assert not empty.complete and any(w["code"] == "job_observation_deadline" for w in empty.warnings)
            finally:
                release.set()
            rest = client.search_jobs(replace(query, cursor=first.next_cursor))
            assert rest.next_cursor is None
            rows = first.items + rest.items
            assert [row["identity"] for row in rows] == sorted(exact)
            assert rows[-1]["sources"]["job_associations"]["scheduling"]["availability"] == "unavailable"
            assert rows[2]["sources"]["job_associations"]["scheduling"]["availability"] == "available"
            for row in rows:
                owners = row["sources"]["job_associations"]
                reference = cast(Any, exact[row["identity"]].to_dict()["owners"])
                assert set(owners) == set(reference)
                for axis in ("authority", "scheduling", "assignment", "execution", "slurm", "admission"):
                    assert owners[axis]["state"] == reference[axis]["state"]
                    assert owners[axis].get("revision") == reference[axis].get("revision")


            if not https:
                # Two individually timely reads consume the whole observation budget.
                elapsed = [0.0]

                def measured_read(admission, view):
                    detail = read(admission, view)
                    elapsed[0] += 1.5
                    return detail

                monkeypatch.setattr(_run_queries, "monotonic", lambda: elapsed[0])
                monkeypatch.setattr(_run_queries, "_JOB_READ_SECONDS", 4.0)
                monkeypatch.setattr(_run_queries, "_JOB_PAGE_SECONDS", 3.0)
                monkeypatch.setattr(daemon, "_admission_detail", measured_read)
                # A page may preload shared rows for all seven candidates, but the
                # untouched suffix must not open any per-run authorities.
                factory = daemon.config.coordinator_authority_factory
                assert factory is not None
                opened = set()

                def observe_authority(uri):
                    opened.add(uri)
                    return factory(uri)

                monkeypatch.setattr(
                    daemon, "config",
                    replace(daemon.config, coordinator_authority_factory=observe_authority),
                )

                def measured_page(query):
                    opened.clear()
                    page = client.search_jobs(query)
                    assert opened == {item["native"]["run_uri"] for item in page.items}
                    return page

                result = collect_pages(measured_page, JobQuery(limit=7))
                assert [p.examined for p in result.pages] == [2, 2, 2, 1]
                assert [row["identity"] for row in result.items] == sorted(exact)


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
