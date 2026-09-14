"""Fake foreground runtime and namespace observation seam for local examples.

The fixture models the namespace with the creation-owned launcher pidfd. It does
not establish Linux namespace behavior or qualify a physical Apptainer runtime.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile


@contextmanager
def fake_apptainer():
    from loom.pipeline.executors.apptainer import _timeout

    with tempfile.TemporaryDirectory(prefix="loom-fake-apptainer-") as scratch:
        root = Path(scratch)
        command = root / "apptainer"
        command.write_text(f"""#!{sys.executable}
import os, sys
args = sys.argv[1:]
if args == ['--version']:
    print('singularity version 3.10.4')
    raise SystemExit(0)
assert args.pop(0) == 'exec'
while args and args[0].startswith('--'):
    option = args.pop(0)
    if option in ('--pid', '--no-init=false', '--cleanenv', '--nv', '--rocm', '--fakeroot', '--no-home'):
        continue
    value = args.pop(0)
    if option == '--env':
        name, item = value.split('=', 1)
        os.environ[name] = item
    elif option == '--pwd':
        os.chdir(value)
args.pop(0)
os.execvpe(args[0], args, os.environ)
""")
        command.chmod(0o700)
        image = root / "fixture.sif"
        image.write_text("Local fixture only; not a container image.\n")
        # Supervisor processes use a fresh interpreter. Install the same explicit
        # fake kernel seam there; product code contains no fixture switch.
        (root / "sitecustomize.py").write_text(
            "import os\nfrom loom.pipeline.executors.apptainer import _timeout\n"
            "_timeout._capture_init = lambda process, group: os.pidfd_open(process.pid)\n"
        )
        prior = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(root) + (os.pathsep + prior if prior else "")
        original = _timeout._capture_init
        _timeout._capture_init = lambda process, group: os.pidfd_open(process.pid)
        try:
            yield {
                "kind": "apptainer",
                "container": {"image": {"reference": str(image)}},
                "options": {"command": str(command), "cleanenv": True},
                "python_executable": sys.executable,
                "daemon_endpoint": None,
            }
        finally:
            _timeout._capture_init = original
            if prior is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = prior
