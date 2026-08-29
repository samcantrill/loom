"""Executable docs examples from README and examples/."""

import os
import subprocess
import sys
from pathlib import Path
import re
from typing import cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")
import yaml

from weave import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import PlanAction
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]

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
    "surface",
    "entrypoints",
    "tags",
    "public_surfaces",
    "owner_docs",
    "owner_stages",
    "validation_path",
}
VALID_STATUSES = {"runnable", "illustrative", "deferred"}
VALID_VALIDATION_TIERS = {"smoke", "full", "manual"}
VALID_LEVELS = {"introductory", "intermediate", "advanced"}
VALID_SURFACES = {"cli", "python_api", "internal_demo"}
RUNNABLE_SMOKE_VALIDATION_COMMAND = (
    "uv run pytest tests/integration/docs/test_v0_python_examples.py::"
    "test_smoke_example_scripts_execute"
)
INTERNAL_DEMO_EXAMPLES = {
    "operations.authority-backend-diagnostics",
    "operations.submitted-status",
}
PYTHON_API_EXAMPLES = {
    "execution.local",
    "execution.python-run-options",
    "operations.captured-logs",
    "operations.managed-local-queue",
    "operations.resource-leases",
    "extensions.event-sink",
    "extensions.discord-webhook",
    "storage.fake-backend-materialization",
}
USER_FACING_V10_EXAMPLES = {
    "execution.offline-first-import": "smoke",
    "operations.authority-lifecycle": "smoke",
    "operations.offline-import-rejections": "full",
    "operations.resource-leases": "full",
}
NON_USER_FACING_V10_EXAMPLES = {
    "operations.authority-backend-diagnostics": "smoke",
}
USER_FACING_V17_EXAMPLES = {
    "execution.containers.docker": "smoke",
}
CO_LOCATED_VARIANT_EXAMPLES = {
    "execution.containers.docker",
    "execution.runtime-profile",
    "execution.subprocess",
    "execution.offline-first-import",
    "execution.slurm.dry-run-basics",
    "execution.slurm.afterok-diamond",
    "operations.local-diagnostics",
    "operations.failing-run",
    "operations.offline-import-rejections",
}


