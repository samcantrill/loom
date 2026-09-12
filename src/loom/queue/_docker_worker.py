"""Daemon lifetime evidence owned by the resident process supervisor.

The caller supplies its existing SQLite connection. Intent commits precede daemon
calls; unknown responses never authorize a second create or start. Container
terminal evidence is retained before removal, independently of worker results.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import sqlite3
import subprocess
from typing import Any


@dataclass(frozen=True, slots=True)
class DockerObservation:
    """Backend facts; none of these is a native process-exit qualification."""

    state: str
    container_id: str | None = None
    exit_code: int | None = None
    contained: bool = False
    successful: bool = False
    removed: bool = False


DockerCall = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _call(
    argv: Sequence[str], *, environment: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        stdin=subprocess.DEVNULL,
        env=dict(environment or {}),
    )


class DockerWorker:
    """Reconcile one exact daemon object through the supervisor's database.

    The bound command uses an absolute CLI executable and explicit daemon endpoint.
    It must be produced by Loom's container command/resource owner. The supervisor
    serializes calls for an operation; this owner commits at every effect boundary.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        ownership: str,
        command: Sequence[str],
        endpoint: str,
        call: DockerCall = _call,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.connection = connection
        self.operation_id = operation_id
        self.ownership = ownership
        self.command = tuple(command)
        self.endpoint = endpoint
        self.call = call
        self.environment = dict(environment or {})
        self.name = "loom-" + ownership
        self.prefix = (self.command[0], "--host", endpoint)

    @staticmethod
    def initialize(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE docker_workers (operation_id TEXT PRIMARY KEY, "
            "intent TEXT NOT NULL, evidence TEXT NOT NULL)"
        )

    def _load(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT intent, evidence FROM docker_workers WHERE operation_id = ?",
            (self.operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != self._intent():
            raise ValueError("Docker worker intent conflicts with retained ownership")
        return json.loads(row[1])

    def _intent(self) -> str:
        return json.dumps(
            {
                "ownership": self.ownership,
                "command": self.command,
                "endpoint": self.endpoint,
                "environment": self.environment,
            },
            sort_keys=True,
        )

    def _save(self, evidence: Mapping[str, Any]) -> None:
        self.connection.execute(
            "UPDATE docker_workers SET evidence = ? WHERE operation_id = ?",
            (json.dumps(evidence, sort_keys=True), self.operation_id),
        )
        self.connection.commit()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            if self.call is _call:
                return _call((*self.prefix, *args), environment=self.environment)
            return self.call((*self.prefix, *args))
        except (OSError, subprocess.SubprocessError):
            return None

    def launch(self) -> DockerObservation:
        evidence = self._load()
        if evidence is not None:
            return self.observe()
        if len(self.command) < 3 or self.command[1] != "run" or "--rm" in self.command:
            raise ValueError("Docker worker requires retained foreground run options")
        self.connection.execute(
            "INSERT INTO docker_workers VALUES (?, ?, ?)",
            (self.operation_id, self._intent(), json.dumps({"phase": "creating"})),
        )
        self.connection.commit()
        # No --rm: the daemon must retain the only terminal evidence until capture.
        self._run(
            "create",
            "--name",
            self.name,
            "--label",
            "org.loom.ownership=" + self.ownership,
            "--restart=no",
            "--pull=never",
            *self.command[2:],
        )
        return self.observe()

    def observe(self) -> DockerObservation:
        evidence = self._load()
        if evidence is None:
            return DockerObservation("not_accepted")
        if evidence.get("contained"):
            return self._observation(evidence)
        reference = evidence.get("container_id", self.name)
        result = self._run("inspect", "--type", "container", reference)
        if result is None or result.returncode:
            return DockerObservation("unknown", evidence.get("container_id"))
        try:
            values = json.loads(result.stdout)
            if not isinstance(values, list) or len(values) != 1:
                raise ValueError("ambiguous container observation")
            value = values[0]
            container_id = value["Id"]
            state = value["State"]
            if (
                not isinstance(container_id, str)
                or not container_id
                or value["Config"]["Labels"].get("org.loom.ownership") != self.ownership
                or value["Name"] != "/" + self.name
                or evidence.get("container_id", container_id) != container_id
                or value["HostConfig"]["RestartPolicy"]["Name"] not in ("no", "")
                or value["HostConfig"].get("AutoRemove") is not False
            ):
                raise ValueError(
                    "Docker observation has a foreign or unstable identity"
                )
        except (ValueError, KeyError, TypeError):
            return DockerObservation("unknown", evidence.get("container_id"))
        evidence["container_id"] = container_id
        if evidence.get("cancelled"):
            if (
                state.get("Status") in {"exited", "dead", "created"}
                and state.get("Running") is False
            ):
                evidence.update(
                    phase="terminal",
                    contained=True,
                    successful=False,
                    exit_code=state.get("ExitCode"),
                )
                self._save(evidence)
                return self._observation(evidence)
            self._save(evidence)
            self._run("kill", container_id)
            # A command return is not containment. A subsequent inspection owns it.
            return DockerObservation("running", container_id)
        if state.get("Status") == "created" and evidence["phase"] == "creating":
            evidence["phase"] = "starting"
            self._save(evidence)
            self._run("start", container_id)
            return self.observe()
        if state.get("Status") == "running" and state.get("Running") is True:
            evidence["phase"] = "running"
            self._save(evidence)
            return DockerObservation("running", container_id)
        if (
            state.get("Status") in {"exited", "dead"}
            and state.get("Running") is False
            and type(state.get("ExitCode")) is int
            and state.get("FinishedAt") not in (None, "", "0001-01-01T00:00:00Z")
        ):
            evidence.update(
                phase="terminal",
                contained=True,
                successful=state["ExitCode"] == 0
                and not state.get("OOMKilled", False)
                and not state.get("Error"),
                exit_code=state["ExitCode"],
            )
            self._save(evidence)
            return self._observation(evidence)
        self._save(evidence)
        return DockerObservation("unknown", container_id)

    def cancel(self) -> DockerObservation:
        evidence = self._load()
        if evidence is None:
            # A durable no-effect outcome can settle without a daemon object.
            evidence = {
                "phase": "terminal",
                "cancelled": True,
                "contained": True,
                "successful": False,
            }
            self.connection.execute(
                "INSERT INTO docker_workers VALUES (?, ?, ?)",
                (self.operation_id, self._intent(), json.dumps(evidence)),
            )
            self.connection.commit()
        elif not evidence.get("contained"):
            evidence["cancelled"] = True
            self._save(evidence)
        return self.observe()

    def remove(self) -> DockerObservation:
        evidence = self._load()
        if evidence is None or not evidence.get("contained"):
            return DockerObservation("unknown")
        if evidence.get("removed") or not evidence.get("container_id"):
            return self._observation(evidence)
        # Absence can settle cleanup only after terminal evidence was captured.
        observed = self._run("inspect", "--type", "container", evidence["container_id"])
        if observed is None:
            return self._observation(evidence)
        if observed.returncode:
            if (
                "No such container" in observed.stderr
                or "No such object" in observed.stderr
            ):
                evidence["removed"] = True
                self._save(evidence)
            return self._observation(evidence)
        try:
            values = json.loads(observed.stdout)
            if (
                len(values) != 1
                or values[0]["Id"] != evidence["container_id"]
                or values[0]["Config"]["Labels"].get("org.loom.ownership")
                != self.ownership
            ):
                return self._observation(evidence)
        except (ValueError, KeyError, TypeError):
            return self._observation(evidence)
        # Immutable ID, never the reusable name. Captured evidence survives loss.
        result = self._run("rm", evidence["container_id"])
        if result is not None and result.returncode == 0:
            evidence["removed"] = True
            self._save(evidence)
        return self._observation(evidence)

    @staticmethod
    def _observation(evidence: Mapping[str, Any]) -> DockerObservation:
        return DockerObservation(
            evidence["phase"],
            evidence.get("container_id"),
            evidence.get("exit_code"),
            evidence.get("contained", False),
            evidence.get("successful", False),
            evidence.get("removed", False),
        )
