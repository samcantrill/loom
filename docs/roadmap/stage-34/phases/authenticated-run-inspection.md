# Phase 2 Execution Plan: Authenticated Run Inspection

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 34, Phase 2
- Manifest: docs/roadmap/stage-34/implementation-plan.md
- Branch: agent/stage-34-p2-authenticated-run-inspection
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-34-p2-authenticated-run-inspection`
- Base revision: `0eb6a90df1517a0b51538241db8792359563e619`
- PR target: develop
- PR title: `Stage 34 phase 2: add authenticated run inspection`
- Dependencies: Phase 1 merged; existing Stage 29 mTLS server, certificate
  fingerprint mapping, current-policy authorizer, and protected config loader
- Workflow path: expanded; this phase changes an authenticated remote trust
  boundary and credential policy
- Blockers: none; Phase 1 is remotely merged in
  [#263](https://github.com/samcantrill/loom/pull/263)

## Objective And Context

- Vertical outcome: an authorized remote caller uses the same Python/CLI query
  and receives the Phase 1 model through a dedicated read-only mTLS credential;
  mutation roles cannot use the operation and query credentials cannot mutate.
- Earlier dependency: Phase 1 fixes projection/result/error codecs, the injected
  query callable, bounds, and `loom inspect-run` command.
- Later work explicitly out of scope: tenant or per-run ACLs, bearer tokens,
  hosted gateways, another server, SSH implementation, payload relay, streaming,
  subscriptions, dashboards, and coordinator federation.

## Current Source And Harness

- Relevant files and symbols: `LocalDaemonRole`, `TransportPrincipalPolicy`,
  `ScopedAuthorizer`, `LocalDaemonAgentHttpServer`, `_MutualTlsHttpServer`,
  `_dispatch_application`, coordinator protected configuration, TLS client call
  patterns, Phase 1 projection callable/model/CLI.
- Existing tests and seams: generated local CA/server/client certificates,
  fingerprint-to-principal mapping, role/path mismatch, live policy replacement,
  bounded strict JSON, safe HTTP errors, direct/HTTP application parity, and
  protected service-config permission tests.
- Import, dependency, or harness constraints: reuse stdlib TLS/HTTP and the
  existing server/process; transport receives plain data and must not import the
  diagnostics model; tests use localhost only and require no external network.

## Scope

In scope:

- Add `query` to the protected principal role vocabulary with no operator action,
  agent, pool, submit, cancel, recovery, authority, bootstrap, or transfer scope.
  Keep credentials role-exclusive and recheck the current policy on every call.
- Advertise/require `run-inspection-v1` and dispatch only
  `/v1/query/inspect_run` on the existing mTLS application server. Authenticate
  and authorize before admission lookup or projection invocation.
- Scope HTTP queries to exact runs admitted by that coordinator. Wrong role,
  certificate, path, capability, revoked policy, missing admission, malformed
  request, unavailable owner, and oversized response use the Phase 1 safe
  failure vocabulary/status mapping without exception/path leakage.
- Add a no-redirect HTTPS inspection client and strict protected
  `loom.run-inspection-client` v1 config containing URL and CA/certificate/key
  paths. Reuse protected ownership/mode and relative-path rules; never expose
  key material or credentials in argv/output.
- Add `--remote-config` to `loom inspect-run`, mutually exclusive with direct and
  Unix selectors, and deserialize the exact Phase 1 result. Unsupported old
  servers and all transport failures fail closed without local fallback.
- Complete managed local, authenticated remote, and service-less SSH
  documentation, including non-atomicity, freshness, truncation, location
  reachability, certificate-policy setup, and content-transfer limitations.

Out of scope:

- Reusing mutation-capable `client` credentials, request-body principals,
  authorization by network/loopback location, per-run grants, new CA issuance,
  automatic endpoint discovery, HTTP GET/query-string identities, retries that
  hide indeterminate transport failure, or changes to agent/operator/bootstrap
  semantics.

Assumptions:

- One query credential may inspect any run admitted to its configured
  coordinator; Loom has no tenant model. Site operators issue and protect
  certificates and decide whether returned `file://` locations are shared.
