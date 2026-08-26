"""Private durable owner for resident managed-worker process groups.

The coordinator and agent journal deliberately do not retain live process
objects.  A supervisor has one narrowly scoped job: persist a fully specified
launch before creating its process group and report only facts it owns.  It is
private queue application infrastructure; pipeline execution never imports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
from multiprocessing.connection import Client, Listener
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
from time import monotonic, sleep
from typing import Mapping, cast
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
            raise AgentProcessSupervisorError(
                "resident worker launch profile is unavailable"
            )
        try:
            descriptor = freeze_plain_data(self.descriptor, path="resident profile")
        except ValueError as exc:
            raise AgentProcessSupervisorError(str(exc)) from exc
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "python_executable", executable)
        object.__setattr__(
            self, "descriptor", thaw_plain_data(descriptor, path="resident profile")
        )

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                "project_root": str(self.project_root),
                "python_executable": str(self.python_executable),
                "descriptor": self.descriptor,
            }
        )

    @property
    def profile_id(self) -> str:
        value = self.descriptor.get("profile_id")
        if not isinstance(value, str) or not value:
            raise AgentProcessSupervisorError("resident profile ID is invalid")
        return value


@dataclass(frozen=True, slots=True)
class SupervisorLaunchConfiguration:
    """The complete, canonical resident profile set bound to one supervisor."""

    agent_id: str
    profiles: tuple[ResidentWorkerLaunchProfile, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise AgentProcessSupervisorError("supervisor agent ID is invalid")
        profiles = tuple(sorted(self.profiles, key=lambda item: item.profile_id))
        if not profiles or any(
            not isinstance(item, ResidentWorkerLaunchProfile) for item in profiles
        ):
            raise AgentProcessSupervisorError("supervisor profile set is invalid")
        if len({item.profile_id for item in profiles}) != len(profiles) or len(
            {item.fingerprint for item in profiles}
        ) != len(profiles):
            raise AgentProcessSupervisorError("supervisor profiles must be unique")
        object.__setattr__(self, "profiles", profiles)

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                "agent_id": self.agent_id,
                "profiles": [
                    {"profile_id": item.profile_id, "fingerprint": item.fingerprint}
                    for item in self.profiles
                ],
            }
        )


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
            "supervisor_id",
            "continuity_epoch",
            "agent_id",
            "session_id",
            "assignment_id",
            "process_execution_id",
            "execution_fence",
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
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise AgentProcessSupervisorError("resident launch environment is invalid")
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "environment", environment)

    @property
    def spec_digest(self) -> str:
        return _digest(
            {
                "supervisor_id": self.supervisor_id,
                "continuity_epoch": self.continuity_epoch,
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                "assignment_id": self.assignment_id,
                "process_execution_id": self.process_execution_id,
                "execution_fence": self.execution_fence,
                "launch_operation_id": self.launch_operation_id,
                "workspace_root": str(self.workspace_root),
                "profile_id": self.profile.profile_id,
                "profile_fingerprint": self.profile.fingerprint,
                "profile": _profile_value(self.profile),
                "environment": self.environment,
            }
        )


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

    _SCHEMA_VERSION = 2

    def __init__(
        self,
        root: Path,
        *,
        agent_id: str,
        profiles: tuple[ResidentWorkerLaunchProfile, ...],
        initialize: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self._configuration = SupervisorLaunchConfiguration(agent_id, profiles)
        self._agent_id = self._configuration.agent_id
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._path = self.root / "supervisor.sqlite"
        if initialize:
            self._initialize()
        self._open()

    @classmethod
    def initialize(
        cls,
        agent_root: Path,
        *,
        agent_id: str,
        profiles: tuple[ResidentWorkerLaunchProfile, ...],
    ) -> "AgentProcessSupervisor":
        root = Path(agent_root).resolve() / "supervisor"
        if root.exists():
            raise AgentProcessSupervisorError("supervisor root already exists")
        root.mkdir(mode=0o700, parents=False)
        return cls(root, agent_id=agent_id, profiles=profiles, initialize=True)

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
            conn.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (
                    ("schema_version", str(self._SCHEMA_VERSION)),
                    ("supervisor_id", f"supervisor-{uuid4()}"),
                    ("agent_id", self._agent_id),
                    ("configuration_fingerprint", self._configuration.fingerprint),
                    ("continuity_epoch", f"supervisor-epoch-{uuid4()}"),
                ),
            )
            conn.commit()
        self._path.chmod(0o600)

    def _open(self) -> None:
        if not self._path.is_file():
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )
        try:
            with self._connect() as conn:
                values = {
                    str(row["key"]): str(row["value"])
                    for row in conn.execute("SELECT key, value FROM metadata")
                }
        except sqlite3.Error as exc:
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            ) from exc
        if (
            values.get("schema_version") != str(self._SCHEMA_VERSION)
            or values.get("agent_id") != self._agent_id
            or values.get("configuration_fingerprint")
            != self._configuration.fingerprint
        ):
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )
        self.supervisor_id = values.get("supervisor_id", "")
        self.continuity_epoch = values.get("continuity_epoch", "")
        if not self.supervisor_id or not self.continuity_epoch:
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )

    def launch(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        self._validate_launch(launch)
        encoded = _launch_json(launch)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM launches WHERE operation_id = ?",
                (launch.launch_operation_id,),
            ).fetchone()
            if row is not None:
                if str(row["digest"]) != launch.spec_digest:
                    raise AgentProcessSupervisorError(
                        "launch operation conflicts with durable identity"
                    )
                return self._receipt(launch, row)
            conn.execute(
                "INSERT INTO launches(operation_id, digest, launch_json, state, revision) VALUES (?, ?, ?, ?, 1)",
                (
                    launch.launch_operation_id,
                    launch.spec_digest,
                    encoded,
                    SupervisorLaunchState.STARTING.value,
                ),
            )
            conn.commit()
        # The complete permitted environment is part of the durable launch
        # identity.  Do not merge ambient service state at the spawn boundary.
        environment = dict(launch.environment)
        gate = launch.workspace_root / "run.grant"
        gate.write_text("granted\n", encoding="utf-8")
        try:
            child = subprocess.Popen(
                [
                    str(launch.profile.python_executable),
                    "-m",
                    "loom.queue._resident_stage_worker",
                    "--workspace",
                    str(launch.workspace_root),
                ],
                cwd=launch.profile.project_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE launches SET state = ?, revision = revision + 1 WHERE operation_id = ?",
                    (SupervisorLaunchState.UNKNOWN.value, launch.launch_operation_id),
                )
                conn.commit()
            raise AgentProcessSupervisorError("resident root was not created") from exc
        self._children[launch.launch_operation_id] = child
        with self._connect() as conn:
            conn.execute(
                "UPDATE launches SET state = ?, pid = ?, revision = revision + 1 WHERE operation_id = ?",
                (
                    SupervisorLaunchState.RUNNING.value,
                    child.pid,
                    launch.launch_operation_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM launches WHERE operation_id = ?",
                (launch.launch_operation_id,),
            ).fetchone()
            conn.commit()
        return self._receipt(launch, row)

    def query(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        self._validate_launch(launch)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM launches WHERE operation_id = ?",
                (launch.launch_operation_id,),
            ).fetchone()
            if row is None:
                return SupervisorReceipt(SupervisorLaunchState.NOT_ACCEPTED, launch, 0)
            if str(row["digest"]) != launch.spec_digest:
                raise AgentProcessSupervisorError(
                    "launch query conflicts with durable identity"
                )
            child = self._children.get(launch.launch_operation_id)
            if child is not None:
                code = child.poll()
                if code is not None and str(row["state"]) in {
                    SupervisorLaunchState.STARTING.value,
                    SupervisorLaunchState.RUNNING.value,
                }:
                    result = launch.workspace_root / "worker-result.json"
                    digest = _file_digest(result) if result.is_file() else None
                    conn.execute(
                        "UPDATE launches SET state = ?, exit_code = ?, result_digest = ?, revision = revision + 1 WHERE operation_id = ?",
                        (
                            SupervisorLaunchState.EXITED.value,
                            code,
                            digest,
                            launch.launch_operation_id,
                        ),
                    )
                    conn.commit()
                    row = conn.execute(
                        "SELECT * FROM launches WHERE operation_id = ?",
                        (launch.launch_operation_id,),
                    ).fetchone()
            elif str(row["state"]) in {
                SupervisorLaunchState.STARTING.value,
                SupervisorLaunchState.RUNNING.value,
            }:
                # An agent can restart only against a continuously running supervisor
                # service.  This object has no evidence that a raw retained PID is ours.
                conn.execute(
                    "UPDATE launches SET state = ?, revision = revision + 1 WHERE operation_id = ?",
                    (SupervisorLaunchState.UNKNOWN.value, launch.launch_operation_id),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM launches WHERE operation_id = ?",
                    (launch.launch_operation_id,),
                ).fetchone()
            return self._receipt(launch, row)

    def contain(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        receipt = self.query(launch)
        child = self._children.get(launch.launch_operation_id)
        if child is None:
            return receipt
        # A root wait/result is deliberately not containment evidence: a child
        # can outlive its root.  The service owns the original process-group ID
        # and proves that group has vanished after bounded TERM/KILL escalation.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            return SupervisorReceipt(
                SupervisorLaunchState.UNKNOWN, launch, receipt.supervisor_revision
            )
        deadline = monotonic() + 2
        while _process_group_alive(child) and monotonic() < deadline:
            sleep(0.02)
        if _process_group_alive(child):
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                return SupervisorReceipt(
                    SupervisorLaunchState.UNKNOWN, launch, receipt.supervisor_revision
                )
            deadline = monotonic() + 2
            while _process_group_alive(child) and monotonic() < deadline:
                sleep(0.02)
        if _process_group_alive(child):
            return SupervisorReceipt(
                SupervisorLaunchState.UNKNOWN, launch, receipt.supervisor_revision
            )
        child.poll()
        result = launch.workspace_root / "worker-result.json"
        with self._connect() as conn:
            conn.execute(
                "UPDATE launches SET state = ?, exit_code = ?, result_digest = ?, revision = revision + 1 WHERE operation_id = ?",
                (
                    SupervisorLaunchState.CONTAINED.value,
                    child.returncode,
                    _file_digest(result) if result.is_file() else None,
                    launch.launch_operation_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM launches WHERE operation_id = ?",
                (launch.launch_operation_id,),
            ).fetchone()
        return self._receipt(launch, row)

    def _validate_launch(self, launch: ResidentWorkerLaunch) -> None:
        if (
            launch.supervisor_id != self.supervisor_id
            or launch.continuity_epoch != self.continuity_epoch
            or launch.agent_id != self._agent_id
            or not any(
                item.profile_id == launch.profile.profile_id
                and item.fingerprint == launch.profile.fingerprint
                for item in self._configuration.profiles
            )
        ):
            raise AgentProcessSupervisorError("supervisor launch identity mismatch")

    @staticmethod
    def _receipt(launch: ResidentWorkerLaunch, row: sqlite3.Row) -> SupervisorReceipt:
        return SupervisorReceipt(
            SupervisorLaunchState(str(row["state"])),
            launch,
            int(row["revision"]),
            cast_int(row["pid"]),
            cast_int(row["exit_code"]),
            str(row["result_digest"]) if row["result_digest"] is not None else None,
        )


def cast_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | str):
        return int(value)
    raise AgentProcessSupervisorError("supervisor receipt contains an invalid PID")


def _launch_json(launch: ResidentWorkerLaunch) -> str:
    return json.dumps(_launch_value(launch), sort_keys=True, separators=(",", ":"))


def _profile_value(profile: ResidentWorkerLaunchProfile) -> dict[str, object]:
    return {
        "project_root": str(profile.project_root),
        "python_executable": str(profile.python_executable),
        "descriptor": profile.descriptor,
    }


def _profile_from_value(value: object) -> ResidentWorkerLaunchProfile:
    if not isinstance(value, Mapping) or set(value) != {
        "project_root",
        "python_executable",
        "descriptor",
    }:
        raise AgentProcessSupervisorError("supervisor profile state is invalid")
    return ResidentWorkerLaunchProfile(
        project_root=Path(cast(str, value["project_root"])),
        python_executable=Path(cast(str, value["python_executable"])),
        descriptor=cast(Mapping[str, PlainData], value["descriptor"]),
    )


def _launch_value(launch: ResidentWorkerLaunch) -> dict[str, object]:
    return {
        "supervisor_id": launch.supervisor_id,
        "continuity_epoch": launch.continuity_epoch,
        "agent_id": launch.agent_id,
        "session_id": launch.session_id,
        "assignment_id": launch.assignment_id,
        "process_execution_id": launch.process_execution_id,
        "execution_fence": launch.execution_fence,
        "launch_operation_id": launch.launch_operation_id,
        "workspace_root": str(launch.workspace_root),
        "profile": _profile_value(launch.profile),
        "environment": dict(launch.environment),
    }


def _launch_from_value(value: object) -> ResidentWorkerLaunch:
    fields = {
        "supervisor_id",
        "continuity_epoch",
        "agent_id",
        "session_id",
        "assignment_id",
        "process_execution_id",
        "execution_fence",
        "launch_operation_id",
        "workspace_root",
        "profile",
        "environment",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AgentProcessSupervisorError("supervisor launch request is invalid")
    environment = value["environment"]
    if not isinstance(environment, Mapping):
        raise AgentProcessSupervisorError("supervisor launch environment is invalid")
    return ResidentWorkerLaunch(
        supervisor_id=cast(str, value["supervisor_id"]),
        continuity_epoch=cast(str, value["continuity_epoch"]),
        agent_id=cast(str, value["agent_id"]),
        session_id=cast(str, value["session_id"]),
        assignment_id=cast(str, value["assignment_id"]),
        process_execution_id=cast(str, value["process_execution_id"]),
        execution_fence=cast(str, value["execution_fence"]),
        launch_operation_id=cast(str, value["launch_operation_id"]),
        workspace_root=Path(cast(str, value["workspace_root"])),
        profile=_profile_from_value(value["profile"]),
        environment={
            cast(str, key): cast(str, item) for key, item in environment.items()
        },
    )


def _receipt_value(receipt: SupervisorReceipt) -> dict[str, object]:
    return {
        "state": receipt.state.value,
        "launch": _launch_value(receipt.launch),
        "supervisor_revision": receipt.supervisor_revision,
        "process_id": receipt.process_id,
        "exit_code": receipt.exit_code,
        "worker_result_digest": receipt.worker_result_digest,
    }


def _receipt_from_value(value: object) -> SupervisorReceipt:
    if not isinstance(value, Mapping) or set(value) != {
        "state",
        "launch",
        "supervisor_revision",
        "process_id",
        "exit_code",
        "worker_result_digest",
    }:
        raise AgentProcessSupervisorError("supervisor receipt is invalid")
    return SupervisorReceipt(
        SupervisorLaunchState(cast(str, value["state"])),
        _launch_from_value(value["launch"]),
        cast_int(value["supervisor_revision"]) or 0,
        cast_int(value["process_id"]),
        cast_int(value["exit_code"]),
        cast(str | None, value["worker_result_digest"]),
    )


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_alive(child: subprocess.Popen[bytes]) -> bool:
    """Reap our leader before using the group as descendant evidence.

    A killed leader remains a zombie until its owning service reaps it, and a
    zombie still makes ``killpg(..., 0)`` report a group.  Reaping first does
    not weaken containment: any living descendant remains in the original
    group and keeps the group observable.
    """

    child.poll()
    return _process_group_exists(child.pid)


class AgentProcessSupervisorClient:
    """Authenticated private client for the independent process owner.

    This is intentionally not an HTTP/public queue protocol.  The endpoint and
    random verifier are protected root state; an agent application only proves
    it is talking to the continuous service selected during initialization.
    """

    def __init__(
        self, agent_root: Path, configuration: SupervisorLaunchConfiguration
    ) -> None:
        self._root = Path(agent_root).resolve() / "supervisor"
        self._configuration = configuration
        self.agent_id = configuration.agent_id
        self._endpoint = _endpoint_for_root(self._root)
        secret = self._root / "service.secret"
        if not secret.is_file() or secret.stat().st_mode & 0o077:
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )
        self._secret = secret.read_bytes()
        if len(self._secret) != 32:
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )
        status = self.status()
        if status.get("configuration_fingerprint") != configuration.fingerprint:
            raise AgentProcessSupervisorError(
                "managed_supervisor_state_requires_reinitialization"
            )
        self.supervisor_id = _required_string(status, "supervisor_id")
        self.continuity_epoch = _required_string(status, "continuity_epoch")

    def status(self) -> Mapping[str, object]:
        value = self._call("status", None)
        if not isinstance(value, Mapping):
            raise AgentProcessSupervisorError("managed supervisor response is invalid")
        return value

    def launch(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        return _receipt_from_value(self._call("launch", _launch_value(launch)))

    def query(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        return _receipt_from_value(self._call("query", _launch_value(launch)))

    def request_stop(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        return _receipt_from_value(self._call("request_stop", _launch_value(launch)))

    def contain(self, launch: ResidentWorkerLaunch) -> SupervisorReceipt:
        return _receipt_from_value(self._call("contain", _launch_value(launch)))

    def shutdown_for_test(self) -> None:
        self._call("shutdown", None)

    def _call(self, operation: str, value: object) -> object:
        if not self._endpoint.exists():
            raise AgentProcessSupervisorError(
                "managed supervisor endpoint is unavailable"
            )
        try:
            connection = Client(
                str(self._endpoint), family="AF_UNIX", authkey=self._secret
            )
            connection.send({"operation": operation, "value": value})
            result = connection.recv()
            connection.close()
        except (OSError, EOFError, ConnectionError) as exc:
            raise AgentProcessSupervisorError(
                "managed supervisor endpoint is unavailable"
            ) from exc
        if not isinstance(result, Mapping):
            raise AgentProcessSupervisorError("managed supervisor response is invalid")
        if result.get("ok") is not True:
            message = result.get("error")
            raise AgentProcessSupervisorError(
                message
                if isinstance(message, str)
                else "managed supervisor operation failed"
            )
        return result.get("value")


class AgentProcessSupervisorService:
    """Fresh-root initialization and independent service entry point."""

    _CONFIG_NAME = "service-config.json"

    @classmethod
    def initialize(
        cls, agent_root: Path, *, configuration: SupervisorLaunchConfiguration
    ) -> AgentProcessSupervisorClient:
        root = Path(agent_root).resolve() / "supervisor"
        if root.exists():
            raise AgentProcessSupervisorError("supervisor root already exists")
        root.mkdir(mode=0o700)
        # The database is initialized before the endpoint can exist, so launch
        # acceptance is always durable before a service accepts a request.
        AgentProcessSupervisor(
            root,
            agent_id=configuration.agent_id,
            profiles=configuration.profiles,
            initialize=True,
        )
        config_path = root / cls._CONFIG_NAME
        config_path.write_text(
            json.dumps(
                {
                    "agent_id": configuration.agent_id,
                    "profiles": [
                        _profile_value(profile) for profile in configuration.profiles
                    ],
                    "configuration_fingerprint": configuration.fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        secret = root / "service.secret"
        secret.write_bytes(secrets.token_bytes(32))
        secret.chmod(0o600)
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "loom.queue._agent_process_supervisor",
                "--serve",
                str(root),
            ],
            cwd=str(Path.cwd()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = monotonic() + 5
        while True:
            try:
                client = AgentProcessSupervisorClient(agent_root, configuration)
                return client
            except AgentProcessSupervisorError:
                if monotonic() >= deadline:
                    raise AgentProcessSupervisorError(
                        "managed supervisor endpoint is unavailable"
                    )
                sleep(0.02)


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise AgentProcessSupervisorError("managed supervisor response is invalid")
    return item


def _service_configuration(root: Path) -> SupervisorLaunchConfiguration:
    config = root / AgentProcessSupervisorService._CONFIG_NAME
    try:
        value = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AgentProcessSupervisorError(
            "managed_supervisor_state_requires_reinitialization"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or set(value) != {"agent_id", "profiles", "configuration_fingerprint"}
        or not isinstance(value["profiles"], list)
    ):
        raise AgentProcessSupervisorError(
            "managed_supervisor_state_requires_reinitialization"
        )
    configuration = SupervisorLaunchConfiguration(
        cast(str, value["agent_id"]),
        tuple(_profile_from_value(item) for item in value["profiles"]),
    )
    if value["configuration_fingerprint"] != configuration.fingerprint:
        raise AgentProcessSupervisorError(
            "managed_supervisor_state_requires_reinitialization"
        )
    return configuration


def _serve(root: Path) -> None:
    root = Path(root).resolve()
    lock_path = root / "service.lock"
    lock = lock_path.open("a+", encoding="utf-8")
    lock_path.chmod(0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise AgentProcessSupervisorError(
            "managed supervisor service is already running"
        ) from exc
    configuration = _service_configuration(root)
    supervisor = AgentProcessSupervisor(
        root, agent_id=configuration.agent_id, profiles=configuration.profiles
    )
    secret = (root / "service.secret").read_bytes()
    endpoint = _endpoint_for_root(root)
    if endpoint.exists():
        endpoint.unlink()
    listener = Listener(str(endpoint), family="AF_UNIX", authkey=secret)
    endpoint.chmod(0o600)
    running = True
    try:
        while running:
            connection = listener.accept()
            try:
                request = connection.recv()
                if not isinstance(request, Mapping):
                    raise AgentProcessSupervisorError(
                        "managed supervisor request is invalid"
                    )
                operation = request.get("operation")
                launch = (
                    _launch_from_value(request["value"])
                    if operation in {"launch", "query", "request_stop", "contain"}
                    else None
                )
                if operation == "status":
                    response: object = {
                        "supervisor_id": supervisor.supervisor_id,
                        "continuity_epoch": supervisor.continuity_epoch,
                        "configuration_fingerprint": configuration.fingerprint,
                    }
                elif operation == "launch":
                    response = _receipt_value(
                        supervisor.launch(cast(ResidentWorkerLaunch, launch))
                    )
                elif operation == "query":
                    response = _receipt_value(
                        supervisor.query(cast(ResidentWorkerLaunch, launch))
                    )
                elif operation == "request_stop":
                    current = supervisor.query(cast(ResidentWorkerLaunch, launch))
                    child = supervisor._children.get(
                        cast(ResidentWorkerLaunch, launch).launch_operation_id
                    )
                    if child is not None and child.poll() is None:
                        try:
                            os.killpg(child.pid, signal.SIGTERM)
                        except OSError:
                            pass
                    response = _receipt_value(current)
                elif operation == "contain":
                    response = _receipt_value(
                        supervisor.contain(cast(ResidentWorkerLaunch, launch))
                    )
                elif operation == "shutdown":
                    response = None
                    running = False
                else:
                    raise AgentProcessSupervisorError(
                        "managed supervisor operation is invalid"
                    )
                connection.send({"ok": True, "value": response})
            except (
                AgentProcessSupervisorError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                connection.send({"ok": False, "error": str(exc)})
            finally:
                connection.close()
    finally:
        listener.close()
        if endpoint.exists():
            endpoint.unlink()
        lock.close()


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", type=Path, required=True)
    arguments = parser.parse_args()
    _serve(arguments.serve)
    return 0


def _endpoint_for_root(root: Path) -> Path:
    # Unix-domain paths have a short platform limit; derive a stable private
    # endpoint name from the protected canonical root rather than truncating a
    # user-controlled path.
    digest = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    return Path(tempfile.gettempdir()) / f"loom-supervisor-{digest[:24]}.sock"


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "AgentProcessSupervisor",
    "AgentProcessSupervisorClient",
    "AgentProcessSupervisorError",
    "AgentProcessSupervisorService",
    "ResidentWorkerLaunch",
    "ResidentWorkerLaunchProfile",
    "SupervisorLaunchConfiguration",
    "SupervisorLaunchState",
    "SupervisorReceipt",
]


if __name__ == "__main__":  # pragma: no cover - independently process-owned.
    raise SystemExit(_main())
