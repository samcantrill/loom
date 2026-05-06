"""Unit tests for ``loom plan`` command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.cli.options import ConfigCliOptions, PlanCliOptions, SelectorCliOptions
import loom.cli.plan as plan_command
from loom.pipeline.planning import FingerprintStatus, PlanAction, PlanReason, PlanReasonCode, PlanSelectors


pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class FakeComposedConfig:
    resolved: dict[str, object]


@dataclass(frozen=True, slots=True)
class FakePipelineResult:
    spec: object = object()
    pipeline_name: str | None = "demo"
    stage_count: int = 1


@dataclass(frozen=True, slots=True)
class FakeStagePlan:
    stage_name: str = "build"
    action: PlanAction = PlanAction.RUN
    base_action: PlanAction = PlanAction.RUN
    fingerprint_status: FingerprintStatus = FingerprintStatus.COMPUTED
    reasons: tuple[PlanReason, ...] = (
        PlanReason(PlanReasonCode.RESUME_DISABLED, "resume is disabled", stage_name="build"),
    )
    pending_inputs: tuple[object, ...] = ()
    reusable_outputs: dict[str, object] | None = None
    upstream_stages: tuple[str, ...] = ()
    downstream_stages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.reusable_outputs is None:
            object.__setattr__(self, "reusable_outputs", {})


@dataclass(frozen=True, slots=True)
class FakePlan:
    pipeline_name: str | None = "demo"
    selectors: PlanSelectors = PlanSelectors()
    summary: dict[str, int] | None = None
    ordered_stage_plans: tuple[FakeStagePlan, ...] = (FakeStagePlan(),)

    def __post_init__(self) -> None:
        if self.summary is None:
            object.__setattr__(self, "summary", {"RUN": 1, "REUSE": 0})


class FakeRunStore:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.opened: list[str] = []
        self.resolved: list[str] = []

    def resolve_run_uri(self, run_uri: str) -> str:
        self.resolved.append(run_uri)
        return "file:///abs/runs/demo"

    def open_run(self, run_uri: str) -> None:
        self.opened.append(run_uri)

    def run_uri_exists(self, run_uri: str) -> bool:
        assert run_uri == "file:///abs/runs/demo"
        return self.exists

    def local_artifact_root(self, run_uri: str) -> Path:
        assert run_uri == "file:///abs/runs/demo"
        return Path("/abs/runs/demo/artifacts")

    def allocate_run_uri(self) -> str:
        raise AssertionError("plan must not allocate a default run URI")


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, store: FakeRunStore | None = None) -> dict[str, object]:
    calls: dict[str, object] = {}
    fake_store = store or FakeRunStore()

    def compose(config_path: object, *, overlays: tuple[Path, ...], overrides: tuple[str, ...]) -> FakeComposedConfig:
        calls["config_path"] = config_path
        calls["overlays"] = overlays
        calls["overrides"] = overrides
        return FakeComposedConfig(resolved={"pipeline": {}})

    def plan_pipeline(*_args: object, **kwargs: object) -> FakePlan:
        calls["planner_run_uri"] = kwargs["run_uri"]
        calls["resume_enabled"] = kwargs["resume_enabled"]
        calls["selectors"] = kwargs["selectors"]
        selectors = kwargs["selectors"]
        assert isinstance(selectors, PlanSelectors)
        return FakePlan(selectors=selectors)

    monkeypatch.setattr(plan_command, "_compose_config", compose)
    monkeypatch.setattr(plan_command, "_validate_pipeline_config", lambda _config: FakePipelineResult())
    monkeypatch.setattr(plan_command, "_create_default_run_store", lambda: fake_store)
    monkeypatch.setattr(plan_command, "_plan_pipeline", plan_pipeline)
    return calls


def test_plan_fresh_text_is_read_only_and_hides_internal_run_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_common(monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "plan",
            "base.yaml",
            "--overlay",
            "team.yaml",
            "--set",
            "a=1",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert stdout.getvalue() == (
        "OK plan base.yaml: 1 stage action\n"
        "build: RUN [RESUME_DISABLED]\n"
    )
    assert calls["config_path"] == Path("base.yaml")
    assert calls["overlays"] == (Path("team.yaml"),)
    assert calls["overrides"] == ("a=1",)
    assert calls["planner_run_uri"] == "file:///__loom_plan_hypothetical__"
    assert calls["resume_enabled"] is False


def test_plan_explicit_run_uri_json_uses_resolved_uri_and_selector_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_common(monkeypatch)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "plan",
                "base.yaml",
                "--run-uri",
                "file://./runs/demo",
                "--only-stage",
                "build",
                "--force-stage",
                "build",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert stderr.getvalue() == ""
    assert calls["planner_run_uri"] == "file:///abs/runs/demo"
    selectors = calls["selectors"]
    assert isinstance(selectors, PlanSelectors)
    assert selectors.only_stages == ("build",)
    assert selectors.force_stages == ("build",)
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["ok"] is True
    assert payload["warnings"] == []
    assert payload["result"]["run_uri"] == "file:///abs/runs/demo"
    assert payload["result"]["resume"] is False
    assert payload["result"]["stage_actions"][0]["reason_codes"] == ["RESUME_DISABLED"]


def test_plan_resume_requires_run_uri_before_config_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_command, "_create_default_run_store", lambda: FakeRunStore())
    monkeypatch.setattr(
        plan_command,
        "_compose_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("compose should not run")),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["plan", "base.yaml", "--resume"], stdout=stdout, stderr=stderr) == 4
    assert stdout.getvalue() == ""
    assert "`loom plan --resume` requires --run-uri" in stderr.getvalue()


def test_plan_existing_non_resume_run_uri_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, store=FakeRunStore(exists=True))
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plan", "base.yaml", "--run-uri", "file://./runs/demo", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["type"] == "RunAlreadyExistsError"


def test_plan_resume_opens_existing_run(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeRunStore()
    _patch_common(monkeypatch, store=store)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plan", "base.yaml", "--run-uri", "file://./runs/demo", "--resume"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert store.opened == ["file:///abs/runs/demo"]


def test_plan_build_result_supports_explanation_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        plan_command,
        "_explanation_payload",
        lambda _plan, stage: {
            "stage": stage,
            "reasons": [{"code": "RESUME_DISABLED", "message": "resume is disabled"}],
        },
    )

    result = plan_command.build_plan_result(
        config_options=ConfigCliOptions(config_path=Path("base.yaml")),
        plan_options=PlanCliOptions(explain_stage="build"),
        selector_options=SelectorCliOptions(),
    )

    assert result.explanation == {
        "stage": "build",
        "reasons": [{"code": "RESUME_DISABLED", "message": "resume is disabled"}],
    }