- Old coordinators do not implement the capability and are rejected rather than
  translated or bypassed.

## Fixed Contracts And Private Discretion

- Observable behavior: valid query role plus exact admitted run succeeds;
  authorization denial occurs before owner reads and reveals no run facts;
  policy revocation affects the next request; remote results equal Phase 1
  serialization; failures never trigger direct/Unix fallback.
- Public or durable shapes: `query` policy role, `run-inspection-v1` capability,
  `/v1/query/inspect_run`, strict request/error envelopes, protected client
  config v1, and `--remote-config`. Phase 1 result/CLI schemas do not change.
- Trust and failure boundaries: TLS derives credential from the verified client
  certificate; fingerprint policy derives principal/role; the authorizer checks
  current policy; request data selects only the already-authorized run URI.
- Cross-phase contracts: consumes Phase 1's callable/codecs/limits unchanged and
  completes the three-source parity/documentation gate.
- Reproducibility and compatibility: no remote query writes owner state; existing
  client/operator/agent/bootstrap operations and credentials retain behavior;
  current CLI schemas remain unchanged.
- Private choices the executor may simplify: client/helper filenames, internal
  TLS config factoring, HTTP status mapping within fixed safe codes, and prose
  placement.

## Proportionality

- Existing seam reused: mTLS server/socket, certificate fingerprints,
  `ScopedAuthorizer`, protected config parsing/permissions, HTTP client framing,
  injected Phase 1 query callable, and CLI source selection.
- Material additions and current justification: one non-mutating role/operation
  and one protected client config are necessary for least-privilege remote use.
- Optional hardening and future capability deferred: token/OIDC auth, ACL
  database, certificate automation, audit log, rate limiter, proxy deployment,
  HA, multi-coordinator search, payload streaming, and UI.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Transport identity comes only from mTLS | TLS server/fingerprint map | request path/body claims another principal | credential spoofing | body/path identity negatives and certificate matrix |
| Query role cannot mutate | protected policy and role dispatch | query credential calls submit/cancel/operator/agent path | unauthorized state change | full operation-denial matrix plus zero-mutation sentinels |
| Mutation roles cannot query | role-path match and authorizer | client/operator credential calls query path | least-privilege collapse | wrong-role denial before projection spy |
| Current policy gates every request | `ScopedAuthorizer` current config | credential revoked after prior success | stale authorization | success, policy replacement, immediate denial |
| Coordinator scope is exact | coordinator admission owner | valid query credential names unadmitted/local run | cross-boundary file inspection | admitted/not-found/local-sentinel cases |
| Remote wire equals local model | Phase 1 codec and HTTP adapter | adapter reshapes/accepts unknown fields | contract drift or leakage | direct/Unix/HTTP byte-equivalent canonical dict |
| Transport remains bounded/safe | HTTP framing and Phase 1 serializer | oversized/malformed input or secret exception | resource abuse or disclosure | size/depth/field/error matrix |

## Implementation Slices

1. Extend role/policy/config validation with the role-exclusive read-only query
   principal and focused authorizer tests.
2. Add capability negotiation and authenticated HTTP dispatch around the
   injected Phase 1 callable, enforcing auth-before-read and safe bounds/errors.
3. Add the protected HTTPS client config/loader and no-redirect typed client
   with certificate, permission, capability, and failure tests.
4. Wire CLI remote selection and complete three-source parity, compatibility,
   security, deployment, and SSH-invocation documentation.
5. Run targeted TLS/subprocess journeys, full gates, and expanded manager review;
   request independent review if any material auth/projection risk remains.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Auth/client additions stay import-safe and dependency-free | lazy diagnostics/CLI import and both builds |
| Unit | required | Role, policy, config, selector, codec/error behavior | role exclusivity, exact fields, protected permissions, no fallback |
| Contract | required | Phase 1 model and existing operations remain stable | result/error parity and unchanged agent/client/operator behavior |
| Integration | required | Real localhost mTLS boundary | cert/role/path/capability/revocation matrix and projection spies |
| E2E / opt-in | required local | Remote CLI journey | subprocess against local mTLS coordinator; real site issuance remains manual |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_deployment.py tests/unit/loom/cli/test_inspect_run.py
    uv run pytest tests/contracts/test_run_inspection_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue/test_agent_session_transport.py tests/integration/diagnostics/test_run_inspection.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: authorization after owner access, role confusion, stale policy,
  query-to-mutation reachability, unsafe exception mapping, fallback, or model
  drift over HTTP.
