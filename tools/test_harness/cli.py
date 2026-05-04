from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_MARKER_EXPR = "not slow and not slurm and not network and not optional_dependency"
CONFIG_EXTRA_MARKER_EXPR = "optional_dependency"
LOCAL_ALL_MARKER_EXPR = "not slurm and not network and not optional_dependency"
SUMMARY_OUTPUT = Path("build/test-summary.md")
UV_CACHE_DIR = "/tmp/uv-cache"


@dataclass(frozen=True)
class Suite:
    name: str
    path: Path
    marker_expr: str = DEFAULT_MARKER_EXPR


@dataclass(frozen=True)
class Result:
    suite: str
    command: str
    status: str
    duration: float
    returncode: int
    output: str


SUITES: dict[str, Suite] = {
    "package": Suite("package", Path("tests/package"), DEFAULT_MARKER_EXPR),
    "unit": Suite("unit", Path("tests/unit"), DEFAULT_MARKER_EXPR),
    "contract": Suite("contract", Path("tests/contracts"), DEFAULT_MARKER_EXPR),
    "integration": Suite("integration", Path("tests/integration"), DEFAULT_MARKER_EXPR),
    "e2e": Suite("e2e", Path("tests/e2e"), DEFAULT_MARKER_EXPR),
    "config-extra": Suite("config-extra", Path("tests"), CONFIG_EXTRA_MARKER_EXPR),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Loom test suites.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one test suite.")
    run_parser.add_argument(
        "suite",
        choices=[*SUITES.keys(), "default", "all"],
        help="Suite to run.",
    )

    summary_parser = subparsers.add_parser(
        "summary", help="Run suites and write a Markdown summary."
    )
    summary_parser.add_argument(
        "--output",
        type=Path,
        default=SUMMARY_OUTPUT,
        help=f"Summary path. Defaults to {SUMMARY_OUTPUT}.",
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_suite(args.suite)
        print_result(result)
        return result.returncode

    if args.command == "summary":
        results = [run_summary_suite(name) for name in SUITES]
        write_summary(args.output, results)
        print(f"Wrote test summary to {args.output}")
        for result in results:
            print(f"{result.suite}: {result.status} ({result.duration:.2f}s)")
        return 1 if any(result.returncode != 0 for result in results) else 0

    raise AssertionError(f"unhandled command: {args.command}")


def run_summary_suite(name: str) -> Result:
    command = [
        "uv",
        "run",
        "--isolated",
        "--locked",
        "--group",
        "dev",
    ]
    if name in {"config-extra", "e2e"}:
        command.extend(["--extra", "config"])
    command.extend(["python", "-m", "tools.test_harness", "run", name])

    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", UV_CACHE_DIR)
    display_command = f"UV_CACHE_DIR={env['UV_CACHE_DIR']} " + " ".join(command)

    start = time.monotonic()
    completed = subprocess.run(
        command,
        check=False,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    duration = time.monotonic() - start
    status = "passed" if completed.returncode == 0 else "failed"
    return Result(
        suite=name,
        command=display_command,
        status=status,
        duration=duration,
        returncode=completed.returncode,
        output=completed.stdout,
    )


def run_suite(name: str) -> Result:
    if name == "default":
        return run_pytest(
            "default",
            ["tests", "-m", DEFAULT_MARKER_EXPR],
            f'uv run pytest tests -m "{DEFAULT_MARKER_EXPR}"',
        )
    if name == "all":
        return run_pytest(
            "all",
            ["tests", "-m", LOCAL_ALL_MARKER_EXPR],
            f'uv run pytest tests -m "{LOCAL_ALL_MARKER_EXPR}"',
        )
    if name == "config-extra":
        suite = SUITES[name]
        return run_pytest(
            suite.name,
            [str(suite.path), "-m", suite.marker_expr],
            f'uv run pytest {suite.path} -m "{suite.marker_expr}"',
        )

    suite = SUITES[name]
    if not has_tests(suite.path):
        return Result(
            suite=suite.name,
            command=f'uv run pytest {suite.path} -m "{suite.marker_expr}"',
            status="not present",
            duration=0.0,
            returncode=0,
            output="No test files are present for this suite yet.",
        )
    return run_pytest(
        suite.name,
        [str(suite.path), "-m", suite.marker_expr],
        f'uv run pytest {suite.path} -m "{suite.marker_expr}"',
    )


def has_tests(path: Path) -> bool:
    if not path.exists():
        return False
    return any(candidate.is_file() for candidate in path.rglob("test*.py"))


def run_pytest(suite: str, args: Sequence[str], command: str) -> Result:
    start = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    duration = time.monotonic() - start
    status = "passed" if completed.returncode == 0 else "failed"
    return Result(
        suite=suite,
        command=command,
        status=status,
        duration=duration,
        returncode=completed.returncode,
        output=completed.stdout,
    )


def print_result(result: Result) -> None:
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    print(f"{result.suite}: {result.status} ({result.duration:.2f}s)")


def write_summary(path: Path, results: Sequence[Result]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Test Suite Summary",
        "",
        "| Suite | Status | Duration | Command |",
        "| --- | --- | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    result.suite,
                    result.status,
                    f"{result.duration:.2f}s",
                    f"`{result.command}`",
                ]
            )
            + " |"
        )

    lines.extend(["", "## Output Tails", ""])
    for result in results:
        lines.extend(
            [
                f"### {result.suite}",
                "",
                "```text",
                tail(result.output),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def tail(output: str, line_count: int = 20) -> str:
    stripped = output.strip()
    if not stripped:
        return "(no output)"
    lines = stripped.splitlines()
    return "\n".join(lines[-line_count:])
