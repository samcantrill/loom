"""Executable docs examples from README and examples/."""

import os
import subprocess
import sys
from typing import cast
from pathlib import Path

import pytest
import yaml

from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction
from loom.pipeline.stores import LocalRunStore


pytestmark = pytest.mark.integration

EXAMPLES_ROOT = Path(__file__).resolve().parents[3] / "examples"
REQUIRED_MANIFEST_FIELDS = {
    "id",
    "title",
    "summary",
    "capability",
    "level",
    "introduced_in",
    "status",
    "validation",
    "entrypoints",
    "tags",
}
VALID_STATUSES = {"runnable", "illustrative", "deferred"}
VALID_VALIDATION_TIERS = {"smoke", "full", "manual"}
VALID_LEVELS = {"introductory", "intermediate", "advanced"}


def _config_path(base: Path) -> Path:
    config = base / "demo_pipeline.yaml"
    config.write_text(
        """
name: demo
pipeline:
  name: demo
  stages:
    - name: build
      _target_: tests.support.pipeline_execution_stages.JsonProducerStage
      config:
        value: 1
      outputs:
        data:
          artifact_type: json
          codec_key: json.v1
    - name: report
      _target_: tests.support.pipeline_execution_stages.TextConsumerStage
      inputs:
        data: build.data
      outputs:
        text:
          artifact_type: text
          codec_key: text.v1
"""
    )
    return config


def test_readme_python_api_example_runs_and_reuses_same_run(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)
    config = compose_config(_config_path(tmp_path)).resolved
    first = runner.run(RunRequest(config=config, run_id="run-1"))
    second = runner.run(
        RunRequest(config=config, run_id="run-1", open_existing=True)
    )

    assert first.status.name == "SUCCEEDED"
    assert second.stage_results["build"].action == PlanAction.REUSE
    assert second.stage_results["report"].action == PlanAction.REUSE


def test_examples_catalog_manifests_are_valid() -> None:
    manifests = _example_manifests()

    assert manifests
    seen_ids: set[str] = set()
    for manifest_path, manifest in manifests:
        example_dir = manifest_path.parent
        relative_dir = example_dir.relative_to(EXAMPLES_ROOT)
        expected_id = ".".join(relative_dir.parts)
        example_id = _required_string(manifest, "id", manifest_path)
        capability = _required_string(manifest, "capability", manifest_path)
        status = _required_string(manifest, "status", manifest_path)
        validation = _required_string(manifest, "validation", manifest_path)
        level = _required_string(manifest, "level", manifest_path)

        assert set(manifest) >= REQUIRED_MANIFEST_FIELDS
        assert example_id == expected_id
        assert example_id not in seen_ids
        assert len(relative_dir.parts) >= 2
        assert capability == relative_dir.parts[0]
        assert (EXAMPLES_ROOT / capability / "README.md").is_file()
        assert (example_dir / "README.md").is_file()
        assert status in VALID_STATUSES
        assert validation in VALID_VALIDATION_TIERS
        assert level in VALID_LEVELS
        assert _required_string(manifest, "title", manifest_path)
        assert _required_string(manifest, "summary", manifest_path)
        assert _required_string(manifest, "introduced_in", manifest_path)
        assert _required_string_list(manifest, "tags", manifest_path)
        _validate_entrypoints(manifest, manifest_path)
        if status != "runnable" or validation == "manual":
            assert _required_string(manifest, "reason", manifest_path)

        seen_ids.add(example_id)


def _example_manifest_paths() -> list[Path]:
    return sorted(EXAMPLES_ROOT.rglob("example.yaml"))


def _example_manifests() -> list[tuple[Path, dict[str, object]]]:
    return [(path, _load_manifest(path)) for path in _example_manifest_paths()]


def _load_manifest(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError(f"{path} must contain a mapping")
    return cast(dict[str, object], loaded)


def _example_entrypoints(validation: str) -> list[tuple[str, Path]]:
    cases: list[tuple[str, Path]] = []
    for manifest_path, manifest in _example_manifests():
        if manifest.get("status") != "runnable":
            continue
        if manifest.get("validation") != validation:
            continue
        example_id = _required_string(manifest, "id", manifest_path)
        for entrypoint in _entrypoint_mappings(manifest, manifest_path):
            if entrypoint.get("kind") != "python":
                continue
            path = _entrypoint_path(entrypoint, manifest_path)
            cases.append((example_id, path))
    return cases


def _validate_entrypoints(
    manifest: dict[str, object],
    manifest_path: Path,
) -> None:
    entrypoints = _entrypoint_mappings(manifest, manifest_path)
    if manifest.get("status") == "runnable":
        assert entrypoints
    for entrypoint in entrypoints:
        assert _required_string(entrypoint, "path", manifest_path)
        assert _required_string(entrypoint, "kind", manifest_path) == "python"
        assert _required_string(entrypoint, "description", manifest_path)
        assert _entrypoint_path(entrypoint, manifest_path).is_file()


def _entrypoint_mappings(
    manifest: dict[str, object],
    manifest_path: Path,
) -> list[dict[str, object]]:
    entrypoints = manifest.get("entrypoints")
    if not isinstance(entrypoints, list):
        raise AssertionError(f"{manifest_path} entrypoints must be a list")
    output: list[dict[str, object]] = []
    for index, entrypoint in enumerate(entrypoints):
        if not isinstance(entrypoint, dict):
            raise AssertionError(
                f"{manifest_path} entrypoints[{index}] must be a mapping"
            )
        output.append(cast(dict[str, object], entrypoint))
    return output


def _entrypoint_path(entrypoint: dict[str, object], manifest_path: Path) -> Path:
    path = _required_string(entrypoint, "path", manifest_path)
    candidate = manifest_path.parent / path
    try:
        candidate.resolve(strict=False).relative_to(
            manifest_path.parent.resolve(strict=False)
        )
    except ValueError as exc:
        raise AssertionError(
            f"{manifest_path} entrypoint path must stay inside the example directory"
        ) from exc
    return candidate


def _required_string(
    mapping: dict[str, object],
    key: str,
    manifest_path: Path,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise AssertionError(f"{manifest_path} {key} must be a non-empty string")
    return value


def _required_string_list(
    mapping: dict[str, object],
    key: str,
    manifest_path: Path,
) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not value:
        raise AssertionError(f"{manifest_path} {key} must be a non-empty list")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise AssertionError(
                f"{manifest_path} {key}[{index}] must be a non-empty string"
            )
    return cast(list[str], value)


@pytest.mark.parametrize(("example_id", "script"), _example_entrypoints("smoke"))
def test_v0_smoke_example_scripts_execute(
    example_id: str,
    script: Path,
    tmp_path: Path,
) -> None:
    repo_root = EXAMPLES_ROOT.parent
    env = os.environ.copy()
    env["LOOM_EXAMPLE_OUTPUT_ROOT"] = str(tmp_path / "outputs" / example_id)
    env["LOOM_EXAMPLE_RUN_ROOT"] = str(tmp_path / "runs" / example_id)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip()