- Review focus: certificate-derived identity, exact role/path dispatch,
  auth-before-projection sentinels, live revocation, capability hard cut,
  protected config permissions, safe errors, and unchanged existing roles.
- Stop if: query must share a mutation credential; authorization needs request-
  supplied identity or a new auth/server stack; an unadmitted run can reach owner
  reads; Phase 1 schema/limits must change; or bytes/streaming become necessary.
- Accepted debt and revisit trigger: no tenant/per-run ACL or audit log; add only
  for a concrete multi-tenant or compliance consumer with an accepted owner.

## Executor Handoff

- Read section range: this entire phase plan; Stage 34 planning FQ-2, DQ-4/DQ-5,
  Minimum Design and validation; Phase 1 fixed contracts; Stage 29 transport and
  protected deployment documentation.
- Safe implementation slices: role/policy; server dispatch; client config/client;
  CLI/docs; focused and full validation.
- Decisions not to revisit: dedicated query role, coordinator-wide admitted-run
  scope, existing mTLS server, no fallback/bytes/new auth, unchanged Phase 1 model.
- Conditions requiring manager action: any stop condition, role/config/schema
  expansion, existing-operation compatibility change, or residual auth risk.

## Workflow State

- Manager preparation: complete; Phase 1 remote merge, exact base/worktree,
  current transport dispatch, policy seam, and protected config loader verified.
- Expanded planning: no planner pass needed. The existing mTLS handler resolves
  the certificate fingerprint through the current policy and enforces the
  mapped role/path before application dispatch, so an injected query callback
  can remain downstream of authorization without a contract change.
- Implementation: complete; the existing mTLS application server now composes
  the injected Phase 1 inspection callable behind the role-exclusive `query`
  principal, exact coordinator admission check, `run-inspection-v1` handshake,
  protected inspection-client config, and explicit CLI remote source.
- Refiner: not needed.
- Pre-submit gate: pending.
- Independent review: expected if manager review leaves any material
  authorization, redaction, or existing-role compatibility risk.
- Blocker corrections: 1/3 complete. The remote client applied the legacy
  agent-request decoder after reading a Phase 1-sized response, incorrectly
  closing valid 65+ record results as unavailable. The correction gives only
  query responses their fixed 1 MiB/256-record strict decoder, preserves the
  existing 64 KiB/64-item agent decoder for request and handshake traffic, and
  rejects wrong response content types or status/envelope combinations.
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added the dedicated `query` role, exact authenticated `/v1/query/inspect_run` dispatch, capability handshake, bounded no-redirect HTTPS client, and strict protected `loom.run-inspection-client` v1 loader. `loom inspect-run --remote-config` decodes the unchanged Phase 1 model with no selected-source fallback. Coordinator serving now injects the Phase 1 callable into the existing mTLS server; user docs cover managed local, remote mTLS, and service-less SSH use. |
| Tests added or updated | Added role-exclusivity and protected-config coverage, remote-selector no-fallback coverage, and a localhost mTLS matrix for query success, mutation-role denial, capability/role denial, and immediate policy revocation before the projection callback. Correction coverage adds a real mTLS 256-stage canonical-result round trip plus strict query-response duplicate-key, 257-record, and 1-MiB closure cases. |
| Validated revision/tree state and evidence | Focused Ruff and Pyright on all changed runtime files passed with 0 errors/warnings; `git diff --check` passed. The focused query-response decoder and localhost mTLS 256-stage parity tests passed. The Phase-plan unit suite and contract suite passed (52 and 10 tests respectively); integration evidence is refreshed after this correction. |
| Validation-relevant changes after evidence | None after the final focused Ruff, Pyright, diff, and query-role mTLS checks. |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
