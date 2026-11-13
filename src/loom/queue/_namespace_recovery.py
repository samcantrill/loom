"""Explicit cancellation-only recovery of one stranded resident PID namespace.

This is operator authority to terminate a freshly identified boundary, never
permission to adopt it for execution. The agent must be stopped. Both process
birth ticks and the Linux boot are explicit preconditions; completed proof is
retained locally before ordinary coordinator recovery can release any claim.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
from time import monotonic, sleep

from .errors import QueueConflictError, QueueServiceError


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int


def _facts(pid: int) -> dict:
    root = Path(f"/proc/{pid}")
    raw = (root / "stat").read_text()
    values = raw[raw.rindex(")") + 2:].split()
    status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines())
    return {
        "pid": pid, "start_ticks": int(values[19]), "state": values[0],
        "parent": int(values[1]), "group": int(values[2]), "session": int(values[3]),
        "uid": tuple(map(int, status["Uid"].split())),
        "namespace_pids": tuple(map(int, status["NSpid"].split())),
    }


def _children(pid: int) -> set[int]:
    return {int(child) for path in Path(f"/proc/{pid}/task").glob("*/children")
            for child in path.read_text().split()}


def _ready(fd: int) -> bool:
    return bool(select.select([fd], [], [], 0)[0])


class _PinnedProcess:
    def __init__(self, identity: ProcessIdentity):
        self.identity = identity
        self.fd = os.pidfd_open(identity.pid)
        self.stopped = False
        try:
            self.check()
            signal.pidfd_send_signal(self.fd, 0)
        except BaseException:
            os.close(self.fd)
            raise

    def check(self) -> dict:
        facts = _facts(self.identity.pid)
        if (facts["start_ticks"] != self.identity.start_ticks or _ready(self.fd)
                or any(uid != os.getuid() for uid in facts["uid"])):
            raise QueueConflictError("namespace recovery process identity changed")
        return facts

    def stop(self) -> None:
        self.check()
        signal.pidfd_send_signal(self.fd, signal.SIGSTOP)
        self.stopped = True
        deadline = monotonic() + 5
        while True:
            self.check()
            tasks = tuple(Path(f"/proc/{self.identity.pid}/task").glob("*/status"))
            if tasks and all(dict(line.split(":", 1) for line in p.read_text().splitlines())["State"].strip().startswith("T") for p in tasks):
                return
            if monotonic() >= deadline:
                raise QueueConflictError("namespace recovery stop observation incomplete")
            sleep(0.02)

    def kill_and_observe(self) -> None:
        self.check()
        signal.pidfd_send_signal(self.fd, signal.SIGKILL)
        if not select.select([self.fd], [], [], 10)[0]:
            raise QueueConflictError("namespace recovery containment observation incomplete")

    def close(self) -> None:
        try:
            if self.stopped and not _ready(self.fd):
                signal.pidfd_send_signal(self.fd, signal.SIGCONT)
        except ProcessLookupError:
            pass
        finally:
            os.close(self.fd)


def _receipt(conn, operation_id, intent):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='namespace_recoveries'").fetchone():
        return None
    row = conn.execute("SELECT intent, result FROM namespace_recoveries WHERE operation_id=?", (operation_id,)).fetchone()
    if row is None:
        return None
    if row[0] != intent:
        raise QueueConflictError("namespace recovery operation conflicts")
    if row[1] is None:
        raise QueueConflictError("namespace recovery was interrupted; retain claims and proof")
    return json.loads(row[1])


def _selection(conn, assignment_id, supervisor_id, generation, root, boot):
    from ._agent_process_supervisor import _launch_from_value

    metadata = dict(conn.execute("SELECT key, value FROM metadata"))
    if (metadata["supervisor_id"] != supervisor_id
            or metadata["continuity_epoch"] != generation
            or metadata.get("execution_root") != str(root)
            or json.loads(metadata.get("boot_evidence", "null")) != boot):
        raise QueueConflictError("namespace recovery supervisor identity changed")
    rows = conn.execute("SELECT * FROM launches WHERE state != 'contained'").fetchall()
    if len(rows) != 1:
        raise QueueConflictError("namespace recovery requires exactly one unresolved launch")
    row = rows[0]
    launch = _launch_from_value(json.loads(row["launch_json"]))
    if (launch.assignment_id != assignment_id or launch.backend_kind != "apptainer"
            or row["digest"] != launch.spec_digest or launch.continuity_epoch != generation
            or launch.supervisor_id != supervisor_id or launch.agent_id != metadata["agent_id"]):
        raise QueueConflictError("namespace recovery launch identity mismatch")
    return row, launch


def _recover(root, agent_id, *, operation_id, assignment_id, boot_id,
             supervisor: ProcessIdentity, launcher: ProcessIdentity, namespace: ProcessIdentity):
    from ._agent_process_supervisor import _SupervisorControlClient, _host_boot_evidence, _service_configuration

    root = Path(root).resolve()
    boot = _host_boot_evidence()
    if boot["boot"] != boot_id:
        raise QueueConflictError("namespace recovery Linux boot changed")
    intent = json.dumps({"root": str(root), "agent_id": agent_id, "assignment_id": assignment_id,
                         "boot": boot, "supervisor": vars(supervisor), "launcher": vars(launcher),
                         "namespace": vars(namespace)}, sort_keys=True)
    database = root / "supervisor.sqlite"
    if not database.is_file():
        raise QueueServiceError("namespace recovery requires an existing supervisor")
    with sqlite3.connect(database, timeout=2) as conn:
        conn.row_factory = sqlite3.Row
        prior = _receipt(conn, operation_id, intent)
        if prior is not None:
            return prior
        configuration = _service_configuration(root)
        if configuration.agent_id != agent_id:
            raise QueueConflictError("namespace recovery agent identity mismatch")
        with ExitStack() as stack:
            owner = _PinnedProcess(supervisor)
            stack.callback(owner.close)
            client = _SupervisorControlClient(root.parent, agent_id, configuration.fingerprint)
            if client.service_process_id != supervisor.pid:
                raise QueueConflictError("namespace recovery endpoint owner changed")
            owner.check()
            row, launch = _selection(conn, assignment_id, client.supervisor_id, client.continuity_epoch, root, boot)
            if row["pid"] != launcher.pid:
                raise QueueConflictError("namespace recovery launcher differs from retained launch")
            parent = _PinnedProcess(launcher)
            stack.callback(parent.close)
            init = _PinnedProcess(namespace)
            stack.callback(init.close)
            # Quiesce both possible host-side spawners before taking the final
            # lineage snapshot. Every failure before proof resumes live owners.
            owner.stop()
            parent.stop()
            parent_facts, init_facts = parent.check(), init.check()
            if (parent_facts["parent"] != supervisor.pid
                    or parent_facts["group"] != launcher.pid
                    or parent_facts["session"] != launcher.pid
                    or init_facts["parent"] != launcher.pid
                    or init_facts["group"] != launcher.pid
                    or len(init_facts["namespace_pids"]) != len(parent_facts["namespace_pids"]) + 1
                    or init_facts["namespace_pids"][-1] != 1
                    or _children(supervisor.pid) != {launcher.pid}
                    or _children(launcher.pid) != {namespace.pid}):
                raise QueueConflictError("namespace recovery boundary is not isolated")
            row, launch = _selection(conn, assignment_id, client.supervisor_id, client.continuity_epoch, root, boot)
            conn.execute("CREATE TABLE IF NOT EXISTS namespace_recoveries (operation_id TEXT PRIMARY KEY, intent TEXT NOT NULL, launch_operation_id TEXT NOT NULL, result TEXT)")
            conn.execute("INSERT INTO namespace_recoveries VALUES (?, ?, ?, NULL)", (operation_id, intent, launch.launch_operation_id))
            conn.commit()
            # Namespace init exit tears down the namespace. Killing the pinned
            # host launcher afterwards cannot reopen it or select a reused PID.
            init.kill_and_observe()
            parent.kill_and_observe()
            owner.kill_and_observe()
            lock = stack.enter_context((root / "service.lock").open("a+"))
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueConflictError("namespace recovery supervisor lock is still owned") from exc
            conn.execute("BEGIN IMMEDIATE")
            row, launch = _selection(conn, assignment_id, client.supervisor_id, client.continuity_epoch, root, boot)
            result = {"operation_id": operation_id, "state": "contained", "assignment_id": assignment_id,
                      "launch_operation_id": launch.launch_operation_id, "supervisor_id": client.supervisor_id,
                      "generation": client.continuity_epoch, "boot": boot, "successful_exit": False}
            conn.execute("UPDATE launches SET state='contained', exit_code=NULL, successful_exit=0, revision=revision+1 WHERE operation_id=?", (launch.launch_operation_id,))
            conn.execute("INSERT INTO metadata VALUES ('clean_shutdown_epoch', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (client.continuity_epoch,))
            conn.execute("UPDATE namespace_recoveries SET result=? WHERE operation_id=?", (json.dumps(result), operation_id))
            conn.commit()
            return result


def recover_namespace(config, *, operation_id: str, assignment_id: str, boot_id: str,
                      supervisor: ProcessIdentity, launcher: ProcessIdentity, namespace: ProcessIdentity):
    """Contain one operator-selected namespace with the agent stopped.

    A completed receipt is replayable with exactly the same arguments. An
    interrupted destructive attempt retains claims and refuses to invent proof.
    This command starts no service and never releases or retries an assignment.
    """
    from ._agent_session_journal import _RemoteAgentJournal
    from ._managed_local import SQLiteAgentJournal
    from .agent_session_transport import _agent_active_fingerprint
    from ._agent_process_supervisor import AgentProcessSupervisorError

    if (not operation_id.strip() or not assignment_id.strip() or not boot_id.strip()
            or config.agent_root is None or config.slurm_profiles
            or len({supervisor.pid, launcher.pid, namespace.pid}) != 3
            or any(type(v) is not int or v <= 0 for p in (supervisor, launcher, namespace) for v in (p.pid, p.start_ticks))):
        raise QueueServiceError("namespace recovery requires an existing root and exact process identities")
    journal = _RemoteAgentJournal(config.agent_root,
        expected_configuration_fingerprint=config.deployment_configuration_fingerprint,
        expected_active_configuration_fingerprint=_agent_active_fingerprint(config))
    try:
        execution = SQLiteAgentJournal(Path(config.agent_root) / "journal.sqlite", _allow_initialize=False)
        execution._open_existing()
        execution.retained_claim_commands()
        return _recover(Path(config.agent_root).resolve() / "supervisor", journal.root_id,
                        operation_id=operation_id, assignment_id=assignment_id, boot_id=boot_id,
                        supervisor=supervisor, launcher=launcher, namespace=namespace)
    except (AgentProcessSupervisorError, OSError, sqlite3.Error) as exc:
        raise QueueServiceError(str(exc)) from exc
    finally:
        journal.close()
