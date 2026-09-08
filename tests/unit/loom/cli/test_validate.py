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
class FakeSpec:
    stage_names: tuple[str, ...] = ("build", "test")


@dataclass(frozen=True, slots=True)
class FakePipelineResult:
    spec: FakeSpec = FakeSpec()
    stage_count: int = 2
    pipeline_name: str | None = "demo"
    stage_factory_target_paths: tuple[str, ...] = ("$.pipeline.stages[0].factory",)


def test_validate_static_text_preserves_config_option_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def compose(
        config_path: object, *, overlays: tuple[Path, ...], overrides: tuple[str, ...]
    ) -> FakeComposedConfig:
        calls["config_path"] = config_path
        calls["overlays"] = overlays
        calls["overrides"] = overrides
        return FakeComposedConfig(resolved={"pipeline": {}})

    monkeypatch.setattr(validate_command, "_compose_config", compose)
    monkeypatch.setattr(
        validate_command,
        "_validate_pipeline_config",
        lambda _config: FakePipelineResult(),
    )

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


def test_validate_json_reports_v3_static_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    resolved = {
        "pipeline": {"stage_data": {"_target_": "inert"}},
        "service": {"_target_": "project.Service"},
    }

    def compose(*_args: object, **_kwargs: object) -> FakeComposedConfig:
        events.append("compose")
        return FakeComposedConfig(resolved=resolved)

    def validate_pipeline(_config: object) -> FakePipelineResult:
        events.append("static")
        return FakePipelineResult()

    monkeypatch.setattr(validate_command, "_compose_config", compose)
    monkeypatch.setattr(
        validate_command, "_validate_pipeline_config", validate_pipeline
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["validate", "base.yaml", "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert events == ["compose", "static"]
    payload = json.loads(stdout.getvalue())
    assert payload == {
        "schema_version": "loom.cli.validate.v3",
        "ok": True,
        "warnings": [],
        "result": {
            "config_path": "base.yaml",
            "pipeline_name": "demo",
            "stage_count": 2,
        },
    }


def test_validate_removed_check_targets_option_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["validate", "base.yaml", "--check-targets"], stdout=stdout, stderr=stderr)
        == 2
    )
    assert stdout.getvalue() == ""
    assert "unrecognized arguments: --check-targets" in stderr.getvalue()


def test_validate_help_assigns_project_readiness_to_project_owners() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", "--help"], stdout=stdout, stderr=stderr) == 0
    assert (
        "Project owners perform construction and readiness checks during execution."
        in " ".join(stdout.getvalue().split())
    )
    assert "--check-targets" not in stdout.getvalue()
    assert stderr.getvalue() == ""


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
        monkeypatch.setattr(
            validate_command,
            "_compose_config",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
        )
    else:
        monkeypatch.setattr(
            validate_command,
            "_compose_config",
            lambda *_args, **_kwargs: FakeComposedConfig(resolved={}),
        )
        monkeypatch.setattr(
            validate_command,
            "_validate_pipeline_config",
            lambda _config: (_ for _ in ()).throw(error),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["validate", "base.yaml"], stdout=stdout, stderr=stderr) == expected_exit
    )
    assert stdout.getvalue() == ""
    assert f"error: {error}" in stderr.getvalue()
