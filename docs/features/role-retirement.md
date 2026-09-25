# Explicit role retirement

Retirement prepares an idle native role for operator-owned removal. It does not
delete files, uninstall software, revoke TLS credentials or cancel experiments.
The downstream fleet launcher owns those actions and their filesystem scope.

For a drained, stopped outbound agent, while its credentials are still accepted:

```sh
loom queue agent-retire /PRIVATE/agent.yaml --env-file /PRIVATE/machine.env \
  --operation-id REMOVE_ID --expected-coordinator-id COORDINATOR_ID \
  --session-id SESSION_ID --format json
```

`loom.queue.retirement.retire_outbound_agent` uses the native journal lock,
retained-assignment/provider checks, clean supervisor shutdown and authenticated
session retirement. A busy or uncertain owner refuses. It can open only existing
initialized state and may restart a provably empty initialized supervisor to
complete its native shutdown protocol. It does not start an agent polling loop.
Keep the coordinator available and the agent's credentials authorized until the
receipt is returned; revocation belongs after native `RETIRED_CLEAN` confirmation.

For an idle **pure coordinator**, after all agents retire:

```sh
loom queue daemon-retire --endpoint /LOCAL/daemon.sock \
  --operation-id REMOVE_ID --expected-coordinator-id COORDINATOR_ID --format json
```

The same operation is `LocalDaemonSocketClient.retire`. It requires the existing
local-owner `scheduling_reload` authorization. Under the application cycle lock,
it checks all accepted-work owners, startup attachments and remote sessions,
then permanently fences new acceptance and registration. This is not a status
snapshot followed by a later unguarded shutdown. Embedded local agents are not
supported by this operator removal surface.

`LocalDaemonSocketClient.agent_retirement_ready(agent_id, session_id)` requires
the existing scoped drain authorization and observes coordinator-side references
only. It never substitutes for worker-side retirement/shutdown proof.

Both roles persist a `role_retirement` receipt in their existing native root
metadata. The receipt is the irreversible reuse fence for this operation, not a
second scheduling inventory. The same request replays; conflicting identities
or operation IDs fail. Normal serve/register cannot restart an explicitly
retired role. There is no automatic undo or reinitialization over old roots.

`retired_role_guard(root, receipt)` holds the exact root's native ownership lock
(and supervisor lock where present) while the caller disposes of that root.
Callers must still stop the foreground service, verify their selected paths and
exclude shared datasets, outputs, installations and other roles. A receipt alone
does not authorize arbitrary filesystem deletion.

Scheduling reload may remove a policy rule belonging to cleanly retired sessions
without disrupting other active agents. Existing live rules and policy revision
remain unchanged. Capacity removal separately checks the removed namespaces'
retained reservations; it never drops claims owned by another active worker.
