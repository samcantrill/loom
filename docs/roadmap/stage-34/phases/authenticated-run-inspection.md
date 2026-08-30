# Phase 2 Execution Plan: Authenticated Run Inspection

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 34, Phase 2
- Manifest: docs/roadmap/stage-34/implementation-plan.md
- Branch: agent/stage-34-p2-authenticated-run-inspection
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-34-p2-authenticated-run-inspection`
- Base revision: `0eb6a90df1517a0b51538241db8792359563e619`
- PR target: develop
- PR title: `Stage 34 phase 2: add authenticated run inspection`
- PR: [#264](https://github.com/samcantrill/loom/pull/264)
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
- Refiner: one bounded pass completed in `56aadb1` for the qualified remote
  decoder-limit blocker; no further refiner pass is available or needed.
- Pre-submit gate: complete at `fa38573`; manager review found no remaining
  blocker against the authenticated trust contract, exact coordinator scope,
  Phase 1 wire parity, existing-role compatibility, import direction, or
  proportionality.
- Independent review: required on the expanded path after PR submission because
  this phase changes the remote credential and authorization boundary. The
  review found no product blocker and one localized failure-parity correction.
- Blocker corrections: 3/3 complete; exhausted. The remote client applied the legacy
  agent-request decoder after reading a Phase 1-sized response, incorrectly
  closing valid 65+ record results as unavailable. The correction gives only
  query responses their fixed 1 MiB/256-record strict decoder, preserves the
  existing 64 KiB/64-item agent decoder for request and handshake traffic, and
  rejects wrong response content types or status/envelope combinations.
  Correction 2/3 is complete: manager review found malformed run URIs reached
  admission and became `not_found` instead of the Phase 1 `invalid_request`, and
  malformed handshake JSON could escape the closed failure path. The correction
  reuses the lower canonical run-URI validator before admission, closes handshake
  decoding/status failures, and adds exact-scope, capability, role-isolation,
  zero-owner-view, revocation, and remote CLI subprocess evidence.
  Correction 3/3 closes the independent review's lone-surrogate URI case as
  `invalid_request` rather than `unavailable`, matching Phase 1 without changing
  authorization, admission, or public schemas.
- PR and merge: PR #264 is open with verified base `develop`, phase head,
  title, body, non-draft state, and clean mergeability. Expanded independent
  review and merge are pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added the dedicated `query` role, exact authenticated `/v1/query/inspect_run` dispatch, capability handshake, bounded no-redirect HTTPS client, and strict protected `loom.run-inspection-client` v1 loader. `loom inspect-run --remote-config` decodes the unchanged Phase 1 model with no selected-source fallback. Coordinator serving now injects the Phase 1 callable into the existing mTLS server; user docs cover managed local, remote mTLS, and service-less SSH use. |
| Tests added or updated | Added role-exclusivity and protected-config coverage, remote-selector no-fallback coverage, and a localhost mTLS matrix for query success, exact admitted/unadmitted scope, malformed identity/URI closure, mutation-role and query-role isolation with zero owner-view calls, missing capability, immediate policy revocation, and a 256-stage canonical-result round trip. Strict decoder tests cover duplicate keys, 257 records, and the 1-MiB limit. E2E coverage invokes `loom inspect-run --remote-config` as a subprocess against the real local mTLS server. |
| Validated revision/tree state and evidence | At `fa38573`, the complete phase-targeted unit, contract, and integration commands passed 52, 10, and 44 tests respectively; both direct/service-less and authenticated-remote inspect-run E2E journeys passed (2 tests). Focused Ruff, Pyright with 0 errors/warnings, and `git diff --check` passed. Fresh `make validate-pr` passed Ruff, Pyright with 0 errors/warnings, 2,734 default tests with 136 deselected, 157 config-extra tests with 3 expected skips and 2,737 deselected, plus source and wheel builds. Fresh `make test-summary` recorded 2,891 selected passes across package 119, unit 1,924, contract 300, integration 329, E2E 62, and config-extra 157, with the same 3 expected skips. |
| Validation-relevant changes after evidence | Correction 3 changed the remote URI guard and causal mTLS test after the recorded broad evidence. Fresh repository gates are required before merge. |
| PR, review, and merge | [#264](https://github.com/samcantrill/loom/pull/264) opened against `develop`; target, head, title, body, non-draft state, and clean mergeability verified. Expanded independent review and merge are pending. |
| Residual risk and cleanup | Independent review found no product blocker; its one localized parity finding is corrected and the correction budget is exhausted. Fresh validation, merge verification, metadata, and worktree/branch cleanup remain. Localhost mTLS proves Loom policy behavior but cannot certify site certificate issuance or path reachability. |
