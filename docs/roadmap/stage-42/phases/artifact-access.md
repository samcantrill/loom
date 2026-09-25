# Phase 6 Execution Plan: Artifact Access

## Metadata

- Status: in_progress; stage 42 / P6.
- Manifest: [implementation-plan.md](../implementation-plan.md).
- Branch: `agent/stage-42-p6-artifact-access`; PR target: `develop`.
- PR title: Stage 42 Run Discovery, Annotations, Lineage, And Result Access - Phase 6: Artifact Access
- Worktree/coordination: manifest context; base after P5
  `fce1c5b174980783046b63cb5a321bbd458b8f27`.
- Dependencies: P4 selection; P3/P5 discovery and graph for composed acceptance.
- Named refinement uncertainty: none. Blockers: none. P5 #354 remotely merged,
  completion metadata published/synchronized and exact phase branch retired.

## Objective And Supported Merge State

Retrieve exact selected results, including complete declared file trees from a
server the client cannot mount. Provide bounded generic previews and truthful
batch outcomes. Finish the journey: discover → trace → select → retrieve →
explicitly annotate chosen source runs. No domain result reader is implemented.

Own `FR-42-A06/A07/A09`, `EX-42-A03/A05/A06`, `VAL-42-A04`–`A08`,
`DQ-42-A03/A04/A05`, and payload-level enforcement of `FR-42-A05/A08` and
`VAL-42-A03`. Earlier phases already own their individual adapter parity.

## Current Source And Harness

- `src/loom/pipeline/stores/shared_artifacts.py`: publication bindings, receipts,
  declared members and checksums, root mappings and containment.
- `artifact_materialization.py`, `immutable_artifacts.py`, `artifact_store.py`,
  `local_artifacts.py`, backend capability adapters: existing access mechanisms.
- P4 exact authority resolver; existing native control/HTTPS byte/body budgets.
- `src/loom/queue` regular-file/agent transfer helpers: reuse byte mechanics only
  where appropriate; agent assignment authorization is not client authorization.
- `src/loom/cli/artifacts.py`, `src/loom/mcp/_server.py`, native client, existing
  materialization/shared-publication/native transport fixtures.

## Fixed Contracts And Finite Matrix

