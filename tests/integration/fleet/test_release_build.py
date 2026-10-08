"""Real wheel construction and isolated offline installation of a finite project."""

import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from loom.cli.main import main
from loom.fleet.release_build import build_release
from loom.fleet.releases import verify_release
from loom.queue.errors import QueueConfigError

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def run(*command, cwd):
    return subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def project(root, *, broken=False):
    root.mkdir()
    package = root / "src/loom/fleet"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "_host.py").write_text(
        "import missing_service_dependency\n"
        if broken
        else "SOURCE_MARKER = 'installed-fixture'\n"
    )
    (root / "pyproject.toml").write_text("""[project]
name = "loom"
version = "0.1.0"
requires-python = ">=3.12"
[project.optional-dependencies]
fleet = []
[build-system]
requires = ["uv_build>=0.11.8,<0.12.0"]
build-backend = "uv_build"
""")
    run("uv", "lock", "--python", sys.executable, cwd=root)
    run("git", "init", "-q", cwd=root)
    run("git", "add", ".", cwd=root)
    run(
        "git",
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "source",
        cwd=root,
    )
    return root


def test_build_publishes_verified_bundle_and_preserves_source(tmp_path):
    source = project(tmp_path / "source")
    output = tmp_path / "release"
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        [
            "fleet",
            "build-release",
            "--source",
            str(source),
            "--output",
            str(output),
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert result["source"]["commit"] == run("git", "rev-parse", "HEAD", cwd=source)
    assert receipt["offline_installation"] == "passed"
    assert verify_release(Path(result["release"])) == receipt["release"]
    assert run("git", "status", "--porcelain", cwd=source) == ""
    assert not list(output.glob(".verify-*"))
    wheel = next((output / "wheels").glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert b"installed-fixture" in archive.read("loom/fleet/_host.py")
    wheel.write_bytes(wheel.read_bytes() + b"changed")
    with pytest.raises(QueueConfigError, match="changed"):
        verify_release(Path(result["release"]))


@pytest.mark.parametrize("case", ["dirty", "existing"])
def test_build_refuses_dirty_source_or_existing_destination_before_writes(
    tmp_path, case
):
    source = project(tmp_path / "source")
    output = tmp_path / "release"
    if case == "dirty":
        (source / "uncommitted.py").write_text("unpublished = True\n")
    else:
        output.mkdir()
        (output / "retained").write_text("original")
    with pytest.raises(QueueConfigError, match="clean|already exists"):
        build_release(source, output)
    if case == "dirty":
        assert not output.exists()
    else:
        assert {p.name for p in output.iterdir()} == {"retained"}
        assert (output / "retained").read_text() == "original"


def test_failed_installed_import_never_publishes_a_release(tmp_path):
    source = project(tmp_path / "source", broken=True)
    output = tmp_path / "release"
    with pytest.raises(QueueConfigError, match="protected log"):
        build_release(source, output)
    assert "missing_service_dependency" in (output / "build.log").read_text()
    assert not (output / "release.json").exists()
    assert not (output / "build-receipt.json").exists()
