"""Integration coverage for the downstream Discord webhook event sink."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
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
TERMINAL_RUN_EVENT_TYPES = sink_module.TERMINAL_RUN_EVENT_TYPES
WEBHOOK_URL_ENVIRONMENT_VARIABLE = sink_module.WEBHOOK_URL_ENVIRONMENT_VARIABLE
discord_event_sink = loom_discord.discord_event_sink


def test_metadata_factory_and_terminal_filter_are_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = tomllib.loads((EXAMPLE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "loom-discord"
    assert metadata["project"]["dependencies"] == ["httpx>=0.28,<1", "loom"]
    assert metadata["project"]["entry-points"]["loom.event_sinks"] == {
        "notifications.discord": "loom_discord:discord_event_sink"
    }

    monkeypatch.delenv(WEBHOOK_URL_ENVIRONMENT_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match=WEBHOOK_URL_ENVIRONMENT_VARIABLE):
        discord_event_sink()

    monkeypatch.setenv(WEBHOOK_URL_ENVIRONMENT_VARIABLE, "https://discord.invalid/webhook-token")
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
    sink = DiscordWebhookSink("https://discord.invalid/webhook-token", timeout_seconds=3.5)
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
