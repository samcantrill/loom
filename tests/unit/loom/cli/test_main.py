"""Unit tests for the CLI entry point."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli import main as cli_main
from loom.cli.errors import CliError
from loom.cli.main import build_parser, main


pytestmark = pytest.mark.unit


def test_build_parser_includes_v2_commands() -> None:
    help_text = build_parser().format_help()

    assert "validate" in help_text
    assert "preflight" in help_text
    assert "plan" in help_text
    assert "run" in help_text


def test_help_and_version_return_zero() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["--help"], stdout=stdout, stderr=stderr) == 0
    assert "usage: loom" in stdout.getvalue()
    assert stderr.getvalue() == ""

    stdout = io.StringIO()
    stderr = io.StringIO()
    assert main(["--version"], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue().startswith("loom ")
    assert stderr.getvalue() == ""


def test_usage_errors_return_two_as_text() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["--bad"], stdout=stdout, stderr=stderr) == 2
    assert stdout.getvalue() == ""
    assert "usage: loom" in stderr.getvalue()


def test_no_command_prints_help_and_returns_zero() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main([], stdout=stdout, stderr=stderr) == 0
    assert "usage: loom" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_command_errors_are_text_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_namespace: object) -> int:
        raise CliError("command failed", code="cli.test_failure")

    monkeypatch.setattr(cli_main, "_dispatch", fail)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["run", "pipeline.yaml"], stdout=stdout, stderr=stderr) == 1
    assert stdout.getvalue() == ""
    assert "command failed" in stderr.getvalue()


def test_command_errors_are_json_when_command_format_is_known(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_namespace: object) -> int:
        raise CliError("command failed", code="cli.test_failure")

    monkeypatch.setattr(cli_main, "_dispatch", fail)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["run", "pipeline.yaml", "--format", "json"], stdout=stdout, stderr=stderr) == 1
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.error.v2"
    assert payload["ok"] is False
    assert payload["warnings"] == []
    assert payload["error"]["type"] == "CliError"
    assert payload["error"]["code"] == "cli.test_failure"


def test_traceback_is_accepted_before_or_after_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_namespace: object) -> int:
        raise CliError("command failed", code="cli.test_failure")

    monkeypatch.setattr(cli_main, "_dispatch", fail)
    before_stdout = io.StringIO()
    before_stderr = io.StringIO()
    after_stdout = io.StringIO()
    after_stderr = io.StringIO()

    assert (
        main(
            ["--traceback", "run", "pipeline.yaml", "--format", "json"],
            stdout=before_stdout,
            stderr=before_stderr,
        )
        == 1
    )
    assert (
        main(
            ["run", "pipeline.yaml", "--format", "json", "--traceback"],
            stdout=after_stdout,
            stderr=after_stderr,
        )
        == 1
    )

    assert "CliError" in before_stderr.getvalue()
    assert "CliError" in after_stderr.getvalue()
    assert "traceback" in json.loads(before_stdout.getvalue())["error"]["details"]
    assert "traceback" in json.loads(after_stdout.getvalue())["error"]["details"]


def test_keyboard_interrupt_returns_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(_namespace: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "_dispatch", interrupt)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", "pipeline.yaml"], stdout=stdout, stderr=stderr) == 130
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "interrupted\n"
