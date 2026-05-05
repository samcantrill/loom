from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree


DEFAULT_MARKER_EXPR = (
    "not slow and not slurm and not network and not optional_dependency"
)
CONFIG_EXTRA_MARKER_EXPR = "optional_dependency"
LOCAL_ALL_MARKER_EXPR = "not slurm and not network and not optional_dependency"
SUMMARY_OUTPUT = Path("build/test-summary.md")
SUMMARY_ARTIFACT_DIR = Path("build/test-summary")
SOURCE_COVERAGE_ROOT = "src/loom"
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


@dataclass(frozen=True)
class GroupRule:
    name: str
    class_prefixes: tuple[str, ...]
    coverage_paths: tuple[str, ...] = ()


@dataclass
class Counts:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    deselected: int = 0
    duration: float = 0.0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def status(self) -> str:
        if self.failed or self.errors:
            return "failed"
        if self.total:
            return "passed"
        return "not present"

    def add(self, other: Counts) -> None:
        self.passed += other.passed
        self.failed += other.failed
        self.errors += other.errors
        self.skipped += other.skipped
        self.deselected += other.deselected
        self.duration += other.duration


@dataclass(frozen=True)
class CoverageMetric:
    covered_lines: int
    statements: int

    @property
    def percent(self) -> float | None:
        if self.statements == 0:
            return None
        return (self.covered_lines / self.statements) * 100


@dataclass(frozen=True)
class SuiteSummary:
    suite: str
    command: str
    status: str
    duration: float
    returncode: int
    output: str
    counts: Counts
    groups: Mapping[str, Counts]
    coverage: Mapping[str, CoverageMetric]


SUITES: dict[str, Suite] = {
    "package": Suite("package", Path("tests/package"), DEFAULT_MARKER_EXPR),
    "unit": Suite("unit", Path("tests/unit"), DEFAULT_MARKER_EXPR),
    "contract": Suite("contract", Path("tests/contracts"), DEFAULT_MARKER_EXPR),
    "integration": Suite("integration", Path("tests/integration"), DEFAULT_MARKER_EXPR),
    "e2e": Suite("e2e", Path("tests/e2e"), DEFAULT_MARKER_EXPR),
    "config-extra": Suite("config-extra", Path("tests"), CONFIG_EXTRA_MARKER_EXPR),
}

