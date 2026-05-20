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
        for forbidden in ("omegaconf", "yaml", "pydantic", "fastapi", "starlette"):
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


def test_import_config_current_state_boundary_inventory_is_present_and_forward_compatible() -> None:
    script = dedent(
        """
        import sys

        import loom.config

        public_symbols = set(dir(loom.config))

        if "compose_config" not in public_symbols:
            raise SystemExit("compose_config missing from loom.config public API")
        if "inspect_config_composition" not in public_symbols:
            raise SystemExit("inspect_config_composition missing from loom.config public API")
        if "RecipeCatalog" not in public_symbols:
            raise SystemExit("RecipeCatalog missing from loom.config public API")
        if "weave" in sys.modules:
            raise SystemExit("weave imported before Phase 4 boundary shift")
        for forbidden in (
            "loom.pipeline",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.cli",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through current-state loom.config boundary")
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

        for forbidden in ("loom.config", "loom.cli", "loom.pipeline.execution", "loom.pipeline.executors", "fastapi", "starlette"):
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


def test_import_docker_command_contracts_do_not_import_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.docker as docker

        assert docker.DockerRunCommand
        for forbidden in (
            "docker",
            "subprocess",
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through Docker commands")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_apptainer_command_contracts_do_not_import_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.apptainer as apptainer

        assert apptainer.ApptainerExecCommand
        for forbidden in (
            "subprocess",
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through Apptainer commands")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_authority_root_does_not_import_fastapi() -> None:
    script = dedent(
        """
        import sys

        import loom.authority

        for forbidden in (
            "fastapi",
            "starlette",
            "pydantic",
            "sqlite3",
            "loom.authority._repository",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through loom.authority")
        if "loom.pipeline" in sys.modules:
            raise SystemExit("loom.pipeline imported through loom.authority")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_authority_root_does_not_export_private_repository() -> None:
    import loom.authority as authority

    assert not hasattr(authority, "AuthorityRepository")
    assert not hasattr(authority, "initialize_authority_repository")


def test_import_queue_root_is_lightweight() -> None:
    script = dedent(
        """
        import sys

        import loom.queue

        for forbidden in (
            "sqlite3",
            "loom.config",
            "loom.cli",
            "loom.authority",
            "loom.authority._repository",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.queue")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_queue_control_modules_do_not_import_authority_or_config() -> None:
    script = dedent(
        """
        import sys

        import loom.queue.client
        import loom.queue.config
        import loom.queue.controller
        import loom.queue.service

        for forbidden in (
            "loom.config",
            "loom.authority",
            "loom.authority._repository",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "yaml",
            "omegaconf",
            "pydantic",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through queue control modules")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_artifacts_does_not_import_store_plugins_or_services() -> None:
    script = dedent(
        """
        import sys

        import loom.artifacts

        for forbidden in (
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.plugins",
            "loom.diagnostics",
            "loom.runs",
            "loom.cli",
            "loom.config",
            "fastapi",
            "starlette",
            "pydantic",
            "yaml",
            "omegaconf",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.artifacts")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_stage_16_public_defaults_do_not_import_plugins_or_optional_sdks() -> None:
    script = dedent(
        """
        import sys

        import loom.artifacts
        import loom.pipeline.stores
        import loom.runs
        from loom.pipeline.stores import (
            ArtifactStoreBackendOperation,
            ArtifactStorePayloadOperationRequest,
            ArtifactStorePayloadOperationResult,
            LocalMaterializationPolicy,
        )
        from loom.runs import RunBundleExportOptions

        request = ArtifactStorePayloadOperationRequest(
            operation=ArtifactStoreBackendOperation.DOWNLOAD,
            source_uri="s3://example-bucket/artifact.bin",
            target_uri="file:///tmp/artifact.bin",
        )
        result = ArtifactStorePayloadOperationResult.not_implemented(
            request,
            backend_kind="s3",
        )
        assert result.result.status.value == "not_implemented"
        assert LocalMaterializationPolicy.COPY.value == "copy"
        assert RunBundleExportOptions(materialize_payloads=True).materialize_payloads

        for forbidden in (
            "loom.plugins",
            "mlflow",
            "boto3",
            "botocore",
            "s3fs",
            "google.cloud",
            "azure",
            "dvc",
            "wandb",
            "requests",
            "httpx",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported by Stage 16 public defaults")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_stage_16_default_preflight_avoids_backend_discovery_and_sdks() -> None:
    script = dedent(
        """
        import sys

        import loom.diagnostics.preflight as preflight
        from loom.diagnostics import PreflightCheckStatus, PreflightRequest, run_preflight

        def fail_provider():
            raise AssertionError("default artifact backend preflight discovered plugins")

        preflight._plugin_entry_point_provider = fail_provider
        result = run_preflight(
            PreflightRequest(config_path="missing.yaml", groups=("artifacts",))
        )
        by_id = {check.check_id: check for check in result.checks}
        assert by_id["artifact_backends.registry"].status is PreflightCheckStatus.SKIP
        assert by_id["artifact_backends.handlers"].details["reason"] == "no_artifact_backend_targets"
        assert by_id["artifact_backends.materialization"].status is PreflightCheckStatus.SKIP
        assert by_id["artifact_backends.materialization"].details["reason"] == "no_artifact_backend_targets"

        for forbidden in (
            "loom.plugins",
            "mlflow",
            "boto3",
            "botocore",
            "s3fs",
            "google.cloud",
            "azure",
            "dvc",
            "wandb",
            "requests",
            "httpx",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported by default backend preflight")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_default_executor_preflight_does_not_import_docker_modules() -> None:
    script = dedent(
        """
        import sys
        from types import ModuleType

        from loom.diagnostics import PreflightCheckStatus, PreflightRequest, run_preflight

        class FakeComposedConfig:
            resolved = {"pipeline": {}}
            source_artifacts = ()

        config_package = ModuleType("loom.config")
        config_api = ModuleType("loom.config.api")
        config_api.compose_config = lambda *_args, **_kwargs: FakeComposedConfig()
        config_package.api = config_api
        sys.modules["loom.config"] = config_package
        sys.modules["loom.config.api"] = config_api

        result = run_preflight(
            PreflightRequest(
                config_path="pipeline.yaml",
                groups=("executor",),
                runtime_options={"executor": "local"},
            )
        )
        by_id = {check.check_id: check for check in result.checks}
        assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS

        for forbidden in (
            "loom.pipeline.executors.containers",
            "loom.pipeline.executors.docker",
            "loom.pipeline.executors.docker.commands",
            "loom.pipeline.executors.docker.executor",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported by default executor preflight")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_stage_15_bundle_inspect_preserves_metadata_without_backend_imports() -> None:
    script = dedent(
        """
        import io
        import sys
        import tarfile
        import tempfile
        from pathlib import Path

        from loom.runs import (
            RUN_BUNDLE_MANIFEST_MEMBER,
            RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY,
            PortableRunSourceIdentity,
            PortableRunTargetIdentityPolicy,
            RunBundleManifest,
            inspect_run_bundle,
        )
        from loom.serialization import stable_json_bytes

        manifest = RunBundleManifest(
            run_uri="file:///runs/source/run-1",
            source_identity=PortableRunSourceIdentity(
                source_kind="local",
                run_uri="file:///runs/source/run-1",
            ),
            target_identity=PortableRunTargetIdentityPolicy(),
            extensions={
                RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY: {
                    "schema_version": 1,
                    "artifacts": [
                        {
                            "artifact_name": "model",
                            "artifact_id": "external-model",
                            "uri": "s3://secret-bucket/model",
                            "artifact_type": "model",
                            "codec_key": "json.v1",
                            "checksum": None,
                            "fingerprint": None,
                            "producer_stage": "train",
                            "summaries": {
                                "external_artifact": {
                                    "schema_version": 1,
                                    "artifact_id": "external-model",
                                    "uri": "s3://secret-bucket/model",
                                    "artifact_type": "model",
                                    "codec_key": "json.v1",
                                    "artifact_schema_version": 1,
                                    "store": {
                                        "schema_version": 1,
                                        "kind": "object-store",
                                        "key": None,
                                        "uri": None,
                                        "display_uri": "s3://redacted/model",
                                        "details": {},
                                    },
                                    "location": None,
                                    "checksum": None,
                                    "fingerprint": None,
                                    "immutability": "declared",
                                    "metadata": {},
                                    "details": {},
                                }
                            },
                        }
                    ],
                }
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle.tar"
            manifest_bytes = stable_json_bytes(manifest.to_dict())
            with tarfile.open(bundle, "w") as archive:
                info = tarfile.TarInfo(RUN_BUNDLE_MANIFEST_MEMBER)
                info.size = len(manifest_bytes)
                archive.addfile(info, io.BytesIO(manifest_bytes))

            inspection = inspect_run_bundle(bundle)

        assert RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY in inspection.extensions
        assert inspection.included_payload_count == 0
        for forbidden in (
            "loom.plugins",
            "mlflow",
            "boto3",
            "botocore",
            "s3fs",
            "google.cloud",
            "azure",
            "dvc",
            "wandb",
            "requests",
            "httpx",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported by bundle inspect")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_queue_local_adapter_avoids_private_authority_and_scheduler_modules() -> (
    None
):
    script = dedent(
        """
        import sys

        import loom.queue.local
        import loom.queue.resources

        for forbidden in (
            "loom.authority",
            "loom.authority._repository",
            "loom.pipeline.executors",
            "loom.pipeline.executors.slurm",
            "loom.cli",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through queue local modules")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_queue_slurm_adapter_uses_public_scheduler_boundary_only() -> None:
    script = dedent(
        """
        import sys

        import loom.queue.slurm

        if "loom.pipeline.executors.slurm.commands" not in sys.modules:
            raise SystemExit("SLURM command boundary was not imported")
        for forbidden in (
            "loom.authority",
            "loom.authority._repository",
            "loom.cli",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through queue SLURM adapter")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_queue_preflight_avoids_private_authority_and_scheduler_modules() -> (
    None
):
    script = dedent(
        """
        import sys

        import loom.queue.preflight

        for forbidden in (
            "loom.authority._repository",
            "loom.cli",
            "loom.pipeline.executors.slurm",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through queue preflight")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_queue_cli_is_presentation_only_until_handlers_run() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.queue

        for forbidden in (
            "loom.authority._repository",
            "loom.pipeline.execution",
            "loom.pipeline.executors.slurm",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through queue CLI import")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_runtime_facade_does_not_import_forbidden_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.runtime

        for forbidden in (
            "loom.config",
            "loom.cli",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
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


def test_import_event_sinks_does_not_import_forbidden_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.event_sinks

        for forbidden in (
            "loom.config",
            "loom.cli",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.plugins",
            "loom.diagnostics",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
            "fastapi",
            "starlette",
            "sqlite3",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.event_sinks")
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

        for forbidden in ("loom.config", "loom.pipeline.execution", "loom.pipeline.executors", "loom.runs", "loom.cli", "project"):
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


def test_import_sweep_contract_package_is_lightweight() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.sweep

        for forbidden in (
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.queue",
            "loom.cli",
            "loom.authority",
            "loom.authority._repository",
            "loom.project",
            "optuna",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.sweep")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_authority_client_does_not_import_server_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.stores.authority_client

        for forbidden in (
            "fastapi",
            "starlette",
            "loom.authority._repository",
            "loom.authority.routes.mutations",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through authority_client")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_authority_registry_does_not_import_server_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.stores.authority_registry

        for forbidden in (
            "fastapi",
            "starlette",
            "loom.authority._repository",
            "loom.authority.routes.mutations",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through authority_registry")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_authority_factory_does_not_import_server_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.stores.authority_factory

        for forbidden in (
            "fastapi",
            "starlette",
            "loom.authority._repository",
            "loom.authority.routes.mutations",
            "loom.authority.supervisor",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through authority_factory")
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


def test_import_backend_cli_is_presentation_only() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.backend

        for forbidden in (
            "loom.config",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores.sqlite_authority",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.backend")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_authority_cli_does_not_import_server_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.authority

        for forbidden in (
            "fastapi",
            "starlette",
            "uvicorn",
            "loom.authority._repository",
            "loom.authority.supervisor",
            "loom.authority._server",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.authority")
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


def test_import_runs_does_not_import_diagnostics() -> None:
    script = dedent(
        """
        import sys

        import loom.runs

        if "loom.diagnostics" in sys.modules:
            raise SystemExit("loom.runs imported loom.diagnostics")
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
            "DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY",
            "CONTINUE_INDEPENDENT_FAILURE_POLICY",
            "DEFAULT_FAILURE_POLICY",
            "DEFAULT_MAX_PARALLEL_STAGES",
            "RUNTIME_CONFIG_SECTION",
            "RUNTIME_METADATA_SCHEMA_VERSION",
            "RUNTIME_PROFILES_CONFIG_SECTION",
            "RUN_OPTIONS_SCHEMA_VERSION",
            "RUNTIME_SCHEMA_VERSION",
            "CapabilityDiagnostic",
            "CapabilitySeverity",
            "CapabilityValidationResult",
            "ExecutionOptions",
            "ExecutorDescriptor",
            "ExecutorDescriptorRegistry",
            "ParallelExecutionOptions",
            "RunEnvironmentRequest",
            "RunOptions",
            "ResolvedStageRuntimeOptions",
            "ResourceCapability",
            "ResourceEnforcementExpectation",
            "ResourceSupportLevel",
            "RuntimeConfigSections",
            "RuntimeMetadata",
            "RuntimeProfile",
            "RuntimeProfileCollection",
            "RuntimeKind",
            "RuntimeRequest",
            "StageEnvironmentRequest",
            "StageRuntimeOptions",
            "FailureClassification",
            "ReliabilityPolicy",
            "ReliabilityStatusDetail",
            "RetryDecisionRecord",
            "RetryPolicy",
            "RetryEvaluator",
            "StageAttemptTransaction",
            "StageAttemptTransactionState",
            "TimeoutAdapter",
            "TimeoutOutcome",
            "TimeoutOutcomeRecord",
            "TimeoutPolicy",
            "TimeoutSupportLevel",
            "build_runtime_metadata",
            "merge_config_run_options",
            "merge_run_options",
            "parallel_execution_options",
            "parse_run_options",
            "parse_runtime_config_sections",
            "parse_runtime_profile",
            "parse_runtime_profiles",
            "parse_runtime_request",
            "resolve_executor_descriptor",
            "resolve_run_runtime",
            "select_runtime_profile",
            "validate_executor_capabilities",
            "validate_stage_runtime_options",
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


def test_import_container_records_does_not_import_execution_or_docker_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.containers

        for forbidden in (
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "loom.pipeline.executors.docker",
            "docker",
            "subprocess",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through container records")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_slurm_models_does_not_import_scheduler_cli_or_config_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.slurm

        for forbidden in (
            "loom.cli",
            "loom.config",
            "project",
            "slurm",
            "pyslurm",
            "subprocess",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.executors.slurm")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_slurm_dry_run_modules_does_not_import_forbidden_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.executors.slurm.artifacts
        import loom.pipeline.executors.slurm.planning
        import loom.pipeline.executors.slurm.rendering

        for forbidden in (
            "loom.cli",
            "loom.config",
            "project",
            "slurm",
            "pyslurm",
            "subprocess",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through SLURM dry-run modules")
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


def test_import_cli_sweep_remains_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.sweep

        for forbidden in (
            "loom.config",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.queue",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
            "optuna",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.cli.sweep")
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
        import loom.cli.cancel
        import loom.cli.runs

        for forbidden in (
            "loom.config",
            "loom.runs",
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


def test_import_cleanup_cli_commands_remain_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom.cli.clean
        import loom.cli.cleanup_options
        import loom.cli.gc

        for forbidden in (
            "loom.config",
            "loom.runs",
            "loom.pipeline",
            "loom.pipeline.stores",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "project",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through cleanup CLI")
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
        from loom.pipeline.execution import create_authority_backed_serial_run_store
        from loom.pipeline.status import RunStatus
        from loom.pipeline.stores import path_to_run_uri
        from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

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
            run_store = create_authority_backed_serial_run_store(
                tmpdir,
                authority_store=SQLitePerRunAuthorityStore(),
            )
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


def test_import_config_does_not_import_plugins() -> None:
    script = dedent(
        """
        import sys

        import loom.config

        if "loom.plugins" in sys.modules:
            raise SystemExit("loom.plugins was imported through loom.config")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_pipeline_does_not_import_plugins() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline

        if "loom.plugins" in sys.modules:
            raise SystemExit("loom.plugins was imported through loom.pipeline")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_root_does_not_import_plugins() -> None:
    script = dedent(
        """
        import sys

        import loom

        if "loom.plugins" in sys.modules:
            raise SystemExit("loom.plugins was imported through root package import")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_operations_is_import_light_and_no_forbidden_layers() -> None:
    script = dedent(
        """
        import sys

        import loom.operations

        for forbidden in (
            "loom.runs",
            "loom.diagnostics",
            "loom.pipeline",
            "loom.cli",
            "loom.plugins",
            "loom.authority",
            "yaml",
            "omegaconf",
            "pydantic",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.operations")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_weave_does_not_import_loom() -> None:
    script = dedent(
        """
        import pathlib
        import sys

        sys.path.insert(0, str(pathlib.Path.cwd() / "packages" / "weave" / "src"))
        import weave

        if "loom" in sys.modules:
            raise SystemExit("loom was imported when loading weave")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_weave_public_config_symbols_do_not_import_loom() -> None:
    script = dedent(
        """
        import pathlib
        import sys

        repo = pathlib.Path.cwd()
        sys.path.insert(0, str(repo / "packages" / "weave" / "src"))

        from weave import (
            RecipeCatalog,
            check_config_targets,
            compose_config,
            inspect_config_composition,
            instantiate,
        )

        catalog = RecipeCatalog()
        assert catalog.names() == ()
        assert callable(compose_config)
        assert callable(inspect_config_composition)

        value = {"item": {"_target_": "builtins:dict", "value": 1}}
        assert instantiate(value) == {"item": {"value": 1}}
        assert check_config_targets(value).checked_paths == ("$.item",)

        for forbidden in [name for name in sys.modules if name == "loom" or name.startswith("loom.")]:
            raise SystemExit(f"weave public config symbols imported {forbidden}")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_core_runtime_imports_do_not_depend_on_weave() -> None:
    script = dedent(
        """
        import sys

        import loom
        import loom.config
        import loom.pipeline
        import loom.serialization
        import loom.plugins
        import loom.queue
        import loom.runs

        if "weave" in sys.modules:
            raise SystemExit("weave was imported before phase 4 cutover")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
