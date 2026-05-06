"""Unit tests for ``loom validate`` command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
import loom.cli.validate as validate_command
from loom.errors import ConfigError, PipelineError


pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class FakeComposedConfig:
    resolved: dict[str, object]


@dataclass(frozen=True, slots=True)
class FakePipelineResult:
    spec: object = object()
    stage_count: int = 2
    pipeline_name: str | None = "demo"
    stage_factory_target_paths: tuple[str, ...] = ("$.pipeline.stages[0].factory",)


@dataclass(frozen=True, slots=True)
class FakeTargetResult:
    target_count: int
    checked_paths: tuple[str, ...] = ()


def test_validate_static_text_preserves_config_option_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def compose(config_path: object, *, overlays: tuple[Path, ...], overrides: tuple[str, ...]) -> FakeComposedConfig:
        calls["config_path"] = config_path
        calls["overlays"] = overlays
        calls["overrides"] = overrides
        return FakeComposedConfig(resolved={"pipeline": {}})

    monkeypatch.setattr(validate_command, "_compose_config", compose)
    monkeypatch.setattr(validate_command, "_validate_pipeline_config", lambda _config: FakePipelineResult())

    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        [
            "validate",
            "base.yaml",
            "--overlay",
            "team.yaml",
            "--overlay",
            "local.yaml",
            "--set",
            "a=1",
            "--set",
            "b=2",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == "OK validate base.yaml: 2 stages\n"
    assert stderr.getvalue() == ""
    assert calls == {
        "config_path": Path("base.yaml"),
        "overlays": (Path("team.yaml"), Path("local.yaml")),
        "overrides": ("a=1", "b=2"),
    }


def test_validate_json_check_targets_warns_and_invokes_facades_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    def compose(*_args: object, **_kwargs: object) -> FakeComposedConfig:
        events.append("compose")
        return FakeComposedConfig(resolved={"pipeline": {}, "service": {}})

    def validate_pipeline(_config: object) -> FakePipelineResult:
        events.append("static")
        return FakePipelineResult()

    def check_pipeline(_spec: object) -> FakeTargetResult:
        events.append("pipeline-targets")
        return FakeTargetResult(target_count=1)

    def check_config(_config: object, *, skip_paths: tuple[str, ...]) -> FakeTargetResult:
        events.append(f"config-targets:{','.join(skip_paths)}")
        return FakeTargetResult(target_count=2)

    monkeypatch.setattr(validate_command, "_compose_config", compose)
    monkeypatch.setattr(validate_command, "_validate_pipeline_config", validate_pipeline)
    monkeypatch.setattr(validate_command, "_check_pipeline_stage_targets", check_pipeline)
    monkeypatch.setattr(validate_command, "_check_config_targets", check_config)

    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["validate", "base.yaml", "--check-targets", "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert events == [
        "compose",
        "static",
        "pipeline-targets",
        "config-targets:$.pipeline.stages[0].factory",
    ]
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.validate.v2"
    assert payload["ok"] is True
    assert payload["warnings"] == [
        {
            "code": "validate.target_constructors_may_run",
            "message": "--check-targets imports and constructs trusted project targets.",
            "details": {"consent_boundary": "--check-targets"},
        }
    ]
    assert payload["result"]["target_count"] == 3
    assert payload["result"]["check_targets"] is True


def test_validate_text_check_targets_prints_warning_before_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validate_command, "_compose_config", lambda *_args, **_kwargs: FakeComposedConfig(resolved={}))
    monkeypatch.setattr(validate_command, "_validate_pipeline_config", lambda _config: FakePipelineResult(stage_count=1))
    monkeypatch.setattr(validate_command, "_check_pipeline_stage_targets", lambda _spec: FakeTargetResult(target_count=1))
    monkeypatch.setattr(
        validate_command,
        "_check_config_targets",
        lambda _config, *, skip_paths: FakeTargetResult(target_count=0),
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", "base.yaml", "--check-targets"], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == "OK validate base.yaml: 1 stage\n"
    assert stderr.getvalue() == "warning: --check-targets imports and constructs trusted project targets.\n"


@pytest.mark.parametrize(
    ("error", "expected_exit"),
    [(ConfigError("bad config"), 3), (PipelineError("bad pipeline"), 4)],
)
def test_validate_errors_map_to_config_or_pipeline_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_exit: int,
) -> None:
    if isinstance(error, ConfigError):
        monkeypatch.setattr(validate_command, "_compose_config", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    else:
        monkeypatch.setattr(validate_command, "_compose_config", lambda *_args, **_kwargs: FakeComposedConfig(resolved={}))
        monkeypatch.setattr(validate_command, "_validate_pipeline_config", lambda _config: (_ for _ in ()).throw(error))

    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", "base.yaml"], stdout=stdout, stderr=stderr) == expected_exit
    assert stdout.getvalue() == ""
    assert f"error: {error}" in stderr.getvalue()


def test_validate_json_error_keeps_target_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validate_command, "_compose_config", lambda *_args, **_kwargs: FakeComposedConfig(resolved={}))
    monkeypatch.setattr(validate_command, "_validate_pipeline_config", lambda _config: FakePipelineResult())
    monkeypatch.setattr(
        validate_command,
        "_check_pipeline_stage_targets",
        lambda _spec: (_ for _ in ()).throw(PipelineError("target failed")),
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["validate", "base.yaml", "--check-targets", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["warnings"][0]["code"] == "validate.target_constructors_may_run"
    assert payload["error"]["message"] == "target failed"
