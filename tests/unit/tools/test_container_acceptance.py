"""Host-free regressions for the real-runtime acceptance probe's shell flow."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.container_acceptance import test_real_container_runtimes as acceptance


@pytest.mark.parametrize(
    ("failed_control", "message", "reads"),
    (
        ("membership", "payload cgroup-v2 membership is missing", []),
        ("cpu", "cannot read payload cpu.max", ["cpu"]),
        ("memory", "cannot read payload memory.max", ["cpu", "memory"]),
        ("", "", ["cpu", "memory"]),
    ),
)
def test_resource_probe_fails_closed_before_accepting_controls(
    tmp_path: Path,
    failed_control: str,
    message: str,
    reads: list[str],
) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    lookup = commands / "awk"
    lookup.write_text(
        '#!/bin/sh\n[ "$PROBE_FAILURE" = membership ] && exit 0\n'
        "printf '/payload\\n'\n",
        encoding="utf-8",
    )
    reader = commands / "cat"
    reader.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        "*/cpu.max) control=cpu ;;\n"
        "*/memory.max) control=memory ;;\n"
        "*) exit 2 ;;\nesac\n"
        'printf "%s\\n" "$control" >> "$PROBE_READ_LOG"\n'
        '[ "$PROBE_FAILURE" = "$control" ] && exit 1\n'
        'if [ "$control" = cpu ]; then printf "200000 100000\\n"; '
        'else printf "536870912\\n"; fi\n',
        encoding="utf-8",
    )
    lookup.chmod(0o700)
    reader.chmod(0o700)
    read_log = tmp_path / "reads.txt"

    result = subprocess.run(  # noqa: S603 - bounded acceptance shell with owned stubs.
        ("/bin/sh", "-c", acceptance._RESOURCE_LIMIT_PROBE),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env={
            "PATH": str(commands),
            "PROBE_FAILURE": failed_control,
            "PROBE_READ_LOG": str(read_log),
        },
    )

    assert result.returncode == (1 if failed_control else 0)
    assert message in result.stderr
    actual_reads = read_log.read_text().splitlines() if read_log.exists() else []
    assert actual_reads == reads
    if not failed_control:
        assert result.stdout.splitlines() == ["200000 100000", "536870912"]