The [output-access contract](../planning/output-access.md#detailed-implementation-contract)
owns description/chunks/previews/materialization semantics and limits. Initial
matrix: committed regular file under configured run artifact root, or full native
shared-publication receipt tree; Unix and authenticated HTTPS reads; optional
client local mapping through the same verifier. No new cloud SDK/backend or
inferred application file closure. Unsupported access is a typed outcome.

Source identity/authorization is rechecked at each native read. Retrieval never
accepts arbitrary server paths or trusts a client-edited ref. Receipt membership,
containment, regular-file semantics and digests define allowed reads. Legacy
files without recorded checksums are labelled original-integrity-unverified.
Transfer-time hashes cannot prove original production bytes.

Client fetch publishes a completed directory only after verification, without
overwriting existing destinations. It writes locally, not a coordinator job.
Private chunk iteration/cache/helper names remain discretionary; limits and
partial-result meanings are public. No generic codec import or pickle execution.

## Invariant Ownership

| Invariant | Owner | Reachable boundary and consequence | Coverage |
| --- | --- | --- | --- |
| Read only selected authorized declaration | Native artifact resolver on every call | Forged locator/member/ref, symlink or stale declaration could expose other files | Scope, traversal, undeclared-member, symlink, exact commit and changed receipt rejection |
| Complete declared files, not inferred subset | Publication receipt/artifact descriptor | Primary manifest references separate payloads | Fetch whole declared tree; undeclared legacy closure reports unsupported |
| No false verification or successor substitution | Existing recorded digest plus transfer verifier | Corrupt, deleted, mutable or unchecksummed historical bytes | Integrity failure/unavailable/unverified-original distinctly; never current-head fallback |
| No partial final destination or destructive overwrite | Client materializer | Interrupted transfer or existing user directory | Own temp cleanup, final publish-if-absent, destination_exists, per-item failure |
| Bounded truthful content | Native preview and adapter formatter | Large JSON/binary, invalid UTF-8 or mixed batch | Whole JSON or too_large; text truncation; bytes base64; explicit failed items and coverage |

## Implementation Slices

1. Implement `describe_artifact(locator)` over exact authority facts and existing
   configured root/backend resolution. Return primary member, paged inventory,
   declaration identity, sizes, recorded hashes and verification capability.
   For a shared receipt the closure is the whole publication tree, even if it
   contains several output primaries. Do not parse a domain manifest to invent it.
2. Implement authenticated `read_artifact_chunk` with maximum 256 KiB raw content,
   declared relative member and offset/length. Fit existing 64 KiB request/1 MiB
   response envelopes. Use read-only CLIENT/QUERY routes and identity guards.
   Ensure receipt validation is correct without needlessly rehashing an entire
   large tree per chunk; any private caching must not authorize stale paths.
3. Implement generic bounded text/JSON/bytes preview. Text preserves valid UTF-8
   boundary and reports truncation; JSON needs the full file within the limit;
   bytes use base64. Application codec fields are metadata, never instructions.
4. Implement client-side `fetch_artifacts` with bounded streaming, safe relative
   paths, retries of the same read, size/digest checks, destination conflict
   handling and publish-if-absent. A batch preserves input order and every matched
   run association while deduplicating identical declaration downloads. Complete
   means processed, not all successful. Cross-restart resume is deferred.
5. Add `artifact-read-v1`, native/Python methods, CLI describe/read/fetch and MCP
   tools. MCP fetch advertises local writes and explicitly names whose filesystem
   contains the destination. Generic bytes/text access remains an option when an
   agent cannot use a returned local path. Document the supported matrix and
   original-integrity limits, not merely API signatures.
6. Add the small two-vocabulary composed workflow: query all pages and preserve
   warnings, trace generic dependencies, select summaries by caller-provided type,
   preview/fetch a mixed-success batch, and separately patch only explicitly
   chosen runs with successful retrieval. No automatic tagging side effect of
   retrieval; the example itself makes the mutation requests.

## Test And Validation Plan

New proposed files: `tests/contracts/test_artifact_access_contract.py`,
`tests/integration/queue/test_artifact_access.py`,
`tests/integration/queue/test_run_discovery_workflow.py`.
Reuse `tests/contracts/test_artifact_materialization_contract.py`,
`tests/contracts/test_immutable_artifact_semantics_contract.py`,
`tests/integration/queue/test_shared_publication.py`,
`tests/integration/queue/test_agent_session_transport.py`, MCP/CLI fixtures.

Required real local integration lane: start the existing authenticated HTTPS
fixture, publish a small actual multi-file tree, run a client without source-root
mapping, and retrieve through chunk routes to an isolated destination. Assert
every member's bytes/layout/checksum. No test that succeeds by directly opening
the producer path qualifies this lane. Unix uses the same resolver/read contract.
No cloud, real Slurm, GPU or physiological dataset is required by this matrix.

Also require: successor commit after selection, corrupt/missing/deleted member,
unchecksummed legacy file, unsupported closure/backend, unavailable authority,
unauthorized producer, unsafe member path/symlink, request/response limits,
interrupted chunk then replay, concurrent/existing destination, malformed/oversize
preview, full inventory paging, duplicate reuse associations and mixed batch.
Optional mapped-local fast path must pass the same identity/integrity fixtures.

Development selection:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest tests/contracts/test_artifact_access_contract.py tests/integration/queue/test_artifact_access.py tests/integration/queue/test_run_discovery_workflow.py tests/contracts/test_artifact_materialization_contract.py tests/integration/queue/test_shared_publication.py
```

Final gate: `make validate-pr`, plus the real HTTPS artifact lane if it is not
included in that target. Use `$loom-targeted-validation`; do not rerun an included
passing lane or summary target merely to restate evidence. Final acceptance
records protocol/authority modes and the bytes/closure actually tested. If an
implementation adds a backend beyond the finite matrix, stop and approve its
additional dependency/qualification obligations first.

## Risks, Stops, And Handoff

Review source containment, exact-version authorization and destination publish
semantics most closely. Stop if a requested multi-file result has no authoritative
closure, if a backend cannot provide actual bytes, or if transfer needs a new
credential service. Report the supported failure; do not infer files or claim a
fake backend proves the real path. No retention pin or durable partial-download
session is promised. Read all detailed access sections and the composed example.

Workflow preparation passed; reuse approved access matrix and predecessor
contracts. One executor is justified by the coupled server authorization,
bounded transport, client filesystem publication and composed workflow. Its
write boundary is P6 source/tests/user docs and this card; no additional backend
or credential service is authorized. Preserve full `make validate-pr` and real
HTTPS multi-file transfer acceptance, with concrete failure/containment/overwrite
checks above. Existing legacy limits remain explicit outcomes rather than new
scope. Implementation and required validation complete; independent review and PR pending.
Refiner not needed yet; blocker corrections 0/3; improvement entries none.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation | Native exact-locator declaration/chunk/preview resolver; flat Python methods, CLIENT/QUERY Unix/HTTPS routes, CLI and MCP; client-owned verified temporary downloads and atomic no-replace publication |
| Changed paths | `src/loom/queue/_artifact_access.py`, `_coordinator_control.py`, `_coordinator_client.py`, `agent_session_transport.py`; `src/loom/_artifact_fetch.py`, `coordinator.py`, `cli/artifacts.py`, `mcp/_server.py`; artifact-access contract/native/composed tests, existing transport/MCP capability tests; `docs/features/artifact-access.md`, artifacts index |
| Affected contracts and consumers | Exact authority identity and scope per call; contained regular-file/receipt membership; complete inventories; bounded inert preview; stream integrity and client destination ownership; native/Python/CLI/MCP parity and explicit source annotation |
| Focused evidence | Isolated locked Python 3.12 config lane: artifact access contracts, native Unix/real mutual-TLS HTTPS transfer, two-vocabulary workflow, existing materialization and shared publication: 15 passed. Isolated config+MCP lane: existing stdio reconnect workflow extended with describe/read/fetch on Unix and HTTPS: 2 passed, 8 deselected. Subsequent assertions and preview verification are covered by the final gate below |
| Selected final checks and expansion triggers | Required `make validate-pr` covers baseline, config, MCP, Ruff, Pyright, builds including the real HTTPS lane. Expand only for failures, source changes invalidating evidence, or a newly affected owner. No additional backend, cloud, physical fleet, or mapped-local optimization is claimed |
| Validated revision/tree and final gate | All `make validate-pr` components passed. Runtime source and baseline/config/static evidence: `d5edfc7b62c669a55a4fa21c85ca9f85925e8cc0`, tree `bf230e4c24721e7ce00e950156e5277c08b95d44`. MCP inventory/write-hint expectation correction only: `45205d75ed53fafc18cb428438a12b5067ae42bc`, tree `de3947f7ac910b578ada3a2fd0d0b2f9d0603792`; affected Ruff, full MCP lane and sdist/wheel builds passed there. Subsequent changes are this evidence record only |
| Gate results and skips | Ruff/Pyright passed (0 type errors). Baseline 3,288 passed / 2 skipped / 406 deselected; config-extra 348 passed / 15 skipped / 3,351 deselected; MCP-extra 57 passed / 3,639 deselected. Baseline skips are existing config-dependent queue CLI cases; config skips are opt-in physical container acceptance. No P6 acceptance case was skipped; no cloud, container/fleet or Slurm qualification is claimed |
| Gate recovery and evidence paths | Initial `make validate-pr` exited 137 during config-extra after baseline/static success, without a reported test failure or diagnosed termination cause. Its one surviving fixture supervisor was stopped and exit verified. Resumed unchanged dependencies with `make -o lint -o typecheck -o test-no-extra validate-pr`; config passed, MCP exposed four stale expected tool-name/write-hint assertions. Corrected only those assertions and finished with `make -o lint -o typecheck -o test-no-extra -o test-config-extra validate-pr` (exit 0). Logs: `build/p6-validate-pr.log`, `build/p6-validate-pr-resume.log`, `build/p6-validate-pr-mcp.log`; no passed lane was repeated |
| Executable access matrix | Embedded and authenticated authority local-file contracts; CLIENT Unix and actual mutually authenticated HTTPS complete-tree transfer without client source mapping; QUERY HTTPS declaration/chunk/preview parity; CLI describe/read/fetch and MCP Unix/HTTPS describe/read/fetch. Real transfer: three declared members, 350,020 payload bytes with nested layout and full byte comparison, including a member spanning chunks. Contract inventory: 205 declared members; native reuse association preserved with one published download |
| Review/PR/merge | Manager-owned; pending |
| Residual limitations | No retention pin or durable partial resume; legacy original bytes remain unverified without checksum. Atomic non-replacing directory publication requires Linux/filesystem `renameat2` support; unsupported hosts fail without overwriting. No inferred application closure or external reader |
