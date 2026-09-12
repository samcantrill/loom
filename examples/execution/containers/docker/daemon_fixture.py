"""A stateful local daemon fixture; no physical container qualification."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
from threading import Lock, Thread
from uuid import uuid4


@contextmanager
def fake_docker(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    endpoint = root / "daemon.sock"
    executable = root / "docker"
    executable.write_text(f"""#!{sys.executable}
import json, socket, sys
args = sys.argv[1:]
assert args[0] == '--host'
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect(args[1].removeprefix('unix://'))
    connection.sendall((json.dumps(args[2:]) + '\\n').encode())
    stream = connection.makefile('rb')
    result = json.loads(stream.readline())
print(result['stdout'])
print(result['stderr'], file=sys.stderr)
sys.exit(result['code'])
""")
    executable.chmod(0o700)
    records = {}
    children = []
    watchers = []
    calls = []
    lock = Lock()

    def watch(child, record):
        code = child.wait()
        with lock:
            record["State"].update(
                Status="exited",
                Running=False,
                ExitCode=code,
                FinishedAt="2026-09-12T01:02:03Z",
            )

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            args = json.loads(self.rfile.readline())
            with lock:
                calls.append(args)
                code, stdout, stderr = 0, "", ""
                if args[0] == "create":
                    name = args[args.index("--name") + 1]
                    ownership = args[args.index("--label") + 1].split("=", 1)[1]
                    identifier = uuid4().hex
                    env = dict(os.environ)
                    index = 1
                    while index < len(args) and args[index].startswith("--"):
                        option = args[index]
                        if "=" in option:
                            index += 1
                            continue
                        value = args[index + 1]
                        if option == "--env":
                            key, item = value.split("=", 1)
                            env[key] = item
                        index += 2
                    worker = args[index + 1 :]
                    records[identifier] = {
                        "Id": identifier,
                        "Name": "/" + name,
                        "Config": {"Labels": {"org.loom.ownership": ownership}},
                        "HostConfig": {
                            "RestartPolicy": {"Name": "no"},
                            "AutoRemove": False,
                        },
                        "State": {"Status": "created", "Running": False, "ExitCode": 0},
                        "worker": worker,
                        "env": env,
                        "cwd": args[args.index("--workdir") + 1],
                    }
                    stdout = identifier
                elif args[0] == "inspect":
                    record = records.get(args[-1]) or next(
                        (v for v in records.values() if v["Name"] == "/" + args[-1]),
                        None,
                    )
                    if record is None:
                        code, stderr = 1, "No such container"
                    else:
                        stdout = json.dumps(
                            {
                                k: v
                                for k, v in record.items()
                                if k not in {"child", "worker", "env", "cwd"}
                            }
                        )
                        stdout = "[" + stdout + "]"
                elif args[0] == "start":
                    record = records[args[1]]
                    assert record["State"]["Status"] == "created"
                    child = subprocess.Popen(
                        record["worker"],
                        cwd=record["cwd"],
                        env=record["env"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    children.append(child)
                    record["child"] = child
                    record["State"].update(Status="running", Running=True)
                    thread = Thread(target=watch, args=(child, record))
                    watchers.append(thread)
                    thread.start()
                elif args[0] == "kill":
                    records[args[1]]["child"].terminate()
                elif args[0] == "rm":
                    assert records[args[1]]["State"]["Running"] is False
                    del records[args[1]]
                else:
                    raise AssertionError(args)
            self.wfile.write(
                (
                    json.dumps({"code": code, "stdout": stdout, "stderr": stderr})
                    + "\n"
                ).encode()
            )

    server = socketserver.ThreadingUnixStreamServer(str(endpoint), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield (
            {
                "kind": "docker",
                "container": {"image": {"reference": "sha256:" + "a" * 64}},
                "options": {"command": str(executable)},
                "python_executable": sys.executable,
                "daemon_endpoint": "unix://" + str(endpoint),
            },
            calls,
        )
    finally:
        # This fixture is the daemon owner and reaps every worker it created.
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=20)
        for watcher in watchers:
            watcher.join(timeout=20)
            assert not watcher.is_alive()
        server.shutdown()
        server.server_close()
        thread.join(timeout=20)
        assert not thread.is_alive()
        endpoint.unlink()
