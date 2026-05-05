from __future__ import annotations

import json
from pathlib import Path

from tools.test_harness.cli import (
    Counts,
    CoverageMetric,
    SuiteSummary,
    format_coverage,
    parse_coverage_json,
    parse_deselected,
    parse_junit,
    write_summary,
)


def test_parse_junit_groups_testcase_counts_by_suite_section(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1">
    <testcase classname="tests.unit.loom.config.test_load" name="test_passes" time="0.10" />
    <testcase classname="tests.unit.loom.pipeline.execution.test_runner" name="test_fails" time="0.20">
      <failure message="failed" />
    </testcase>
    <testcase classname="tests.unit.loom.pipeline.graph.test_dag" name="test_errors" time="0.30">
      <error message="errored" />
    </testcase>
    <testcase classname="tests.unit.loom.serialization.test_json" name="test_skips" time="0.40">
      <skipped message="skipped" />
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    counts, groups = parse_junit(junit_path, "unit")

    assert counts.passed == 1
    assert counts.failed == 1
    assert counts.errors == 1
    assert counts.skipped == 1
    assert counts.total == 4
    assert groups["config"].passed == 1
    assert groups["pipeline-execution"].failed == 1
    assert groups["pipeline-graph"].errors == 1
    assert groups["serialization"].skipped == 1


def test_parse_deselected_uses_last_pytest_summary_count() -> None:
    assert parse_deselected("14 passed, 5 deselected in 0.25s") == 5
    assert parse_deselected("first: 1 deselected\nsecond: 411 deselected") == 411
    assert parse_deselected("14 passed in 0.25s") == 0


def test_parse_junit_classifies_collection_skips_by_test_name(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="1" skipped="1">
    <testcase classname="" name="tests.unit.loom.test_deferred_stubs" time="0.00">
      <skipped message="collection skipped" />
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    _, groups = parse_junit(junit_path, "unit")

    assert groups["core"].skipped == 1


def test_parse_coverage_json_reports_suite_and_group_percentages(
    tmp_path: Path,
) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "totals": {"covered_lines": 8, "num_statements": 10},
                "files": {
                    "src/loom/config/load.py": {
                        "summary": {"covered_lines": 6, "num_statements": 8}
                    },
                    "src/loom/io/uris.py": {
                        "summary": {"covered_lines": 2, "num_statements": 2}
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    coverage = parse_coverage_json(coverage_path, "unit")

    assert format_coverage(coverage["__suite__"]) == "80%"
    assert format_coverage(coverage["config"]) == "75%"
    assert format_coverage(coverage["io"]) == "100%"


def test_write_summary_renders_overall_and_suite_breakdowns(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.md"
    write_summary(
        summary_path,
        [
            SuiteSummary(
                suite="unit",
                command="UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit",
                status="passed",
                duration=1.23,
                returncode=0,
                output="unit output",
                counts=Counts(passed=2, skipped=1, deselected=4, duration=1.23),
                groups={"config": Counts(passed=2, duration=0.50)},
                coverage={
                    "__suite__": CoverageMetric(covered_lines=9, statements=10),
                    "config": CoverageMetric(covered_lines=3, statements=4),
                },
            )
        ],
    )

    rendered = summary_path.read_text(encoding="utf-8")

    assert "# Test Suite Summary" in rendered
    assert "| unit | passed | 2 | 0 | 0 | 1 | 4 | 3 | 1.23s | 90% |" in rendered
    assert "| Overall | passed | 2 | 0 | 0 | 1 | 4 | 3 | 1.23s | - |" in rendered
    assert "## unit" in rendered
    assert "| config | passed | 2 | 0 | 0 | 0 | 2 | 0.50s | 75% |" in rendered
    assert "unit output" in rendered
