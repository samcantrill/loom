# Native operator observations

`loom.coordinator.CoordinatorOperatorClient` connects explicitly as an operator
through `from_unix_socket` or `from_connection_file`. HTTPS uses the existing
protected connection-file format with an operator certificate; ordinary client
credentials do not gain operator privileges. Local Unix operators need the
existing explicit local-owner policy.

The client negotiates `operator-observations-v1`. A peer missing that capability
returns `unsupported_capability` and the missing capability name; there is no
SQL fallback. Existing client methods and their response shapes are unchanged.

- `observe_status()` exposes coordinator ID/epoch, accepted configuration revision
  and fingerprint, scheduling fingerprint/epoch, capabilities and native health.
  A fingerprint can be absent for programmatic configurations without a retained
  deployment declaration. The scheduling fingerprint remains separately named.
- `observe_agent(agent_id)` exposes root/session/config identities, connectivity,
  drain state, profile identities, offer revision, remaining resources and reasons.
  A connected agent can have CPU capacity while GPU capacity is externally occupied.
  Connectivity is the coordinator's current-epoch, unexpired offer evidence; it
  does not prove host process ownership. Drain withdrawal does not imply disconnect.
- `observe_assignment(assignment_id)` joins exactly one coordinator assignment
  with terminal acknowledgement, containment-control and release evidence. It
  never returns transfer paths, retirement secrets or an unbounded journal.
- `control_agent(control, expected_coordinator_id=...)` uses existing native
  drain/resume/reload authority and scopes. It carries the canonical intent digest,
  operation ID, session/config fences and required coordinator identity. Exact
  replay retains one effect; changed intent conflicts. `observe_control(id)`
  resolves the retained effect and digest after a lost response. Outcomes are
  `not_applied`, `applied` or `unknown`; `applied` means the control was committed,
  not that the agent finished processing it. Timeout is not permission to retry
  with another ID. Existing recovery, retirement and scheduling-reload APIs retain
  their native owners and authorization.

Every observation contains `owner`, UTC `observed_at`, owner-local `revision`
when known, `freshness`, `availability`, `value` and an optional `reason`. These
are independent observations, not an atomic fleet snapshot. Expired offers are
retained evidence and cannot authorize new work. An unreachable status returns
known coordinator identity and an explicit unavailable reason; if this client
previously read status, that last status is included as retained evidence with
its original observation timestamp. No durable client cache is written.

The corresponding CLI uses `queue daemon-status --operator`,
`queue daemon-agent AGENT --operator`, `queue daemon-assignment ASSIGNMENT`,
and `queue daemon-operation OPERATION --operator`, with the existing
`--endpoint` or `--connection` options. Drain/resume/reload support an operator
connection and `--expected-coordinator-id`; the established endpoint-only
invocation remains usable. `--format json` and text render the same projections.

Host-local read-only probes in `loom.queue.operations` provide independent facts:

- `inspect_native_service(root, expected_root_id=...)`, exposed as
  `queue daemon-owner --root ROOT`, compares retained root identity and the
  recorded process start ticks and Linux boot ID. PID existence alone is never
  ownership. Older process records without boot identity report unproven
  ownership. Service-manager state belongs to the external service manager.
- `inspect_local_assignment(root, assignment_id)`, exposed as
  `queue agent-assignment ASSIGNMENT --root ROOT`, reads one agent journal and
  the exact retained supervisor launch. Actual GPU UUIDs come from the started
  launch binding, not requested devices or current offers. Unknown, not-started
  or non-UUID bindings explicitly lack UUID proof. Terminal acknowledgement,
  process containment and provider release are independent fields. A successful
  run can still have an unreleased claim. The coordinator does not infer this
  host-local device proof from a connected session.
- `probe_upgrade_compatibility(root, required_capabilities=...)`, exposed as
  `queue daemon-upgrade-probe --root ROOT`, reports current/candidate storage
  versions, supported forward-only offline migration, protocol/capabilities and
  the requirement to preserve and separately qualify workload profile bindings.
  It neither migrates storage nor claims workload compatibility from service
  storage compatibility. Unsupported versions/capabilities have explicit reasons.

`loom.queue.deployment.inspect_role_declaration(path, role=..., env_file=...)`
and `queue daemon-check/agent-check --declaration-only` parse protected sources
and includes without importing workload factories, hashing images, initializing
roots or starting services. The declaration digest identifies parsed declarations,
not installation qualification. Output includes profile identities and the
protected-source result, with credentials and private paths omitted. Full
role-check qualification remains an explicit separate operation.
