"""Package-level import-boundary tests."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_import_does_not_import_deferred_modules() -> None:
    script = dedent(
        """
        import sys

        import loom

        for forbidden in ("loom.config", "loom.pipeline", "loom.cli"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported eagerly")
        for forbidden in ("omegaconf", "yaml", "pydantic"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported eagerly")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_serialization_does_not_import_io() -> None:
    script = dedent(
        """
        import sys

        import loom.serialization

        if "loom.io" in sys.modules:
            raise SystemExit("loom.io imported through serialization")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_io_does_not_import_config_or_pipeline() -> None:
    script = dedent(
        """
        import sys

        import loom.io

        for forbidden in ("loom.config", "loom.pipeline", "loom.cli"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.io")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_config_does_not_import_pipeline_or_execution() -> None:
    script = dedent(
        """
        import sys

        import loom.config

        for forbidden in ("loom.pipeline", "loom.pipeline.execution", "loom.pipeline.executors", "loom.pipeline.stores", "loom.cli"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.config")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_pipeline_does_not_import_forbidden_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline

        for forbidden in ("loom.config", "loom.cli", "loom.pipeline.execution", "loom.pipeline.executors"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_stores_does_not_import_config_or_cli_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.stores

        for forbidden in ("loom.config", "loom.pipeline.execution", "loom.pipeline.executors", "loom.cli", "project"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.stores")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_execution_does_not_import_config_stores_cli() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.execution

        for forbidden in ("loom.config", "loom.cli", "subprocess"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.execution")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_executors_does_not_import_project_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors

        for forbidden in ("loom.config", "loom.pipeline.planning", "loom.cli", "project"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.executors")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_cli_remains_import_safe() -> None:
    script = dedent(
        """
        import sys

        import loom.cli

        for forbidden in ("loom.pipeline", "loom.pipeline.stores", "loom.pipeline.executors", "loom.config", "yaml", "omegaconf", "pydantic"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
