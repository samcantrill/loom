#!/usr/bin/env python3
"""Build two small installed SIFs for submitted-container physical acceptance.

This is an opt-in test fixture builder, not a workload build service. It uses an
unprivileged Python sandbox, the current wheel, locked dependencies and one
image-only probe. Output is never replaced and contains no host source mount.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

BASE = "docker://python@sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--runtime", default=shutil.which("apptainer") or shutil.which("singularity"))
    args = parser.parse_args()
    if not args.runtime:
        parser.error("Apptainer or Singularity is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[1]

    def run(command, *, cwd=repository):
        subprocess.run(command, cwd=cwd, check=True, umask=0o022)

    run(["uv", "build", "--wheel", "--out-dir", str(output / "wheels")])
    requirements = output / "requirements.txt"
    run(["uv", "export", "--locked", "--no-dev", "--extra", "config", "--no-emit-project",
         "--no-hashes", "--format", "requirements-txt", "--output-file", str(requirements)])
    wheel, = (output / "wheels").glob("*.whl")
    source = (repository / "tests/support/submitted_container_probe.py").read_text()
    receipts = {}
    with tempfile.TemporaryDirectory(prefix="loom-submitted-images-") as temporary:
        sandbox = Path(temporary) / "base"
        run([args.runtime, "build", "--sandbox", str(sandbox), BASE])
        site = sandbox / "usr/local/lib/python3.12/site-packages"
        run(["uv", "pip", "install", "--python", "3.12", "--link-mode", "copy",
             "--target", str(site), "-r", str(requirements), str(wheel)])
        # Source-built cached wheels can retain the builder's restrictive modes.
        # SIF packaging assigns root ownership, so installed bytes need read access.
        for path in [site, *site.rglob("*")]:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | (0o555 if path.is_dir() else 0o444))
        for name, value in (("aaa", 11), ("aab", 29)):
            probe = site / "submitted_probe.py"
            probe.write_text(source.replace("VALUE = 11", f"VALUE = {value}"))
            probe.chmod(0o644)
            image = output / name / "image.sif"
            image.parent.mkdir()
            run([args.runtime, "build", str(image), str(sandbox)])
            image.chmod(0o444)
            run([args.runtime, "exec", "--cleanenv", "--no-home", str(image),
                 "/usr/local/bin/python", "-I", "-c",
                 f"import loom.queue, weave, submitted_probe; assert submitted_probe.VALUE == {value}; "
                 f"assert hasattr(submitted_probe, 'NewStage') == {value == 29}"],
                cwd=Path("/tmp"))
            with image.open("rb") as stream:
                receipts[name] = {
                    "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                    "size_bytes": image.stat().st_size,
                }
    (output / "build.json").write_text(json.dumps({
        "base": BASE, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "images": receipts,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
