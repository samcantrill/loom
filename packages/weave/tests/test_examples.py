"""Executable package-local examples for `weave`."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.package

WEAVE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = WEAVE_ROOT / "examples"

EXAMPLE_SCRIPTS = (
    EXAMPLES_ROOT / "config-composition" / "basic" / "compose_basic.py",
    EXAMPLES_ROOT / "config-composition" / "includes" / "compose_includes.py",
    EXAMPLES_ROOT
    / "config-composition"
    / "replacement-overlays"
    / "replacement_overlays.py",
    EXAMPLES_ROOT / "config-composition" / "errors" / "show_errors.py",
    EXAMPLES_ROOT / "recipes" / "compose_config.py",
    EXAMPLES_ROOT / "artifact-safety" / "artifact_safety.py",
    EXAMPLES_ROOT / "target-instantiation" / "instantiate_targets.py",
)
PACKAGE_VALIDATION_PATH = (
    "packages/weave/tests/test_examples.py::test_weave_example_script_runs"
)
PACKAGE_VALIDATION_COMMAND = "make test-weave-examples"


@pytest.mark.parametrize("script", EXAMPLE_SCRIPTS, ids=lambda path: str(path.relative_to(EXAMPLES_ROOT)))
def test_weave_example_script_runs(script: Path) -> None:
    env = dict(os.environ)
    pythonpath = [str(WEAVE_ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parent,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_weave_example_manifests_point_at_package_validation() -> None:
    manifests = sorted(EXAMPLES_ROOT.rglob("example.yaml"))

    assert manifests
    for manifest_path in manifests:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(manifest, dict)
        example_id = ".".join(manifest_path.parent.relative_to(EXAMPLES_ROOT).parts)
        assert manifest["id"] == example_id
        assert manifest["validation_path"] == PACKAGE_VALIDATION_PATH
        assert manifest["validation_command"] == PACKAGE_VALIDATION_COMMAND
        assert "packages/weave/examples/README.md" in manifest["owner_docs"]
        for entrypoint in manifest["entrypoints"]:
            assert (manifest_path.parent / entrypoint["path"]).is_file()