def _config_path(base: Path) -> Path:
    config = base / "demo_pipeline.yaml"
    config.write_text(
        """
name: demo
pipeline:
  name: demo
  stages:
    - name: build
      factory:
        _target_: tests.support.pipeline_execution_stages.JsonProducerStage
      config:
        value: 1
      outputs:
        data:
          artifact_type: json
          codec_key: json.v1
    - name: report
      factory:
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
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
    )
    runner = PipelineRunner(run_store=run_store)
    config = compose_config(_config_path(tmp_path)).resolved
    run_uri = path_to_run_uri(tmp_path / "runs" / "run-1")
    first = runner.run(RunRequest(config=config, run_uri=run_uri))
    second = runner.run(RunRequest(config=config, run_uri=run_uri, open_existing=True))

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
        surface = _required_string(manifest, "surface", manifest_path)
        public_surfaces = _required_string_list(manifest, "public_surfaces", manifest_path)
        owner_docs = _required_string_list(manifest, "owner_docs", manifest_path)
        owner_stages = _required_string_list(manifest, "owner_stages", manifest_path)
        validation_path = _required_string(manifest, "validation_path", manifest_path)

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
        assert surface in VALID_SURFACES
        assert public_surfaces
        assert surface == _expected_surface(example_id)
        assert surface in public_surfaces
        for stage in owner_stages:
            if not stage.startswith("v") or not stage[1:].isdigit():
                raise AssertionError(f"{manifest_path} owner_stages values must be like vN")
        for owner_doc in owner_docs:
            owner_doc_path = EXAMPLES_ROOT.parent / owner_doc
            assert owner_doc_path.is_file(), f"{manifest_path} owner_doc {owner_doc} must exist"
        assert _required_string(manifest, "title", manifest_path)
        assert _required_string(manifest, "summary", manifest_path)
        assert _required_string(manifest, "introduced_in", manifest_path)
        assert _required_string_list(manifest, "tags", manifest_path)
        _assert_validation_reference(validation_path, manifest_path)
        _validate_entrypoints(manifest, manifest_path)
        if status != "runnable" or validation == "manual":
            assert _required_string_list(manifest, "prerequisites", manifest_path)
            assert _required_string(manifest, "manual_rationale", manifest_path)
            assert validation == "manual"
        if validation == "smoke":
            assert manifest["status"] == "runnable"
            assert (
                _required_string(manifest, "validation_command", manifest_path)
                == RUNNABLE_SMOKE_VALIDATION_COMMAND
            )

        seen_ids.add(example_id)


def test_config_docs_warn_against_plaintext_secret_overrides() -> None:
    config_docs = (EXAMPLES_ROOT.parent / "docs" / "features" / "config.md").read_text(
        encoding="utf-8"
    )

    assert "+auth.token=plaintext-secret" in config_docs
    assert "${oc.env:AUTH_TOKEN}" in config_docs
    assert "plaintext_secret_override_warnings" in config_docs


def test_v10_authority_examples_are_cataloged_and_documented() -> None:
    manifests = _example_manifest_map()

    for example_id, validation in USER_FACING_V10_EXAMPLES.items():
        manifest = manifests[example_id]
        assert manifest["introduced_in"] == "v10"
        assert manifest["status"] == "runnable"
        assert manifest["validation"] == validation
        assert manifest["surface"] != "internal_demo"

    for example_id, validation in NON_USER_FACING_V10_EXAMPLES.items():
        manifest = manifests[example_id]
        assert manifest["introduced_in"] == "v10"
        assert manifest["status"] == "runnable"
        assert manifest["validation"] == validation
        assert manifest["surface"] == "internal_demo"

    examples_readme = (EXAMPLES_ROOT / "README.md").read_text(encoding="utf-8")
    coverage_doc = (
        EXAMPLES_ROOT.parent / "docs" / "features" / "authority-example-coverage.md"
    ).read_text(encoding="utf-8")

    assert "authority-example-coverage.md" in examples_readme
    assert "Not Currently User-Facing" in coverage_doc
    assert "co_located_service" in coverage_doc
    for example_id in USER_FACING_V10_EXAMPLES:
        assert example_id in coverage_doc
    for example_id in NON_USER_FACING_V10_EXAMPLES:
        assert example_id in coverage_doc


def test_v17_docker_examples_are_cataloged_and_documented() -> None:
    manifests = _example_manifest_map()

    for example_id, validation in USER_FACING_V17_EXAMPLES.items():
        manifest = manifests[example_id]
        assert manifest["introduced_in"] == "v17"
        assert manifest["status"] == "runnable"
        assert manifest["validation"] == validation
        assert manifest["surface"] == "cli"

    examples_readme = (EXAMPLES_ROOT / "README.md").read_text(encoding="utf-8")
    execution_readme = (EXAMPLES_ROOT / "execution" / "README.md").read_text(
        encoding="utf-8"
    )
    coverage_doc = (
        EXAMPLES_ROOT.parent / "docs" / "features" / "container-example-coverage.md"
    ).read_text(encoding="utf-8")
    docker_readme = _example_readme_path("execution.containers.docker").read_text(
        encoding="utf-8"
    )

    assert "container-example-coverage.md" in examples_readme
    assert "execution.containers.docker" in execution_readme
    assert "execution.containers.docker" in coverage_doc
    assert "--executor docker" in docker_readme
    assert "executor.docker.command" in docker_readme
    assert "filesystem.docker.artifact_root_visible" in docker_readme
    assert "security sandbox" in docker_readme
    assert "untrusted project code" in docker_readme
    assert "Docker daemon" in docker_readme


def test_v30_experiment_extension_and_apptainer_examples_are_cataloged() -> None:
    manifests = _example_manifest_map()
    expected = {
        "experiments.deterministic-sweep": "cli",
        "extensions.event-sink": "python_api",
        "execution.containers.slurm-apptainer": "cli",
        "storage.fake-backend-materialization": "python_api",
    }
    for example_id, surface in expected.items():
        manifest = manifests[example_id]
        assert manifest["introduced_in"] == "v30"
        assert manifest["status"] == "runnable"
        assert manifest["validation"] == "full"
        assert manifest["surface"] == surface

    examples_readme = (EXAMPLES_ROOT / "README.md").read_text(encoding="utf-8")
    execution_readme = (EXAMPLES_ROOT / "execution" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "experiments/README.md" in examples_readme
    assert "extensions/README.md" in examples_readme
    assert "storage/README.md" in examples_readme
    assert "execution.containers.slurm-apptainer" in execution_readme


def test_inventory_owner_docs_and_feature_coverage_references_are_true() -> None:
    for manifest_path, manifest in _example_manifests():
        example_id = _required_string(manifest, "id", manifest_path)
        owner_docs = _required_string_list(manifest, "owner_docs", manifest_path)
        validation_path = _required_string(manifest, "validation_path", manifest_path)
        validation_doc = validation_path.split("::", 1)[0]

        for owner_doc in owner_docs:
            doc_path = EXAMPLES_ROOT.parent / owner_doc
            doc_text = doc_path.read_text(encoding="utf-8")
            if owner_doc.endswith("-example-coverage.md"):
                assert example_id in doc_text
                if validation_doc.endswith(".md"):
                    assert validation_doc == owner_doc

        if validation_doc.endswith(".md"):
            assert (EXAMPLES_ROOT.parent / validation_doc).is_file()


def test_example_readme_catalog_sections_match_manifests() -> None:
    for manifest_path, manifest in _example_manifests():
        example_id = _required_string(manifest, "id", manifest_path)
        capability = _required_string(manifest, "capability", manifest_path)
        surface = _required_string(manifest, "surface", manifest_path)
        readme = (EXAMPLES_ROOT / capability / "README.md").read_text(encoding="utf-8")

        if surface == "internal_demo":
            assert example_id in _readme_example_ids(readme, "Internal Demos")
            assert example_id not in _readme_example_ids(readme, "CLI Workflows")
            assert example_id not in _readme_example_ids(readme, "Public Python API Workflows")
            continue

        if surface == "cli":
            assert example_id in _readme_example_ids(readme, "CLI Workflows")
        elif surface == "python_api":
            assert example_id in _readme_example_ids(readme, "Public Python API Workflows")
        else:
            raise AssertionError(f"{manifest_path} has unknown surface {surface}")


def test_internal_demos_are_excluded_from_primary_catalogs() -> None:
    top_level = (EXAMPLES_ROOT / "README.md").read_text(encoding="utf-8")
    operations_readme = (EXAMPLES_ROOT / "operations" / "README.md").read_text(
        encoding="utf-8"
    )
    primary_sections = (
        _readme_section(operations_readme, "CLI Workflows"),
        _readme_section(operations_readme, "Public Python API Workflows"),
        _readme_section(operations_readme, "Run"),
    )

    for example_id in INTERNAL_DEMO_EXAMPLES:
        assert example_id not in top_level
        for section in primary_sections:
            assert example_id not in section
        assert _example_script_path(example_id) not in _readme_section(
            operations_readme, "Run"
        )


def test_cli_examples_include_workflow_and_variants_sections() -> None:
    for manifest_path, manifest in _example_manifests():
        if manifest.get("surface") != "cli":
            continue
        readme = (manifest_path.parent / "README.md").read_text(encoding="utf-8")
        assert "## Workflow" in readme
        assert "## Variants" in readme


def test_relevant_cli_examples_include_co_located_variants() -> None:
    for example_id in CO_LOCATED_VARIANT_EXAMPLES:
        readme = _example_readme_path(example_id).read_text(encoding="utf-8")
        assert "--authority-backend co_located_service" in readme
        assert "--authority-profile co_located" in readme


def test_python_api_examples_identify_their_public_surface() -> None:
    for manifest_path, manifest in _example_manifests():
        if manifest.get("surface") != "python_api":
            continue
        readme = (manifest_path.parent / "README.md").read_text(encoding="utf-8")
        assert "## Public Python Surface" in readme


def test_offline_first_import_readme_describes_before_and_after_import() -> None:
    readme = _example_readme_path("execution.offline-first-import").read_text(
        encoding="utf-8"
    )

    assert "Before import, `loom status RUN_URI` is expected to fail" in readme
    assert "post-import authoritative status view" in readme or "post-import" in readme


def _example_manifest_paths() -> list[Path]:
    return sorted(EXAMPLES_ROOT.rglob("example.yaml"))


def _example_manifests() -> list[tuple[Path, dict[str, object]]]:
    return [(path, _load_manifest(path)) for path in _example_manifest_paths()]


def _example_manifest_map() -> dict[str, dict[str, object]]:
    return {
        _required_string(manifest, "id", path): manifest
        for path, manifest in _example_manifests()
    }


def _load_manifest(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError(f"{path} must contain a mapping")
    return cast(dict[str, object], loaded)


def _expected_surface(example_id: str) -> str:
    if example_id in PYTHON_API_EXAMPLES:
        return "python_api"
    if example_id in INTERNAL_DEMO_EXAMPLES:
        return "internal_demo"
    return "cli"


def _example_readme_path(example_id: str) -> Path:
    return EXAMPLES_ROOT.joinpath(*example_id.split("."), "README.md")


def _example_script_path(example_id: str) -> str:
    manifest_path = EXAMPLES_ROOT.joinpath(*example_id.split("."), "example.yaml")
    manifest = _example_manifest_map()[example_id]
    entrypoints = _entrypoint_mappings(
        manifest,
        manifest_path,
    )
    relative_parent = manifest_path.parent.relative_to(EXAMPLES_ROOT.parent)
    return str(relative_parent / _required_string(entrypoints[0], "path", manifest_path))


def _readme_example_ids(text: str, heading: str) -> set[str]:
    section = _readme_section(text, heading)
    values: set[str] = set()
    for line in section.splitlines():
        match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if not match:
            continue
        values.add(match.group(1))
    return values


def _readme_section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    if marker not in text:
        raise AssertionError(f"missing README section {heading!r}")
    _, remainder = text.split(marker, 1)
    next_heading = remainder.find("\n## ")
    if next_heading == -1:
        return remainder
    return remainder[:next_heading]


def _assert_validation_reference(ref: str, manifest_path: Path) -> None:
    if ref.startswith("uv "):
        assert ref == RUNNABLE_SMOKE_VALIDATION_COMMAND
        return
    root = EXAMPLES_ROOT.parent
    path, _, _ = ref.partition("::")
    assert (root / path).is_file(), (
        f"{manifest_path} validation_path {ref!r} must reference an existing repo file"
    )


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
def test_smoke_example_scripts_execute(
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
    if example_id == "execution.offline-first-import":
        assert "offline_source: offline_evidence" in result.stdout
        assert "pre_import_status_code:" in result.stdout
        assert "post_import_status_source: authoritative_service_truth" in result.stdout
        assert "post_import_import_source: offline_evidence" in result.stdout
