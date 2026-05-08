"""End-to-end SLURM dry-run generation through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_dry_run_generates_artifacts_without_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  name: slurm-e2e\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.TextConsumerStage\n"
        "      inputs:\n"
        "        data: build.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n",
        encoding="utf-8",
    )

    for mode in ("slurm-single-job", "slurm-afterok"):
        run_path = tmp_path / "runs" / mode
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    mode,
                    "--dry-run",
                    "--run-uri",
                    path_to_run_uri(run_path),
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

        payload = json.loads(stdout.getvalue())
        result = payload["result"]
        assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
        assert result["mode"] == mode
        assert Path(result["manifest_path"]).is_file()
        assert Path(result["plan_path"]).is_file()
        assert all(Path(item["path"]).is_file() for item in result["script_paths"])
        assert (run_path / "plan.json").is_file()
        assert (run_path / "prepared_run.json").is_file()
        assert any(warning["code"] == "executor.slurm.sbatch" for warning in payload["warnings"])
        assert stderr.getvalue() == ""
