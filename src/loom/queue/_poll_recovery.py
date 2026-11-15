"""Explicit stopped-agent recovery of a proven no-delivery poll conflict."""
from __future__ import annotations

from typing import cast

from ._agent_session_journal import _RemoteAgentJournal
from .errors import QueueConflictError, QueueServiceError


def recover_wait_poll(config, *, operation_id, sequence, committed_revision, wait_timeout_ms):
    """Settle only a conflicting capacity revision with an exact committed WAIT.

    The native agent owner lock is held throughout authenticated observation and
    the local transaction. No work is polled, no claims are released, and no
    supervisor is started. The completed receipt supports lost-reply replay.
    """
    from .agent_session_transport import AgentTlsClientConfig, LocalDaemonAgentHttpClient

    if (not isinstance(operation_id, str) or not operation_id.strip()
            or not isinstance(committed_revision, str) or not committed_revision.strip()
            or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1):
        raise QueueServiceError("poll recovery requires an operation, revision and positive sequence")
    if config.agent_root is None:
        raise QueueServiceError("poll recovery requires an existing agent root")
    selection = {"sequence": sequence, "committed_revision": committed_revision,
                 "wait_timeout_ms": wait_timeout_ms}
    journal = _RemoteAgentJournal(
        config.agent_root,
        expected_configuration_fingerprint=config.deployment_configuration_fingerprint,
        expected_active_configuration_fingerprint=config.active_configuration_fingerprint,
    )
    try:
        receipt = journal.poll_recovery_receipt(operation_id, selection)
        if receipt is not None:
            return receipt
        retained = journal.recovery_poll(wait_timeout_ms)
        if retained is None:
            raise QueueConflictError("no unresolved poll to recover")
        _, pending = retained
        if pending["sequence"] != sequence or pending["availability_revision"] == committed_revision:
            raise QueueConflictError("poll recovery requires the selected conflicting sequence")
        session = journal.session(cast(str, pending["session_id"]))
        # A transport-only client cannot initialize or own execution roots.
        transport = AgentTlsClientConfig(
            config.url, config.server_ca_path, config.certificate_path, config.private_key_path,
        )
        client = LocalDaemonAgentHttpClient(transport)
        try:
            handshake = client.handshake()
            if handshake["coordinator_id"] != session.coordinator_id:
                raise QueueConflictError("poll recovery coordinator identity changed")
            proof = client._call("recover_poll", {
                **pending, "availability_revision": committed_revision,
                "coordinator_epoch": session.coordinator_epoch,
            })
        finally:
            client.close()
        if (proof.get("state") != "committed" or proof.get("result") != "wait"
                or proof.get("sequence") != sequence
                or proof.get("coordinator_epoch") != session.coordinator_epoch):
            raise QueueConflictError("poll recovery requires an exact committed no-delivery receipt")
        return journal.settle_rejected_poll(operation_id, selection, pending, dict(proof))
    finally:
        journal.close()
