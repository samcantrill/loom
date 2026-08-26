"""Private durable owner for resident managed-worker process groups.

The coordinator and agent journal deliberately do not retain live process
objects.  A supervisor has one narrowly scoped job: persist a fully specified
launch before creating its process group and report only facts it owns.  It is
private queue application infrastructure; pipeline execution never imports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
from typing import Mapping
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data


class AgentProcessSupervisorError(ValueError):
    """A supervisor identity, schema, or launch contract is invalid."""


class SupervisorLaunchState(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"
    CONTAINED = "contained"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResidentWorkerLaunchProfile:
    """Protected executable/project binding for every resident worker."""

    project_root: Path
    python_executable: Path
    descriptor: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        root = Path(self.project_root).resolve()
        executable = Path(os.path.abspath(self.python_executable))
        if not root.is_dir() or not executable.is_file():
            raise AgentProcessSupervisorError("resident worker launch profile is unavailable")
        try:
            descriptor = freeze_plain_data(self.descriptor, path="resident profile")
        except ValueError as exc:
            raise AgentProcessSupervisorError(str(exc)) from exc
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "python_executable", executable)
        object.__setattr__(self, "descriptor", thaw_plain_data(descriptor, path="resident profile"))

    @property
    def fingerprint(self) -> str:
        return _digest({
            "project_root": str(self.project_root),
            "python_executable": str(self.python_executable),
            "descriptor": self.descriptor,
        })


@dataclass(frozen=True, slots=True)
class ResidentWorkerLaunch:
    """The complete immutable identity accepted by the process owner."""

    supervisor_id: str
    continuity_epoch: str
    agent_id: str
    session_id: str
    assignment_id: str
    process_execution_id: str
    execution_fence: str
    launch_operation_id: str
    workspace_root: Path
    profile: ResidentWorkerLaunchProfile
    environment: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "supervisor_id", "continuity_epoch", "agent_id", "session_id",
            "assignment_id", "process_execution_id", "execution_fence",
            "launch_operation_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise AgentProcessSupervisorError(f"{name} must be a non-empty string")
        workspace = Path(self.workspace_root).resolve()
        if not workspace.is_dir():
            raise AgentProcessSupervisorError("resident workspace is unavailable")
        if not isinstance(self.profile, ResidentWorkerLaunchProfile):
            raise AgentProcessSupervisorError("resident launch profile is invalid")
        environment = dict(self.environment)
        if any(not isinstance(key, str) or not key or not isinstance(value, str) for key, value in environment.items()):
            raise AgentProcessSupervisorError("resident launch environment is invalid")
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "environment", environment)

    @property
    def spec_digest(self) -> str:
        return _digest({
            "supervisor_id": self.supervisor_id,
            "continuity_epoch": self.continuity_epoch,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "process_execution_id": self.process_execution_id,
            "execution_fence": self.execution_fence,
            "launch_operation_id": self.launch_operation_id,
            "workspace_root": str(self.workspace_root),
            "profile_fingerprint": self.profile.fingerprint,
            "environment": self.environment,
        })


@dataclass(frozen=True, slots=True)
class SupervisorReceipt:
    state: SupervisorLaunchState
    launch: ResidentWorkerLaunch
    supervisor_revision: int
    process_id: int | None = None
    exit_code: int | None = None
    worker_result_digest: str | None = None


class AgentProcessSupervisor:
    """SQLite-backed process-group owner with exact-operation replay.

    A service wrapper may hold this object for its complete continuity epoch.
    Reopening the database without that service continuity deliberately returns
    ``UNKNOWN`` for a nonterminal launch: a PID is not adoption evidence.
    """

    _SCHEMA_VERSION = 1

    def __init__(self, root: Path, *, agent_id: str, profile: ResidentWorkerLaunchProfile, initialize: bool = False) -> None:
        self.root = Path(root).resolve()
        self._agent_id = agent_id
        self._profile = profile
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._path = self.root / "supervisor.sqlite"
        if initialize:
            self._initialize()
        self._open()

    @classmethod
    def initialize(cls, agent_root: Path, *, agent_id: str, profile: ResidentWorkerLaunchProfile) -> "AgentProcessSupervisor":
        root = Path(agent_root).resolve() / "supervisor"
        if root.exists():
            raise AgentProcessSupervisorError("supervisor root already exists")
        root.mkdir(mode=0o700, parents=False)
        return cls(root, agent_id=agent_id, profile=profile, initialize=True)

    @classmethod
    def initialize_unbound(cls, agent_root: Path, *, agent_id: str) -> None:
        """Create the current hard-cut root before a resident profile is selected.

        The first protected resident profile binds this fresh root; subsequent
        opens require that exact fingerprint.  Legacy roots have no such row and
        are therefore rejected rather than migrated.
        """
        root = Path(agent_root).resolve() / "supervisor"
        if root.exists():
            raise AgentProcessSupervisorError("supervisor root already exists")
        root.mkdir(mode=0o700, parents=False)
        path = root / "supervisor.sqlite"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE launches (
              operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
              launch_json TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
              pid INTEGER, exit_code INTEGER, result_digest TEXT
            );
            """)
            conn.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", (
                ("schema_version", str(cls._SCHEMA_VERSION)),
                ("supervisor_id", f"supervisor-{uuid4()}"),
                ("agent_id", agent_id),
                ("profile_fingerprint", ""),
                ("continuity_epoch", f"supervisor-epoch-{uuid4()}"),
            ))
            conn.commit()
        path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE launches (
              operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
              launch_json TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
              pid INTEGER, exit_code INTEGER, result_digest TEXT
            );
            """)
            conn.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", (
                ("schema_version", str(self._SCHEMA_VERSION)),
                ("supervisor_id", f"supervisor-{uuid4()}"),
                ("agent_id", self._agent_id),
                ("profile_fingerprint", self._profile.fingerprint),
                ("continuity_epoch", f"supervisor-epoch-{uuid4()}"),
            ))
            conn.commit()
        self._path.chmod(0o600)

    def _open(self) -> None:
        if not self._path.is_file():
            raise AgentProcessSupervisorError("managed_supervisor_state_requires_reinitialization")
        try:
            with self._connect() as conn:
                values = {str(row["key"]): str(row["value"]) for row in conn.execute("SELECT key, value FROM metadata")}
        except sqlite3.Error as exc:
            raise AgentProcessSupervisorError("managed_supervisor_state_requires_reinitialization") from exc
        if values.get("schema_version") != str(self._SCHEMA_VERSION) or values.get("agent_id") != self._agent_id:
            raise AgentProcessSupervisorError("managed_supervisor_state_requires_reinitialization")
        if values.get("profile_fingerprint") == "":
            with self._connect() as conn:
                conn.execute("UPDATE metadata SET value = ? WHERE key = 'profile_fingerprint'", (self._profile.fingerprint,))
                conn.commit()
        elif values.get("profile_fingerprint") != self._profile.fingerprint:
            raise AgentProcessSupervisorError("managed_supervisor_state_requires_reinitialization")
        self.supervisor_id = values.get("supervisor_id", "")
        self.continuity_epoch = values.get("continuity_epoch", "")
        if not self.supervisor_id or not self.continuity_epoch:
            raise AgentProcessSupervisorError("managed_supervisor_state_requires_reinitialization")

    def launch(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        self._validate_launch(launch)
        encoded = _launch_json(launch)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
            if row is not None:
                if str(row["digest"]) != launch.spec_digest:
                    raise AgentProcessSupervisorError("launch operation conflicts with durable identity")
                return self._receipt(launch, row)
            conn.execute("INSERT INTO launches(operation_id, digest, launch_json, state, revision) VALUES (?, ?, ?, ?, 1)", (launch.launch_operation_id, launch.spec_digest, encoded, SupervisorLaunchState.STARTING.value))
            conn.commit()
        # The complete permitted environment is part of the durable launch
        # identity.  Do not merge ambient service state at the spawn boundary.
        environment = dict(launch.environment)
        gate = launch.workspace_root / "run.grant"
        gate.write_text("granted\n", encoding="utf-8")
        try:
            child = subprocess.Popen(
                [str(launch.profile.python_executable), "-m", "loom.queue._resident_stage_worker", "--workspace", str(launch.workspace_root)],
                cwd=launch.profile.project_root, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as exc:
            with self._connect() as conn:
                conn.execute("UPDATE launches SET state = ?, revision = revision + 1 WHERE operation_id = ?", (SupervisorLaunchState.UNKNOWN.value, launch.launch_operation_id))
                conn.commit()
            raise AgentProcessSupervisorError("resident root was not created") from exc
        self._children[launch.launch_operation_id] = child
        with self._connect() as conn:
            conn.execute("UPDATE launches SET state = ?, pid = ?, revision = revision + 1 WHERE operation_id = ?", (SupervisorLaunchState.RUNNING.value, child.pid, launch.launch_operation_id))
            row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
            conn.commit()
        return self._receipt(launch, row)

    def query(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        self._validate_launch(launch)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
            if row is None:
                return SupervisorReceipt(SupervisorLaunchState.NOT_ACCEPTED, launch, 0)
            if str(row["digest"]) != launch.spec_digest:
                raise AgentProcessSupervisorError("launch query conflicts with durable identity")
            child = self._children.get(launch.launch_operation_id)
            if child is not None:
                code = child.poll()
                if code is not None and str(row["state"]) in {SupervisorLaunchState.STARTING.value, SupervisorLaunchState.RUNNING.value}:
                    result = launch.workspace_root / "worker-result.json"
                    digest = _file_digest(result) if result.is_file() else None
                    conn.execute("UPDATE launches SET state = ?, exit_code = ?, result_digest = ?, revision = revision + 1 WHERE operation_id = ?", (SupervisorLaunchState.EXITED.value, code, digest, launch.launch_operation_id))
                    conn.commit()
                    row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
            elif str(row["state"]) in {SupervisorLaunchState.STARTING.value, SupervisorLaunchState.RUNNING.value}:
                # An agent can restart only against a continuously running supervisor
                # service.  This object has no evidence that a raw retained PID is ours.
                conn.execute("UPDATE launches SET state = ?, revision = revision + 1 WHERE operation_id = ?", (SupervisorLaunchState.UNKNOWN.value, launch.launch_operation_id))
                conn.commit()
                row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
            return self._receipt(launch, row)

    def contain(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        receipt = self.query(launch)
        child = self._children.get(launch.launch_operation_id)
        if child is None:
            return receipt
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                return SupervisorReceipt(SupervisorLaunchState.UNKNOWN, launch, receipt.supervisor_revision)
        result = launch.workspace_root / "worker-result.json"
        with self._connect() as conn:
            conn.execute("UPDATE launches SET state = ?, exit_code = ?, result_digest = ?, revision = revision + 1 WHERE operation_id = ?", (SupervisorLaunchState.CONTAINED.value, child.returncode, _file_digest(result) if result.is_file() else None, launch.launch_operation_id))
            conn.commit()
            row = conn.execute("SELECT * FROM launches WHERE operation_id = ?", (launch.launch_operation_id,)).fetchone()
        return self._receipt(launch, row)

    def _validate_launch(self, launch: ResidentWorkerLaunch) -> None:
        if launch.supervisor_id != self.supervisor_id or launch.continuity_epoch != self.continuity_epoch or launch.agent_id != self._agent_id or launch.profile.fingerprint != self._profile.fingerprint:
            raise AgentProcessSupervisorError("supervisor launch identity mismatch")

    @staticmethod
    def _receipt(launch: ResidentWorkerLaunch, row: sqlite3.Row) -> SupervisorReceipt:
        return SupervisorReceipt(SupervisorLaunchState(str(row["state"])), launch, int(row["revision"]), cast_int(row["pid"]), cast_int(row["exit_code"]), str(row["result_digest"]) if row["result_digest"] is not None else None)


def cast_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | str):
        return int(value)
    raise AgentProcessSupervisorError("supervisor receipt contains an invalid PID")


def _launch_json(launch: ResidentWorkerLaunch) -> str:
    return json.dumps({"digest": launch.spec_digest}, sort_keys=True, separators=(",", ":"))


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["AgentProcessSupervisor", "AgentProcessSupervisorError", "ResidentWorkerLaunch", "ResidentWorkerLaunchProfile", "SupervisorLaunchState", "SupervisorReceipt"]
