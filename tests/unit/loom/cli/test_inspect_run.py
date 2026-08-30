from __future__ import annotations

import io

from loom.cli.main import main


def test_inspect_run_requires_exactly_one_source() -> None:
    assert (
        main(
            ["inspect-run", "file:///tmp/run"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 2
    )


def test_inspect_run_json_uses_fixed_envelope() -> None:
    stdout = io.StringIO()
    assert (
        main(
            ["inspect-run", "invalid", "--direct", "--format", "json"],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert '"schema_version":"loom.cli.inspect_run.v1"' in stdout.getvalue()
    assert '"code":"invalid_request"' in stdout.getvalue()
