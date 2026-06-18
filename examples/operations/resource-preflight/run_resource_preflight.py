"""Run resource preflight with warning and strict modes."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from loom.cli.main import main as loom_main


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    config_path = HERE / "pipeline.yaml"
    normal = _run_cli(
        ["preflight", str(config_path), "--check", "resources", "--format", "json"]
    )
    strict = _run_cli(
        [
            "preflight",
            str(config_path),
            "--check",
            "resources",
            "--strict",
            "--format",
            "json",
        ],
        expected=4,
    )
    diagnostics = normal["result"]["checks"][0]["details"]["diagnostics"]
    print(f"normal_status: {normal['result']['status']}")
    print(f"strict_status: {strict['result']['status']}")
    print(f"diagnostic_codes: {','.join(item['code'] for item in diagnostics)}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    return json.loads(stdout.getvalue())


if __name__ == "__main__":
    main()
