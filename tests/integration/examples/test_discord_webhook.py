"""Integration coverage for the downstream Discord webhook event sink."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Mapping
from io import StringIO
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.event_sinks import EventSinkContext, EventSinkRegistry
from loom.pipeline.events import EventScope, PipelineEventRecord
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    LocalDaemonAdmissionState,
    LocalDaemonStatus,
)
from loom.serialization import PlainData
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "extensions" / "discord-webhook"
PACKAGE_SOURCE = EXAMPLE_ROOT / "src"
if str(PACKAGE_SOURCE) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SOURCE))

loom_discord = import_module("loom_discord")
sink_module = import_module("loom_discord.sink")
DiscordWebhookError = sink_module.DiscordWebhookError
DiscordWebhookSink = loom_discord.DiscordWebhookSink
DiscordCoordinatorReporter = loom_discord.DiscordCoordinatorReporter
TERMINAL_RUN_EVENT_TYPES = sink_module.TERMINAL_RUN_EVENT_TYPES
WEBHOOK_URL_ENVIRONMENT_VARIABLE = sink_module.WEBHOOK_URL_ENVIRONMENT_VARIABLE
discord_event_sink = loom_discord.discord_event_sink
cli_module = import_module("loom_discord.cli")


def test_metadata_factory_and_terminal_filter_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = tomllib.loads(
        (EXAMPLE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert metadata["project"]["name"] == "loom-discord"
    assert metadata["project"]["dependencies"] == ["httpx>=0.28,<1", "loom"]
    assert metadata["project"]["entry-points"]["loom.event_sinks"] == {
        "notifications.discord": "loom_discord:discord_event_sink"
    }
    assert metadata["project"]["scripts"] == {
        "loom-discord-coordinator": "loom_discord.cli:main"
    }

    monkeypatch.delenv(WEBHOOK_URL_ENVIRONMENT_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match=WEBHOOK_URL_ENVIRONMENT_VARIABLE):
        discord_event_sink()

    monkeypatch.setenv(
        WEBHOOK_URL_ENVIRONMENT_VARIABLE, "https://discord.invalid/webhook-token"
    )
    registration = discord_event_sink()
    assert isinstance(registration.sink, DiscordWebhookSink)
    assert registration.subscription is not None
    assert registration.subscription.event_types == TERMINAL_RUN_EVENT_TYPES

    registry = EventSinkRegistry()
    registry.register(
        "notifications.discord",
        registration.sink,
        subscription=registration.subscription,
    )
    event = _event(event_type="run.started")
    result = registry.dispatch(event, cast(EventSinkContext, object()))
    assert result.sink_results == ()


def test_sink_posts_bounded_safe_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(204)

    monkeypatch.setattr("loom_discord.sink.httpx.post", fake_post)
    sink = DiscordWebhookSink(
        "https://discord.invalid/webhook-token", timeout_seconds=3.5
    )
    event = _event(
        event_type="stage.completed",
        run_uri="run://" + "x" * 2_100,
        payload={"private": "payload-secret"},
    )

    sink(event, cast(EventSinkContext, object()))

    assert captured["url"] == "https://discord.invalid/webhook-token"
    assert captured["params"] == {"wait": "true"}
    assert captured["timeout"] == 3.5
    payload = cast(dict[str, object], captured["json"])
    assert payload["allowed_mentions"] == {"parse": []}
    content = cast(str, payload["content"])
    assert len(content) <= 2_000
    assert "Loom event: stage.completed" in content
    assert "Occurred: 2026-08-28T00:00:00Z" in content
    assert "Stage: publish" in content
    assert "payload-secret" not in content


@pytest.mark.parametrize(
    ("outcome", "expected_message"),
    [
        (httpx.Response(429), "Discord webhook rejected request with status 429"),
        (httpx.InvalidURL("secret-token"), "Discord webhook URL is invalid"),
        (
            httpx.ConnectTimeout(
                "secret-token",
                request=httpx.Request("POST", "https://discord.invalid/secret-token"),
            ),
            "Discord webhook transport failed",
        ),
    ],
)
def test_provider_failures_are_bounded_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    outcome: httpx.Response | Exception,
    expected_message: str,
) -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        _ = url, kwargs
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("loom_discord.sink.httpx.post", fake_post)

    with pytest.raises(DiscordWebhookError, match=expected_message) as exc_info:
        DiscordWebhookSink("https://discord.invalid/secret-token")(
            _event(event_type="run.completed"),
            cast(EventSinkContext, object()),
        )

    assert "secret-token" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_transport_failure_is_sanitized_and_does_not_change_run_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_url = "https://discord.invalid/webhooks/123/secret-token"
    monkeypatch.setenv(WEBHOOK_URL_ENVIRONMENT_VARIABLE, secret_url)

    def failing_post(url: str, **kwargs: object) -> httpx.Response:
        _ = kwargs
        raise httpx.ConnectError("request failed", request=httpx.Request("POST", url))

    monkeypatch.setattr("loom_discord.sink.httpx.post", failing_post)
    registration = discord_event_sink()
    registry = EventSinkRegistry()
    registry.register(
        "notifications.discord",
        registration.sink,
        subscription=registration.subscription,
    )
    store = create_authority_backed_serial_run_store(
        tmp_path / "runs", authority_store=SQLitePerRunAuthorityStore()
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "discord-failure")

    result = PipelineRunner(run_store=store).run(
        RunRequest(
            config=local_execution_config(),
            run_uri=run_uri,
            event_sink_registry=registry,
        )
    )

    assert result.status is RunStatus.SUCCEEDED
    failures = store.read_event_sink_failures(run_uri)
    assert len(failures) == 1
    failure = failures[0]
    assert failure.failure_type == DiscordWebhookError.__name__
    assert failure.failure_message == "Discord webhook transport failed"
    assert secret_url not in str(failure.to_dict())


def test_coordinator_reporter_projects_authority_progress_and_suppresses_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[dict[str, object]] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        assert url == "https://discord.invalid/webhook-token"
        messages.append(cast(dict[str, object], kwargs["json"]))
        return httpx.Response(204)

    monkeypatch.setattr("loom_discord.sink.httpx.post", fake_post)
    reporter = DiscordCoordinatorReporter("https://discord.invalid/webhook-token")
    first = _daemon_status()

    assert reporter.report(first, _daemon_details()) is True
    assert (
        reporter.report(_daemon_status(as_of="2026-08-28T00:01:00Z"), _daemon_details())
        is False
    )
    assert (
        reporter.report(
            _daemon_status(stage_state="SUCCEEDED"),
            _daemon_details(stage_state="SUCCEEDED"),
        )
        is True
    )
    assert (
        reporter.report(
            _daemon_status(stage_state="SUCCEEDED"),
            _daemon_details(stage_state="SUCCEEDED"),
            force=True,
        )
        is True
    )

    assert len(messages) == 3
    payload = messages[0]
    assert payload["allowed_mentions"] == {"parse": []}
    content = cast(str, payload["content"])
    assert "Loom coordinator report (non-atomic status)" in content
    assert "Admissions: ACTIVE=1, WAITING=1" in content
    assert "Authority runs: RUNNING=1, SUBMITTED=1" in content
    assert "Authority stages: PENDING=1, RUNNING=1, SUBMITTED=1, SUCCEEDED=1" in content
    assert (
        "item=item-active admission=ACTIVE authority=RUNNING/available progress=1/3"
        in content
    )
    assert "Stages: build (RUNNING), publish (SUBMITTED)" in content
    for excluded in (
        "file:///private/run",
        "assignment-secret",
        "scheduler-secret",
        "agent-secret",
        "payload-secret",
        "revision-secret",
    ):
        assert excluded not in content


def test_coordinator_report_is_bounded_and_provider_failures_are_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(204)

    monkeypatch.setattr("loom_discord.sink.httpx.post", fake_post)
    reporter = DiscordCoordinatorReporter("https://discord.invalid/secret-token")
    assert (
        reporter.report(
            _daemon_status(many_active_runs=20), _daemon_details(many_active_runs=20)
        )
        is True
    )
    content = cast(str, cast(dict[str, object], captured["json"])["content"])
    assert len(content) <= 2_000
    assert "Active runs omitted: 14" in content
    assert cast(dict[str, object], captured["json"])["allowed_mentions"] == {
        "parse": []
    }

    def failing_post(url: str, **kwargs: object) -> httpx.Response:
        _ = url, kwargs
        raise httpx.ConnectError(
            "secret-token",
            request=httpx.Request("POST", "https://discord.invalid/secret-token"),
        )

    monkeypatch.setattr("loom_discord.sink.httpx.post", failing_post)
    with pytest.raises(
        DiscordWebhookError, match="Discord webhook transport failed"
    ) as exc_info:
        reporter = DiscordCoordinatorReporter("https://discord.invalid/secret-token")
        reporter.report(_daemon_status(), _daemon_details())
    assert "secret-token" not in str(exc_info.value)
    assert reporter.report(_daemon_status(), _daemon_details()) is False


def test_coordinator_report_prioritizes_running_work_over_waiting_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        _ = url
        captured.update(kwargs)
        return httpx.Response(204)

    monkeypatch.setattr("loom_discord.sink.httpx.post", fake_post)
    reporter = DiscordCoordinatorReporter("https://discord.invalid/webhook-token")

    reporter.report(
        _daemon_status(many_waiting_runs=12), _daemon_details(many_waiting_runs=12)
    )

    content = cast(str, cast(dict[str, object], captured["json"])["content"])
    assert "item=item-active" in content
    assert "Stages: build (RUNNING), publish (SUBMITTED)" in content
    assert "Active runs omitted: 6" in content


def test_coordinator_cli_one_shot_is_injectable_and_sanitizes_status_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        WEBHOOK_URL_ENVIRONMENT_VARIABLE, "https://discord.invalid/token"
    )
    calls: list[bool] = []

    class FakeReporter:
        def report(
            self,
            status: LocalDaemonStatus,
            details: tuple[LocalDaemonAdmissionDetail, ...],
            *,
            force: bool = False,
        ) -> bool:
            assert status is _CLI_STATUS
            assert details == _CLI_DETAILS
            calls.append(force)
            return True

    class FakeClient:
        def status(self) -> LocalDaemonStatus:
            return _CLI_STATUS

        def admissions(self, *, limit: int, cursor: str | None) -> SimpleNamespace:
            assert limit == 100 and cursor is None
            return SimpleNamespace(
                admissions=tuple(item.admission for item in _CLI_DETAILS),
                next_cursor=None,
            )

        def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
            return next(
                item
                for item in _CLI_DETAILS
                if item.admission.admission_id == admission_id
            )

    stderr = StringIO()
    result = cli_module.main(
        ["--endpoint", "/protected/daemon.sock", "--once"],
        client_factory=lambda endpoint: FakeClient(),
        reporter_factory=lambda url, timeout: FakeReporter(),
        stderr=stderr,
    )

    assert result == 0
    assert calls == [True]
    assert stderr.getvalue() == ""

    class FailingClient:
        def status(self) -> LocalDaemonStatus:
            raise RuntimeError("https://discord.invalid/token")

    stderr = StringIO()
    result = cli_module.main(
        ["--endpoint", "/protected/daemon.sock", "--once"],
        client_factory=lambda endpoint: FailingClient(),
        reporter_factory=lambda url, timeout: FakeReporter(),
        stderr=stderr,
    )
    assert result == 1
    assert stderr.getvalue() == "Discord coordinator status read failed\n"
    assert "token" not in stderr.getvalue()


def test_coordinator_cli_collects_all_bounded_admission_pages() -> None:
    calls: list[tuple[str, str | None]] = []
    details = _daemon_details()

    class FakeClient:
        def admissions(self, *, limit: int, cursor: str | None) -> SimpleNamespace:
            calls.append(("page", cursor))
            assert limit == 100
            if cursor is None:
                return SimpleNamespace(
                    admissions=(details[0].admission,), next_cursor="cursor-1"
                )
            return SimpleNamespace(admissions=(details[1].admission,), next_cursor=None)

        def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
            calls.append(("detail", admission_id))
            return next(
                item for item in details if item.admission.admission_id == admission_id
            )

    assert cli_module._collect_admission_details(FakeClient()) == details
    assert calls == [
        ("page", None),
        ("detail", "admission-item-active"),
        ("page", "cursor-1"),
        ("detail", "admission-item-waiting"),
    ]


def test_coordinator_cli_continues_after_a_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        WEBHOOK_URL_ENVIRONMENT_VARIABLE, "https://discord.invalid/token"
    )
    statuses: list[LocalDaemonStatus | Exception] = [
        RuntimeError("https://discord.invalid/token"),
        _CLI_STATUS,
    ]
    reports: list[bool] = []
    sleeps = 0

    class FakeClient:
        def status(self) -> LocalDaemonStatus:
            result = statuses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        def admissions(self, *, limit: int, cursor: str | None) -> SimpleNamespace:
            return SimpleNamespace(
                admissions=tuple(item.admission for item in _CLI_DETAILS),
                next_cursor=None,
            )

        def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
            return next(
                item
                for item in _CLI_DETAILS
                if item.admission.admission_id == admission_id
            )

    class FakeReporter:
        def report(
            self,
            status: LocalDaemonStatus,
            details: tuple[LocalDaemonAdmissionDetail, ...],
            *,
            force: bool = False,
        ) -> bool:
            assert status is _CLI_STATUS
            assert details == _CLI_DETAILS
            reports.append(force)
            return True

    def fake_sleep(seconds: float) -> None:
        nonlocal sleeps
        assert seconds == 2.0
        sleeps += 1
        if sleeps == 2:
            raise KeyboardInterrupt

    stderr = StringIO()
    result = cli_module.main(
        ["--endpoint", "/protected/daemon.sock", "--interval", "2"],
        client_factory=lambda endpoint: FakeClient(),
        reporter_factory=lambda url, timeout: FakeReporter(),
        sleep=fake_sleep,
        monotonic=lambda: 0.0,
        stderr=stderr,
    )

    assert result == 0
    assert reports == [False]
    assert stderr.getvalue() == "Discord coordinator status read failed\n"


def test_coordinator_cli_heartbeat_restarts_after_a_changed_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        WEBHOOK_URL_ENVIRONMENT_VARIABLE, "https://discord.invalid/token"
    )
    report_results = iter((True, True, False, False, True))
    forces: list[bool] = []
    current_time = 0.0
    sleeps = 0

    class FakeClient:
        def status(self) -> LocalDaemonStatus:
            return _CLI_STATUS

        def admissions(self, *, limit: int, cursor: str | None) -> SimpleNamespace:
            return SimpleNamespace(
                admissions=tuple(item.admission for item in _CLI_DETAILS),
                next_cursor=None,
            )

        def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
            return next(
                item
                for item in _CLI_DETAILS
                if item.admission.admission_id == admission_id
            )

    class FakeReporter:
        def report(
            self,
            status: LocalDaemonStatus,
            details: tuple[LocalDaemonAdmissionDetail, ...],
            *,
            force: bool = False,
        ) -> bool:
            assert status is _CLI_STATUS
            assert details == _CLI_DETAILS
            forces.append(force)
            return next(report_results)

    def fake_monotonic() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time, sleeps
        assert seconds == 4.0
        current_time += seconds
        sleeps += 1
        if sleeps == 5:
            raise KeyboardInterrupt

    result = cli_module.main(
        [
            "--endpoint",
            "/protected/daemon.sock",
            "--interval",
            "4",
            "--heartbeat",
            "10",
        ],
        client_factory=lambda endpoint: FakeClient(),
        reporter_factory=lambda url, timeout: FakeReporter(),
        sleep=fake_sleep,
        monotonic=fake_monotonic,
        stderr=StringIO(),
    )

    assert result == 0
    assert forces == [False, False, False, False, True]


def _daemon_status(
    *,
    as_of: str = "2026-08-28T00:00:00Z",
    stage_state: str = "RUNNING",
    many_active_runs: int = 0,
    many_waiting_runs: int = 0,
) -> LocalDaemonStatus:
    admissions = [_admission("item-active", LocalDaemonAdmissionState.ACTIVE)]
    views: list[Mapping[str, PlainData]] = [
        {
            "queue_item_id": "item-active",
            "run_uri": "file:///private/run",
            "admission": {"state": "ACTIVE", "revision": "revision-secret"},
            "authority": {
                "availability": "available",
                "state": "RUNNING",
                "stages": {
                    "build": stage_state,
                    "publish": "SUBMITTED",
                    "prepare": "SUCCEEDED",
                },
            },
            "assignment": {"assignment_id": "assignment-secret"},
            "scheduling": {"job": "scheduler-secret"},
            "execution": {"agent": "agent-secret"},
            "payload": "payload-secret",
        }
    ]
    admissions.append(_admission("item-waiting", LocalDaemonAdmissionState.WAITING))
    views.append(
        {
            "queue_item_id": "item-waiting",
            "authority": {
                "availability": "available",
                "state": "SUBMITTED",
                "stages": {"prepare": "PENDING"},
            },
        }
    )
    for index in range(many_active_runs):
        queue_item_id = f"item-{index:02d}-" + "x" * 180
        admissions.append(_admission(queue_item_id, LocalDaemonAdmissionState.ACTIVE))
        views.append(
            {
                "queue_item_id": queue_item_id,
                "authority": {
                    "availability": "available",
                    "state": "RUNNING",
                    "stages": {f"stage-{index}-" + "y" * 180: "RUNNING"},
                },
            }
        )
    for index in range(many_waiting_runs):
        queue_item_id = f"item-{index:02d}-waiting"
        admissions.append(_admission(queue_item_id, LocalDaemonAdmissionState.WAITING))
        views.append(
            {
                "queue_item_id": queue_item_id,
                "authority": {
                    "availability": "available",
                    "state": "SUBMITTED",
                    "stages": {"prepare": "PENDING"},
                },
            }
        )
    return LocalDaemonStatus(
        coordinator_id="coordinator-secret",
        coordinator_epoch="epoch-secret",
        as_of=as_of,
        service_health="healthy",
        service_diagnostic=None,
        scheduling_epoch="scheduling-secret",
        active_admissions=sum(
            admission.state is LocalDaemonAdmissionState.ACTIVE
            for admission in admissions
        ),
        waiting_admissions=sum(
            admission.state is LocalDaemonAdmissionState.WAITING
            for admission in admissions
        ),
        running_assignments=0,
        accepted_time_health="healthy",
        accepted_time_diagnostic=None,
    )


def _admission(
    queue_item_id: str, state: LocalDaemonAdmissionState
) -> LocalDaemonAdmission:
    return LocalDaemonAdmission(
        admission_id=f"admission-{queue_item_id}",
        queue_item_id=queue_item_id,
        coordinator_id="coordinator-secret",
        run_uri=f"file:///private/{queue_item_id}",
        intent_digest="intent-secret",
        execution_owner="owner-secret",
        state=state,
        accepted_at="2026-08-28T00:00:00Z",
        authority_operation_id="operation-secret",
    )


def _daemon_details(
    *,
    stage_state: str = "RUNNING",
    many_active_runs: int = 0,
    many_waiting_runs: int = 0,
) -> tuple[LocalDaemonAdmissionDetail, ...]:
    records = [
        _detail(
            _admission("item-active", LocalDaemonAdmissionState.ACTIVE),
            "RUNNING",
            {"build": stage_state, "publish": "SUBMITTED", "prepare": "SUCCEEDED"},
        ),
        _detail(
            _admission("item-waiting", LocalDaemonAdmissionState.WAITING),
            "SUBMITTED",
            {"prepare": "PENDING"},
        ),
    ]
    for index in range(many_active_runs):
        queue_item_id = f"item-{index:02d}-" + "x" * 180
        records.append(
            _detail(
                _admission(queue_item_id, LocalDaemonAdmissionState.ACTIVE),
                "RUNNING",
                {f"stage-{index}-" + "y" * 180: "RUNNING"},
            )
        )
    for index in range(many_waiting_runs):
        records.append(
            _detail(
                _admission(
                    f"item-{index:02d}-waiting", LocalDaemonAdmissionState.WAITING
                ),
                "SUBMITTED",
                {"prepare": "PENDING"},
            )
        )
    return tuple(records)


def _detail(
    admission: LocalDaemonAdmission, state: str, stages: Mapping[str, PlainData]
) -> LocalDaemonAdmissionDetail:
    return LocalDaemonAdmissionDetail(
        admission=admission,
        authority={
            "owner": "per-run-authority",
            "availability": "available",
            "state": state,
            "stages": stages,
            "observed_at": "2026-08-28T00:00:00Z",
            "freshness": "current",
        },
    )


_CLI_STATUS = _daemon_status()
_CLI_DETAILS = _daemon_details()


def _event(
    *,
    event_type: str,
    run_uri: str = "run://example",
    payload: Mapping[str, PlainData] | None = None,
) -> PipelineEventRecord:
    return PipelineEventRecord(
        run_uri=run_uri,
        sequence=1,
        event_type=event_type,
        occurred_at="2026-08-28T00:00:00Z",
        scope=EventScope.stage("publish"),
        payload={} if payload is None else payload,
    )