GROUP_RULES: dict[str, tuple[GroupRule, ...]] = {
    "package": (
        GroupRule(
            "imports-boundaries",
            ("tests.package.test_import", "tests.package.test_import_boundaries"),
        ),
        GroupRule("public-api", ("tests.package.test_public_api",)),
        GroupRule(
            "config-api", ("tests.package.test_config_api",), ("src/loom/config/",)
        ),
        GroupRule(
            "pipeline-apis", ("tests.package.test_pipeline",), ("src/loom/pipeline/",)
        ),
    ),
    "unit": (
        GroupRule("config", ("tests.unit.loom.config",), ("src/loom/config/",)),
        GroupRule("io", ("tests.unit.loom.io",), ("src/loom/io/",)),
        GroupRule(
            "pipeline-execution",
            ("tests.unit.loom.pipeline.execution",),
            ("src/loom/pipeline/execution/",),
        ),
        GroupRule(
            "pipeline-executors",
            ("tests.unit.loom.pipeline.executors",),
            ("src/loom/pipeline/executors/",),
        ),
        GroupRule(
            "pipeline-graph",
            ("tests.unit.loom.pipeline.graph",),
            ("src/loom/pipeline/graph/",),
        ),
        GroupRule(
            "pipeline-planning",
            ("tests.unit.loom.pipeline.planning",),
            ("src/loom/pipeline/planning/",),
        ),
        GroupRule(
            "pipeline-stores",
            ("tests.unit.loom.pipeline.stores",),
            ("src/loom/pipeline/stores/",),
        ),
        GroupRule(
            "pipeline-core",
            ("tests.unit.loom.pipeline.test_",),
            (
                "src/loom/pipeline/__init__.py",
                "src/loom/pipeline/context.py",
                "src/loom/pipeline/errors.py",
                "src/loom/pipeline/events.py",
                "src/loom/pipeline/locks.py",
                "src/loom/pipeline/resources.py",
                "src/loom/pipeline/runtime.py",
                "src/loom/pipeline/specs.py",
                "src/loom/pipeline/stage.py",
                "src/loom/pipeline/stage_factory.py",
                "src/loom/pipeline/status.py",
            ),
        ),
        GroupRule(
            "serialization",
            ("tests.unit.loom.serialization",),
            ("src/loom/serialization/",),
        ),
        GroupRule("test-harness", ("tests.unit.tools",)),
        GroupRule(
            "core",
            ("tests.unit.loom.test_",),
            (
                "src/loom/__init__.py",
                "src/loom/artifacts.py",
                "src/loom/errors.py",
                "src/loom/fingerprints.py",
                "src/loom/ids.py",
                "src/loom/protocols.py",
                "src/loom/refs.py",
                "src/loom/timestamps.py",
                "src/loom/provenance/",
                "src/loom/records/",
            ),
        ),
    ),
    "contract": (
        GroupRule(
            "codec", ("tests.contracts.test_codec_contract",), ("src/loom/io/codecs/",)
        ),
        GroupRule(
            "data-source",
            ("tests.contracts.test_data_source_contract",),
            ("src/loom/io/sources/",),
        ),
        GroupRule(
            "executor",
            ("tests.contracts.test_executor_contract",),
            ("src/loom/pipeline/executors/", "src/loom/pipeline/execution/"),
        ),
        GroupRule(
            "recipe",
            ("tests.contracts.test_recipe_contract",),
            ("src/loom/config/recipes/",),
        ),
        GroupRule(
            "stage",
            ("tests.contracts.test_stage_contract",),
            ("src/loom/pipeline/stage.py",),
        ),
        GroupRule(
            "store",
            ("tests.contracts.test_store_contract",),
            ("src/loom/pipeline/stores/",),
        ),
    ),
    "integration": (
        GroupRule("config", ("tests.integration.config",), ("src/loom/config/",)),
        GroupRule("docs", ("tests.integration.docs",)),
        GroupRule("io", ("tests.integration.test_io_basics",), ("src/loom/io/",)),
        GroupRule("pipeline", ("tests.integration.pipeline",), ("src/loom/pipeline/",)),
    ),
    "e2e": (
        GroupRule(
            "local-pipeline-run", ("tests.e2e.test_local_pipeline_run",), ("src/loom/",)
        ),
    ),
    "config-extra": (
        GroupRule("package", ("tests.package",)),
        GroupRule("contract", ("tests.contracts",), ("src/loom/config/recipes/",)),
        GroupRule("unit-config", ("tests.unit.loom.config",), ("src/loom/config/",)),
        GroupRule(
            "unit-core", ("tests.unit.loom.test_deferred_stubs",), ("src/loom/config/",)
        ),
        GroupRule(
            "integration-config",
            (
                "tests.integration.config",
                "tests.integration.pipeline.test_pipeline_config",
            ),
            ("src/loom/config/", "src/loom/pipeline/"),
        ),
        GroupRule("integration-docs", ("tests.integration.docs",)),
        GroupRule(
            "integration-pipeline",
            ("tests.integration.pipeline",),
            ("src/loom/pipeline/",),
        ),
        GroupRule("e2e", ("tests.e2e",), ("src/loom/",)),
    ),
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
        "suites",
        nargs="*",
        choices=SUITES.keys(),
        help="Suites to summarize. Defaults to all suites.",
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
        suite_names = list(args.suites) or list(SUITES)
        results = [run_summary_suite(name) for name in suite_names]
        write_summary(args.output, results)
        print(f"Wrote test summary to {args.output}")
        for result in results:
            print(
                f"{result.suite}: {result.status} "
                f"({result.counts.passed} passed, {result.counts.failed} failed, "
                f"{result.counts.errors} errors, {result.counts.skipped} skipped, "
                f"{result.counts.deselected} deselected; {result.duration:.2f}s)"
            )
        return 1 if any(result.returncode != 0 for result in results) else 0

    raise AssertionError(f"unhandled command: {args.command}")


def run_summary_suite(name: str) -> SuiteSummary:
    suite = SUITES[name]
    if name != "config-extra" and not has_tests(suite.path):
        counts = Counts()
        return SuiteSummary(
            suite=suite.name,
            command=f'uv run pytest {suite.path} -m "{suite.marker_expr}"',
            status="not present",
            duration=0.0,
            returncode=0,
            output="No test files are present for this suite yet.",
            counts=counts,
            groups={},
            coverage={},
        )

    artifact_dir = SUMMARY_ARTIFACT_DIR / name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    junit_path = artifact_dir / "junit.xml"
    coverage_data_path = artifact_dir / ".coverage"
    coverage_json_path = artifact_dir / "coverage.json"
    unlink_existing(junit_path, coverage_data_path, coverage_json_path)

    pytest_args = pytest_args_for_suite(suite)
    command = uv_command_for_suite(name)
    command.extend(
        [
            "python",
            "-m",
            "coverage",
            "run",
            "--data-file",
            str(coverage_data_path),
            "--source",
            SOURCE_COVERAGE_ROOT,
            "-m",
            "pytest",
            *pytest_args,
            "--junitxml",
            str(junit_path),
        ]
    )

    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", UV_CACHE_DIR)
    display_command = f"UV_CACHE_DIR={env['UV_CACHE_DIR']} {format_command(command)}"

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
    output = completed.stdout

    coverage_output = write_coverage_json(
        name, coverage_data_path, coverage_json_path, env
    )
    if coverage_output:
        output = (
            output
            + ("\n" if output and not output.endswith("\n") else "")
            + coverage_output
        )

    counts, groups = parse_junit(junit_path, name)
    counts.deselected = parse_deselected(output)
    counts.duration = duration
    coverage = parse_coverage_json(coverage_json_path, name)
    status = "passed" if completed.returncode == 0 else "failed"
    if counts.total == 0 and completed.returncode == 0:
        status = "not present"

    return SuiteSummary(
        suite=name,
        command=display_command,
        status=status,
        duration=duration,
        returncode=completed.returncode,
        output=output,
        counts=counts,
        groups=groups,
        coverage=coverage,
    )


def uv_command_for_suite(name: str) -> list[str]:
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
    return command


def write_coverage_json(
    suite: str,
    coverage_data_path: Path,
    coverage_json_path: Path,
    env: Mapping[str, str],
) -> str:
    if not coverage_data_path.exists():
        return ""
    command = uv_command_for_suite(suite)
    command.extend(
        [
            "python",
            "-m",
            "coverage",
            "json",
            "--data-file",
            str(coverage_data_path),
            "-o",
            str(coverage_json_path),
            "--quiet",
        ]
    )
    completed = subprocess.run(
        command,
        check=False,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode == 0:
        return ""
    return completed.stdout or "coverage json failed without output\n"


def pytest_args_for_suite(suite: Suite) -> list[str]:
    return [str(suite.path), "-m", suite.marker_expr]


def unlink_existing(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


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
            pytest_args_for_suite(suite),
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
        pytest_args_for_suite(suite),
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


def parse_junit(path: Path, suite: str) -> tuple[Counts, dict[str, Counts]]:
    counts = Counts()
    groups: dict[str, Counts] = {}
    if not path.exists():
        return counts, groups

    root = ElementTree.parse(path).getroot()
    for case in root.iter():
        if local_name(case.tag) != "testcase":
            continue
        classname = case.attrib.get("classname", "") or case.attrib.get("name", "")
        group_name = group_for_classname(suite, classname)
        group_counts = groups.setdefault(group_name, Counts())
        case_counts = testcase_counts(case)
        counts.add(case_counts)
        group_counts.add(case_counts)

    return counts, groups


def testcase_counts(case: ElementTree.Element) -> Counts:
    counts = Counts(duration=parse_float(case.attrib.get("time")))
    child_tags = {local_name(child.tag) for child in case}
    if "error" in child_tags:
        counts.errors = 1
    elif "failure" in child_tags:
        counts.failed = 1
    elif "skipped" in child_tags:
        counts.skipped = 1
    else:
        counts.passed = 1
    return counts


def local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def group_for_classname(suite: str, classname: str) -> str:
    for rule in GROUP_RULES.get(suite, ()):
        if classname.startswith(rule.class_prefixes):
            return rule.name
    return "other"


def parse_float(raw: str | None) -> float:
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse_deselected(output: str) -> int:
    matches = re.findall(r"(\d+)\s+deselected", output)
    if not matches:
        return 0
    return int(matches[-1])


def parse_coverage_json(path: Path, suite: str) -> dict[str, CoverageMetric]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    files = raw.get("files")
    if not isinstance(files, dict):
        return {}

    coverage: dict[str, CoverageMetric] = {}
    totals = raw.get("totals")
    if isinstance(totals, dict):
        coverage["__suite__"] = CoverageMetric(
            covered_lines=int(totals.get("covered_lines", 0)),
            statements=int(totals.get("num_statements", 0)),
        )

    for rule in GROUP_RULES.get(suite, ()):
        metric = aggregate_coverage(files, rule.coverage_paths)
        if metric is not None:
            coverage[rule.name] = metric
    return coverage


def aggregate_coverage(
    files: Mapping[str, object],
    coverage_paths: Sequence[str],
) -> CoverageMetric | None:
    if not coverage_paths:
        return None
    covered_lines = 0
    statements = 0
    for raw_path, raw_file in files.items():
        path = normalize_coverage_path(raw_path)
        if not coverage_path_matches(path, coverage_paths):
            continue
        if not isinstance(raw_file, dict):
            continue
        summary = raw_file.get("summary")
        if not isinstance(summary, dict):
            continue
        covered_lines += int(summary.get("covered_lines", 0))
        statements += int(summary.get("num_statements", 0))
    if statements == 0:
        return None
    return CoverageMetric(covered_lines=covered_lines, statements=statements)


def normalize_coverage_path(path: str) -> str:
    normalized = Path(path).as_posix()
    marker = f"/{SOURCE_COVERAGE_ROOT}/"
    if marker in normalized:
        return f"{SOURCE_COVERAGE_ROOT}/{normalized.split(marker, maxsplit=1)[1]}"
    return normalized


def coverage_path_matches(path: str, selectors: Sequence[str]) -> bool:
    for selector in selectors:
        if selector.endswith("/"):
            if path.startswith(selector):
                return True
        elif path == selector:
            return True
    return False


def write_summary(path: Path, results: Sequence[SuiteSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overall = aggregate_counts([result.counts for result in results])
    overall_status = (
        "failed" if any(result.returncode != 0 for result in results) else "passed"
    )
    lines = [
        "# Test Suite Summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Overall Status: {overall_status}",
        "",
        "| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    result.suite,
                    result.status,
                    str(result.counts.passed),
                    str(result.counts.failed),
                    str(result.counts.errors),
                    str(result.counts.skipped),
                    str(result.counts.deselected),
                    str(result.counts.total),
                    f"{result.duration:.2f}s",
                    format_coverage(result.coverage.get("__suite__")),
                ]
            )
            + " |"
        )
    lines.append(
        "| "
        + " | ".join(
            [
                "Overall",
                overall_status,
                str(overall.passed),
                str(overall.failed),
                str(overall.errors),
                str(overall.skipped),
                str(overall.deselected),
                str(overall.total),
                f"{sum(result.duration for result in results):.2f}s",
                "-",
            ]
        )
        + " |"
    )

    for result in results:
        lines.extend(["", f"## {result.suite}", "", f"Command: `{result.command}`", ""])
        if result.groups:
            lines.extend(
                [
                    "| Group | Status | Passed | Failed | Errors | Skipped | Total | Duration | Coverage |",
                    "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for group_name, counts in sorted(result.groups.items()):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            group_name,
                            counts.status,
                            str(counts.passed),
                            str(counts.failed),
                            str(counts.errors),
                            str(counts.skipped),
                            str(counts.total),
                            f"{counts.duration:.2f}s",
                            format_coverage(result.coverage.get(group_name)),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("_No tests were present for this suite._")

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


def aggregate_counts(counts: Sequence[Counts]) -> Counts:
    aggregate = Counts()
    for count in counts:
        aggregate.add(count)
    return aggregate


def format_coverage(metric: CoverageMetric | None) -> str:
    if metric is None:
        return "N/A"
    percent = metric.percent
    if percent is None:
        return "N/A"
    return f"{percent:.0f}%"


def format_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def tail(output: str, line_count: int = 20) -> str:
    stripped = output.strip()
    if not stripped:
        return "(no output)"
    lines = stripped.splitlines()
    return "\n".join(lines[-line_count:])
