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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_config_symbol_access_without_optional_dependencies_mentions_config_extra() -> (
    None
):
    script = dedent(
        """
        import importlib
        import loom.config

        original_import_module = importlib.import_module

        def fake_import_module(name, package=None):
            if name in {"yaml", "omegaconf", "pydantic"}:
                raise ModuleNotFoundError(f\"No module named {name!r}\")
            return original_import_module(name, package=package)

        importlib.import_module = fake_import_module
        try:
            try:
                _ = loom.config.compose_config
            except Exception as exc:
                message = str(exc)
            else:
                raise SystemExit(\"compose_config unexpectedly imported without optional deps\")
            try:
                _ = loom.config.compose_config_with_catalog
            except Exception as exc:
                message = str(exc)
            else:
                raise SystemExit(\"compose_config_with_catalog unexpectedly imported without optional deps\")
            if \"loom[config]\" not in message:
                raise SystemExit(f\"Expected loom[config] in error message: {message!r}\")
        finally:
            importlib.import_module = original_import_module

        print(\"ok\")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_diagnostics_root_is_lightweight() -> None:
    script = dedent(
        """
        import sys

        import loom.diagnostics

        for forbidden in (
            "loom.cli",
            "loom.config",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.diagnostics")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_lower_layers_do_not_import_diagnostics() -> None:
    script = dedent(
        """
        import sys

        import loom.config
        import loom.pipeline
        import loom.pipeline.stores
        import loom.pipeline.executors
        import loom.io.codecs

        if "loom.diagnostics" in sys.modules:
            raise SystemExit("lower layers imported loom.diagnostics")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_stage_factory_does_not_import_forbidden_modules() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.stage_factory

        for forbidden in ("loom.config", "loom.cli", "loom.pipeline.execution", "loom.pipeline.executors", "project"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.stage_factory")
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_runtime_resource_modules_do_not_import_forbidden_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.resources
        import loom.pipeline.runtime
        import loom.pipeline.events
        import loom.pipeline.locks

        for forbidden in ("loom.config", "loom.cli", "loom.pipeline.execution", "loom.pipeline.executors", "project"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through runtime/resource/event/lock modules")
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_runtime_facade_public_imports_are_stable_and_lightweight() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.runtime as runtime
        from loom.pipeline.runtime import RuntimeKind, RuntimeRequest, parse_runtime_request
        from loom.pipeline import RuntimeKind as PipelineRuntimeKind
        from loom.pipeline import RuntimeRequest as PipelineRuntimeRequest
        from loom.pipeline import parse_runtime_request as pipeline_parse_runtime_request

        assert runtime.RuntimeKind is RuntimeKind
        assert runtime.RuntimeRequest is RuntimeRequest
        assert runtime.parse_runtime_request is parse_runtime_request
        assert PipelineRuntimeKind is RuntimeKind
        assert PipelineRuntimeRequest is RuntimeRequest
        assert pipeline_parse_runtime_request is parse_runtime_request
        assert set(runtime.__all__) == {
            "RUNTIME_SCHEMA_VERSION",
            "RuntimeKind",
            "RuntimeRequest",
            "parse_runtime_request",
        }

        for forbidden in (
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.plugins",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.runtime")
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
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

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_cli_help_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        from loom.cli.main import main

        exit_code = main(["--help"])
        if exit_code != 0:
            raise SystemExit(f"help returned {exit_code}")

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through CLI help")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "usage: loom" in result.stdout


def test_import_cli_validate_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.validate

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.validate")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_cli_preflight_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.preflight

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "loom.diagnostics.preflight",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.preflight")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_cli_plan_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.plan

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.plan")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_cli_run_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.run

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.run")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_cli_diagnostics_commands_remain_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.status
        import loom.cli.logs
        import loom.cli.artifacts

        for forbidden in (
            "loom.config",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.executors",
            "loom.diagnostics.inspection",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through diagnostics CLI")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_config_artifacts_does_not_import_forbidden_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.config.artifacts

        for forbidden in (
            "loom.pipeline",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.cli",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.config.artifacts")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_pipeline_constructs_from_plain_data_without_config_import() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline import parse_pipeline_config

        if "loom.config" in sys.modules:
            raise SystemExit("loom.config was imported before pipeline construction")
        if "yaml" in sys.modules or "omegaconf" in sys.modules or "pydantic" in sys.modules:
            raise SystemExit("pipeline construction should not import config-only dependencies")

        parse_pipeline_config(
            {
                "name": "demo",
                "metadata": {"mode": "boundary"},
                "schema_version": 1,
                "stages": [
                    {
                        "name": "prepare",
                        "factory": {
                            "_target_": "tests.support.pipeline:noop",
                            "init": {"seed": 1},
                        },
                        "outputs": {"model": {"artifact_type": "json"}},
                    }
                ],
            }
        )
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_pipeline_runner_executes_direct_spec_without_config_import() -> None:
    script = dedent(
        """
        import sys
        from tempfile import TemporaryDirectory

        def assert_forbidden_absent(phase):
            for forbidden in (
                "loom.config",
                "loom.cli",
                "project",
                "yaml",
                "omegaconf",
                "pydantic",
            ):
                if forbidden in sys.modules:
                    raise SystemExit(f"{forbidden} was imported {phase}")

        from loom.pipeline import PipelineRunner, PipelineSpec, RunRequest
        from loom.pipeline.status import RunStatus
        from loom.pipeline.stores import LocalRunStore, path_to_run_uri

        assert_forbidden_absent("before direct pipeline run")

        spec = PipelineSpec.from_config(
            {
                "name": "direct-boundary",
                "stages": [
                    {
                        "name": "build",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage",
                        },
                        "config": {"value": 42},
                        "outputs": {"data": {"artifact_type": "json"}},
                    }
                ],
            }
        )
        with TemporaryDirectory() as tmpdir:
            run_store = LocalRunStore(tmpdir)
            run_uri = path_to_run_uri(f"{tmpdir}/run1")
            result = PipelineRunner(run_store=run_store).run(
                RunRequest(pipeline=spec, run_uri=run_uri)
            )
            if result.status is not RunStatus.SUCCEEDED:
                raise SystemExit(f"run failed with status {result.status!r}")
            if set(run_store.read_artifact_index(run_uri)) != {"build.data"}:
                raise SystemExit("direct run did not write expected artifact index")

        assert_forbidden_absent("during direct pipeline run")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
