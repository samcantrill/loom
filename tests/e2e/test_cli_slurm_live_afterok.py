"""End-to-end SLURM afterok live authority admission through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import authority_config_to_cli_args, path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_live_afterok_prepares_exact_runtime_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.run as run_command

    store, _ = _prepared_store(tmp_path, {"extract": ()}, authority_backed=True)
    store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
        authority_config=store.authority_config(),
    )
    monkeypatch.setattr(
        run_command, "_create_default_run_store", lambda **_kwargs: store
    )
    # The in-process authority fixture is not a multi-host authority service.
    # Bypass admission/readiness only; exercise real CLI composition, preparation,
    # planning, and fake submission without claiming physical cluster acceptance.
    monkeypatch.setattr(
        run_command, "_require_slurm_live_authority", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        run_command, "_run_preflight_for_slurm_live_submission", lambda **_kwargs: None
    )
    runner = FakeSlurmCommandRunner()
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_uri = path_to_run_uri(tmp_path / "runs" / "private-handoff")
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        main(
            [
                "run",
                str(config_path),
                "--executor",
                "slurm-afterok",
                "--run-uri",
                run_uri,
                "--set",
                "+runtime="
                + json.dumps(
                    {
                        "stage_options": {
                            "extract": {
                                "resources": {
                                    "entries": {"cpu": {"kind": "cpu", "amount": 2}}
                                }
                            }
                        },
                        "resource_policy": {"account_for": "all", "enforce": []},
                    }
                ),
                "--set",
                "runtime.stage_options.extract.resources.entries.cpu.amount=3",
                "--set",
                "runtime.resource_policy.account_for=[]",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    ), stdout.getvalue()
    payload = json.loads(stdout.getvalue())
    private = json.loads(
        Path(payload["result"]["manifest_path"])
        .with_name("execution-resources.json")
        .read_text()
    )
    saved = private["stages"]["extract"]
    assert saved["resources"]["entries"]["cpu"]["amount"] == 3
    assert saved["resource_policy"] == {"account_for": [], "enforce": []}
    assert saved["resource_selection"] == {"account_for": [], "enforce": []}
    assert len(runner.calls) == 3


def test_cli_slurm_live_afterok_rejects_default_authority_before_sbatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.run as run_command
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: "/usr/bin/sbatch" if name == "sbatch" else None,
    )
    runner = FakeSlurmCommandRunner(starting_job_id=200)
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_path = tmp_path / "runs" / "live-afterok"
    run_uri = path_to_run_uri(run_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with LocalAuthorityService.start() as service:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    "slurm-afterok",
                    "--run-uri",
                    run_uri,
                    *authority_config_to_cli_args(service.config()),
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 7
        )

    payload = json.loads(stdout.getvalue())
    _assert_slurm_live_authority_rejected(payload)
    assert stderr.getvalue() == ""
    assert runner.calls == []
    assert not run_path.exists()


def test_cli_slurm_live_afterok_rejects_before_partial_scheduler_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.run as run_command
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: "/usr/bin/sbatch" if name == "sbatch" else None,
    )
    runner = FakeSlurmCommandRunner()
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_path = tmp_path / "runs" / "partial-afterok"
    run_uri = path_to_run_uri(run_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with LocalAuthorityService.start() as service:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    "slurm-afterok",
                    "--run-uri",
                    run_uri,
                    *authority_config_to_cli_args(service.config()),
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 7
        )

    payload = json.loads(stdout.getvalue())
    _assert_slurm_live_authority_rejected(payload)
    assert stderr.getvalue() == ""
    assert runner.calls == []
    assert not run_path.exists()


def _assert_slurm_live_authority_rejected(payload: dict[str, Any]) -> None:
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.run.slurm_live_authority_unsupported"
    admission = payload["error"]["details"]["authority_admission"]
    assert admission["supported"] is False
    assert "slurm_live_worker" in admission["required"]


def _write_afterok_config(path: Path) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: slurm-live-afterok-e2e\n"
        "  stages:\n"
        "    - name: extract\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: transform\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      depends_on: [transform]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )
