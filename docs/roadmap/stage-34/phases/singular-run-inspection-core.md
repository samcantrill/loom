# Phase 1 Execution Plan: Singular Run Inspection Core

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 34, Phase 1
- Manifest: docs/roadmap/stage-34/implementation-plan.md
- Branch: agent/stage-34-p1-singular-run-inspection-core
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-34-p1-singular-run-inspection-core`
- Base revision: `4fb44179055855e6402ded80de0890552de759d8`
- PR target: develop
- PR title: `Stage 34 phase 1: add singular run inspection core`
- PR: [#263](https://github.com/samcantrill/loom/pull/263)
- Dependencies: Stage 32 replacement Phase 3 merged in
  [#261](https://github.com/samcantrill/loom/pull/261); Stage 29 bounded
  admission detail; existing authority, artifact, log, diagnostics, Unix
  socket, and CLI seams
- Workflow path: fast; the approved public projection is fixed and the merged
  Stage 32 exact-reference seam matches it without a new planning decision
- Blockers: none

## Objective And Context

- Vertical outcome: callers use the public Python API or
  `loom inspect-run RUN_URI` through direct or owner-only Unix sources and
  receive the same safe, bounded result for managed and service-less runs.
- Earlier dependency: Stage 32 replacement Phase 3 retains the canonical queue
  item ID in the run-local submitted operation/manifest; Stage 29 supplies
  indexed managed admission and targeted owner detail.
- Later work explicitly out of scope: mTLS query role/dispatch/client, remote
  client configuration, content delivery, discovery, paging, and subscriptions.

## Current Source And Harness

- Relevant files and symbols: `AuthoritativeRunSnapshot`, `ArtifactRef`,
  diagnostics inspection helpers, `LocalDaemonAdmissionDetail`,
  `build_local_daemon_owner_views`, `LocalDaemonSocketServer`/client, merged
  Stage 32 queue/Slurm types, CLI parser/formatting, and lazy diagnostics exports.
- Existing tests and seams: authoritative read-model contracts, local
  status/log/artifact tests, daemon bounded-detail and socket tests, Stage 32
  delegated Slurm fixtures, CLI JSON envelopes, import-safety/build checks.
- Import, dependency, or harness constraints: diagnostics may depend on public
  lower APIs; queue/store/transport modules must not import diagnostics. No
  optional scheduler/network dependency or project-stage import is permitted.

## Scope

In scope:

- Add immutable strict schema-v1 inspection result, named owner-axis, stage,
  location, truncation, and safe-failure values with rejecting plain-data codecs
  and lazy public diagnostics exports.
- Add one diagnostics projection service over exact managed and service-less
  reads. Preserve authority lifecycle precedence and per-owner revision,
  observation, freshness, availability, and safe codes.
- Resolve managed runs by the coordinator's indexed run URI. For service-less
  runs, verify the Stage 32 run-local canonical queue item reference against the
  dispatch handle before the primary-key item read; never scan the queue.
- Project only approved stage and location fields. Use recorded checksums/types,
  safe path stat where justified, typed reachability, and no payload/log read,
  codec load, checksum calculation, directory enumeration, arbitrary messages,
  metadata, configuration, provenance, commands, receipts, fences, or secrets.
- Enforce the 4-KiB URI, 256-record-per-collection, deterministic ordering/count,
  and 1-MiB encoded response contracts with typed degraded/truncated outcomes.
- Add the owner-only Unix operation and client using an injected plain-data
  projection callable; retain peer-UID authorization and existing envelope
  bounds/errors.
- Add `loom inspect-run` direct and `--endpoint` modes, direct-only optional
  `--queue-config`, text output, `loom.cli.inspect_run.v1` JSON, public API docs,
  and compatibility assertions for existing diagnostic commands.

Out of scope:

- HTTP/TLS policy or client configuration, use of client/operator mutation
  credentials, byte/tail/follow behavior, list/search, a cursor API, new state,
  schema migration, remote stores, path translation, SSH code, or UI.

Assumptions:

- Stage 32's merged durable operation/manifest exposes the approved canonical
  queue item reference. A direct source without queue configuration can still
  inspect authority/materialization but reports its queue axis unavailable.
- Authored paths and refs are trusted project data, but the public projection is
  still a strict allowlist because it crosses process and later network bounds.

## Fixed Contracts And Private Discretion

- Observable behavior: exactly one selected source; known runs return one typed
  result; unknown/invalid/unavailable sources use closed failures; Unix never
  falls back direct; authority terminal truth wins summary precedence.
- Public or durable shapes: schema-v1 result/error, named axes, stage/location
  records, truncation counts, public `inspect_run`, command spelling/selectors,
  and CLI JSON schema. The Stage 32 reference remains owned by Stage 32.
- Trust and failure boundaries: same-user peer UID gates socket access; source
  identity is not request-supplied; partial owners remain explicit; no bytes or
  arbitrary owner mappings cross the projection.
- Cross-phase contracts: Phase 2 consumes the exact result/error codecs,
  projection callable, bounds, and CLI command without changing them.
- Reproducibility and compatibility: the query writes nothing, ordering and
  truncation are deterministic, repeated reads may differ only with owner state,
  and current diagnostic commands/schemas remain unchanged.
- Private choices the executor may simplify: filenames below the planned
  ownership, internal protocols/callbacks, SQL/helper layout, text formatting,
  and byte-budget algorithm.

## Proportionality

- Existing seam reused: authority snapshot, Stage 29 targeted detail, Stage 32
  durable references and primary-key queue read, materialization helpers, Unix
  framing/peer UID, diagnostics lazy exports, and CLI envelopes.
- Material additions and current justification: one shared model/projection is
  required for adapter parity and redaction; one socket operation and CLI are
  required for live managed and service-less operator journeys.
- Optional hardening and future capability deferred: pagination, caching,
  batching, search indexes, store adapters, payload relay, push, metrics, and UI.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Lifecycle summary follows authority | per-run authority plus diagnostics precedence | scheduler/queue disagrees or authority is unavailable | false scientific terminal result | disagreement and unavailable-authority matrix |
| Run-to-item link is exact | Stage 32 manifest and queue dispatch handle | mismatched or absent retained ID | wrong queue row or scan | agreement, mismatch, missing-reference tests |
| Public fields are allowlisted | diagnostics projection | raw owner message/metadata/receipt | secret or unstable schema exposure | secret-bearing fakes and exact-field codec tests |
| Inspection reads no content | artifact/log owners plus projection | convenience helper reads logs/artifacts | unexpected I/O or payload exposure | read-spy stores and no-codec/checksum assertions |
| Work and response are bounded | targeted owners plus serializer | thousands of unrelated runs or 257+ records | scan, memory, or transport growth | query-count sentinel, stable truncation, byte cap |
| Selected source never falls back | source adapter | socket failure with local files present | trust-boundary bypass | failure-with-local-sentinel test |
| Dependency direction remains downward | package boundaries | queue/transport imports diagnostics | import cycle/heavy public import | import graph and build tests |

## Implementation Slices

1. Add the strict public models, codecs, failure vocabulary, constants, and lazy
   exports with round-trip/unknown-field/import tests.
2. Add exact managed and service-less reads plus the projection/precedence,
   allowlist, location, bounds, and no-content tests.
3. Wire the injected query operation through direct composition and the
   owner-only socket, including safe failures and parity tests.
4. Add direct/Unix CLI selection, stable JSON/text formatting, documentation,
   and unchanged-command compatibility tests.
5. Run focused contract/integration journeys, repository gates, and inspect the
   diff for hidden global reads, persistence, or import inversion.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public imports stay intentional and cheap | lazy diagnostics import, wheel/sdist build, no project/optional imports |
| Unit | required | Codec, allowlist, precedence, bounds, selectors | exact fields/codes, 257 truncation, byte budget, parser negatives |
| Contract | required | One model and failure shape across sources | strict round trip and direct/Unix serialized equality |
| Integration | required | Real authority/queue/manifest/socket composition | managed mixed owners, both Stage 32 Slurm modes, peer UID, no fallback |
| E2E / opt-in | required local | Service-less SSH-compatible CLI journey | subprocess JSON after driver exit; no actual SSH/Slurm/network |

Targeted commands:

    uv run pytest tests/unit/loom/diagnostics/test_run_inspection.py tests/unit/loom/cli/test_inspect_run.py tests/unit/loom/queue/test_local_daemon.py
    uv run pytest tests/contracts/test_run_inspection_contract.py
    uv run pytest tests/integration/diagnostics/test_run_inspection.py tests/integration/queue/test_local_daemon_production.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidental raw-owner leakage, hidden queue/global scan, byte reads
  used to determine availability, authority precedence drift, or import inversion.
- Review focus: closed codecs, Stage 32 reference agreement, targeted SQL/store
  calls, read-spy proof, deterministic limits, source failure, and existing CLI
  compatibility.
- Stop if: merged Stage 32 lacks the durable reference; exact lookup requires a
  scan/new schema; a lower module must import diagnostics; content must be read;
  or the fixed model cannot express a supported owner without arbitrary data.
- Accepted debt and revisit trigger: truncation has no paging; add it only for a
  concrete consumer that cannot use existing local forensic commands.

## Executor Handoff

- Read section range: this entire phase plan; Stage 34 planning Minimum Design,
  DQ-1 through DQ-3, validation, and Phase Shaping; merged Stage 32 replacement
  Phase 3 run-to-item contract; `docs/structure.md` diagnostics/import sections.
- Safe implementation slices: models/codecs; exact projection; socket; CLI/docs;
  focused and full validation.
- Decisions not to revisit: one run URI, no bytes/list/paging/fallback, fixed
  limits/allowlist, diagnostics ownership, additive command/schema.
- Conditions requiring manager action: any stop condition, public field/limit
  change, new persistence/dependency, or Stage 32 contract mismatch.

## Workflow State

- Manager preparation: complete; dependency PR #261, exact base, branch,
  worktree, source seams, and fast-path route verified.
- Expanded planning: not needed; the merged Stage 32 seam matches DQ-3.
- Implementation: executor pass complete in `f466a81`; it added the public v1
  model/projection, indexed managed lookup, injected Unix operation, CLI/API,
  lazy exports, documentation, and initial unit/package coverage.
- Refiner: correction 1/3 complete in `202f3d3`. The original skeleton did not
  compose the projection in the production Unix daemon, did not apply direct
  queue configuration, and did not project the retained service-less exact
  queue reference. The bounded correction reuses the retained operation, exact
  queue primary-key read, and dispatch-handle/manifest agreement; it adds no
  owner persistence or protocol.
- Manager correction 2/3: complete. The plan-required contract, integration,
  and subprocess journeys were absent, direct queue configuration started a
  mutable service/global recovery read, managed detail was not projected, known
  partial runs could collapse to whole failures, returned identities were
  omitted, and the response budget did not include the socket envelope. The
  correction adds one read-only existing-database open, fixed-axis/identity and
  truncation invariants, exact managed and both Stage 32 Slurm journeys,
  no-content/secret checks, and direct/Unix parity without new persistence.
- Manager correction 3/3: complete. Pre-submit review found that a reachable
  populated local-agent execution/result owner was omitted from the fixed axes
  and that authoritative per-stage lifecycle reason codes were omitted from the
  v1 stage record. The correction projects the allowlisted local-agent owner as
  `transfer_result`, adds the optional stable stage `code`, and exercises a real
  managed stage through direct and Unix reads while preserving non-atomic
  revision semantics.
- Pre-submit gate: complete at `d0d01e1`; manager review found no remaining
  blocker against the phase plan, accepted contracts, dependency direction,
  domain neutrality, or proportionality.
- Independent review: not used. The fast-path manager review covered the final
  current-target diff and found no material residual risk requiring expansion.
- Blocker corrections: 3/3; exhausted.
- PR and merge: PR #263 was verified against `develop`, approved by
  manager-local review, and squash-merged as `1f3f7fa` on 2026-08-30.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `loom.diagnostics.run_inspection` strict v1 models/projection and lazy exports; owner-only injected Unix operation/client; indexed daemon run-URI lookup; direct/Unix CLI selection, docs, and public import expectation. Corrections compose the production callback, return queue/admission IDs, project targeted managed and service-less owners including local-agent execution/result, expose safe artifact/log locations and stage reason codes, enforce fixed axes/cardinality/socket size, and open an existing queue database read-only for direct inspection. |
| Tests added or updated | Added strict codec/failure/bounds/precedence/reason/no-content units; direct queue-config and no-fallback CLI units; direct/Unix and read-only queue contracts; real managed execution/socket and both Stage 32 Slurm-mode integrations; an after-driver-exit subprocess JSON journey; and diagnostics public-import coverage. |
| Validated revision/tree state and evidence | At `d0d01e1`, after merging current `origin/develop`, the focused unit/contract/integration/E2E matrix passed 52, 3, 49, and 1 tests respectively; targeted Ruff, Pyright, and `git diff --check` passed. Fresh `make validate-pr` passed Ruff, Pyright with 0 errors or warnings, 2,727 default tests with 136 deselected, 157 config-extra tests with 3 expected skips and 2,730 deselected, plus source and wheel builds. Fresh `make test-summary` recorded 2,884 selected passes across package 119, unit 1,921, contract 300, integration 326, E2E 61, and config-extra 157, with the same 3 expected skips. |
| Validation-relevant changes after evidence | None. Only this phase evidence metadata changed after the validated source/test tree, so the receipt remains current under the repository freshness rule. |
| PR, review, and merge | [#263](https://github.com/samcantrill/loom/pull/263) target, head, title, body, non-draft state, and clean mergeability were verified; manager-local fast-path review passed with no blocker; squash-merged to `develop` as `1f3f7fa` on 2026-08-30. |
| Residual risk and cleanup | No known Phase 1 blocker. Huge collections intentionally truncate without paging. The dedicated worktree and exact local/remote phase branches were removed after the remote merge was verified. |
