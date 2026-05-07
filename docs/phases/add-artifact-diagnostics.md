# Phase 4 Execution Plan: Artifact Inspection And End-To-End Diagnostics

## Metadata

- Status: refined phase execution plan
- Feature focus: `Local Diagnostics`
- PR title: `Local Diagnostics - Phase 4: Artifact Inspection and End-to-End Diagnostics`
- Branch: `codex/add-artifact-diagnostics`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-artifact-diagnostics`
- Phase execution plan path: `docs/phases/add-artifact-diagnostics.md`
- Full plan: `docs/implementation-plans/implementation-plan-v3.md`
- Source phase: Phase 4 - Artifact Inspection And End-To-End Diagnostics
- Stack predecessor: none
- Base branch: `develop` at `26c5813 docs: record v3 phase 3 merge`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible only when it targets
  `develop` and validation, review, and CI gates pass
- Workflow path: expanded path
- Successor dependency notes: final v3 phase; no planned successor phase depends
  on this branch.
- Plan quality gate: passed on 2026-05-07 by `loom_plan_reviewer`
  confirmation review
- Plan quality gate loop budget: initial review used, plan refinement used,
  confirmation review used
- Draft pass: completed by managing agent on 2026-05-07
- Refine pass: completed by managing agent on 2026-05-07; artifact selector
  semantics, duplicate handling, provenance scope, zero-artifact behavior, and
  suite obligations were checked before implementation
- Setup limitations: none known
- Blockers: none known

## Objective

Complete the v3 local diagnostics surface by adding artifact metadata inspection
facades and `loom artifacts list/show` commands, then prove the full
preflight-run-status-logs-artifacts workflow over successful and failed local
runs without loading artifact payloads or traversing private store layout in CLI
code.

## Full-Plan Context

Phase 1 established diagnostics models and preflight core. Phase 2 exposed
preflight through the CLI and reused a minimal subset in `loom run`. Phase 3
added store-owned status/log inspection plus `loom status` and `loom logs`.
Phase 4 is the final v3 phase and should stay focused on artifact metadata and
end-to-end evidence; payload display, checksum verification, catalogs, and
retention workflows remain out of scope.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1, Phase 2, and Phase 3 are
  merged into `develop`
- Why this base branch is correct: all earlier v3 phases are merged and the
  implementation-plan metadata is committed on `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: delete the branch after squash merge because no
  successor depends on it

## Source Phase Summary

- Goal: expose artifact metadata inspection and full local diagnostics workflow
  evidence.
- Required scope: diagnostics result models/facades over run-store artifact
  indexes, `ArtifactRef` metadata, producer information, available generic
  provenance, `loom artifacts list RUN_URI`, `loom artifacts show RUN_URI
  ARTIFACT_ID`, and end-to-end tests.
- Required checkpoints: no payload loading, no checksum verification, no codec
  reads, no catalog behavior, and no CLI-private run-layout traversal.
- Acceptance criteria: users can list artifacts and inspect one artifact's
  metadata/provenance; missing artifact IDs fail clearly; successful and failed
  local runs can be diagnosed end to end; JSON output remains stable and
  plain-data friendly.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: artifact primitives live
  in `src/loom/artifacts.py`; the run-store artifact index is exposed through
  `RunArtifactIndexStore.read_artifact_index()`, logical keys through
  `parse_artifact_key()`, stage outputs through `read_stage_outputs()`, and
  generic stage provenance through `read_stage_provenance()`. There is no
  `src/loom/artifacts/` package directory.
- Existing tests or harness behavior: Phase 3 created
  `loom.diagnostics.inspection`, `loom status`, `loom logs`, diagnostics
  integration fixtures, and e2e CLI coverage that can be extended. Existing
  local run tests cover artifact index and corrupt artifact index behavior.
- Import-boundary or dependency constraints: CLI command registration should
  stay import-light. Diagnostics may import public artifact and store APIs, but
  stores and artifacts must not import diagnostics or CLI. Artifact diagnostics
  must not import config composition, execution, codecs, project modules, or
  optional dependencies at import time.

## In-Scope Work

- Add artifact diagnostics summary models and facade functions, likely in
  `loom.diagnostics.inspection`, for run artifact lists and single artifact
  detail views.
- Read artifacts through public run-store APIs: `read_artifact_index()`,
  `parse_artifact_key()`, `read_stage_outputs()`, and
  `read_stage_provenance()`.
- Include stable plain-data fields for logical artifact key, artifact ID, URI,
  artifact type, codec key, checksum, fingerprint, producer stage, output name,
  created timestamp, metadata, and provenance availability.
- Include generic stage provenance in the show/detail payload when available.
- Add `loom artifacts list RUN_URI` with `--format text|json`.
- Add `loom artifacts show RUN_URI ARTIFACT_ID` with `--format text|json`.
- Register the `artifacts` command group in the import-light CLI parser and add
  text formatting plus JSON result-envelope constants.
- Add package, unit, contract, integration, and e2e coverage for artifact
  diagnostics imports, payload shape, missing-artifact errors, CLI output, and
  full successful/failed local diagnostic flows.

## Out-of-Scope Work

- Artifact payload display, `cat`, preview, or decoding.
- Loading artifact content through codecs.
- Checksum verification or existence verification against the artifact store.
- Artifact catalogs, comparison, export/import, retention, cleanup, or garbage
  collection.
- Domain-specific interpretation of artifact metadata or provenance.
- Remote run URI or remote artifact store behavior beyond existing local URI
  validation and store errors.
- New persisted diagnostics documents or schema migrations.

## Assumptions

- `ARTIFACT_ID` for `loom artifacts show` is the `ArtifactRef.artifact_id`
  string, typically `stage/output`, because the roadmap names artifact IDs.
  List output exposes both the logical run-store key, typically `stage.output`,
  and the artifact ID for disambiguation.
- If duplicate artifact IDs are ever present in the run-level index, `show`
  should fail with a run-state error that names the ambiguity rather than
  choosing one silently.
- Stage provenance is generic enough to expose as plain data in `show`, but
  list output should only advertise whether provenance is available.
- A failed run can still have zero artifacts; the full failed-flow e2e coverage
  should prove clear artifact-list behavior without requiring a failed stage to
  produce outputs.

## Scope Contract

Artifact diagnostics must be read-only and metadata-only. The expected public
diagnostics shape is additive and plain-data friendly, with concrete model names
such as:

```text
ArtifactSummary(
    key,
    artifact_id,
    stage_name,
    output_name,
    uri,
    artifact_type,
    codec_key,
    checksum,
    fingerprint,
    producer_stage,
    created_at,
    metadata,
    provenance_available,
)

RunArtifactsSummary(run_uri, artifacts)

ArtifactDetailSummary(
    run_uri,
    artifact,
    stage_provenance,
)
```

Field names may vary to match local style, but JSON payloads must include both
the run-store logical key and the `ArtifactRef.artifact_id`. Artifact list
ordering must be deterministic by logical artifact key. `show` should resolve by
`ArtifactRef.artifact_id`, report a run-state error for missing or ambiguous
IDs, and must not load payload bytes, invoke codecs, or verify checksums.
Artifact summaries should derive `stage_name` and `output_name` from the
run-store logical key via `parse_artifact_key()` instead of string splitting in
CLI code.

`loom artifacts list RUN_URI` emits a command-owned schema version,
`payload_name="result"`, run URI, artifact count, and an artifact summary list.
Text output is compact and includes one line per artifact with stage/output,
type, URI, and artifact ID. A known run with zero artifacts exits successfully
with an empty artifact list and `artifact_count=0`.

`loom artifacts show RUN_URI ARTIFACT_ID` emits the same artifact fields plus
generic stage provenance when available. The detail payload should use
`stage_provenance` with `null` when unavailable and a plain-data mapping when
available. Text output is compact and suitable for terminal debugging; it may
summarize nested provenance keys rather than printing large nested payloads
verbatim. Metadata must be copied from `ArtifactRef.metadata` without domain
interpretation.

## Design Impact

- Maintainability: artifact diagnostics reuse the run store's public artifact
  index and stage provenance readers rather than adding CLI path knowledge.
- Extensibility: payloads leave room for later verification, existence checks,
  payload display, catalogs, and bundle workflows without changing v3 defaults.
- Domain neutrality: output describes generic artifact references and plain
  provenance without interpreting domain metadata.
- Source-tree boundaries: `loom.diagnostics` remains below CLI and above public
  runtime/store APIs; `loom.pipeline.stores` and `loom.artifacts` remain free of
  diagnostics and CLI imports.

## Future Compatibility

- Later checksum/existence commands can add opt-in verification fields without
  changing metadata-only list/show behavior.
- Later payload display can use `ArtifactRef.codec_key` and artifact store APIs
  without changing the run-store index contract.
- Later catalog or remote-store implementations can satisfy the same
  diagnostics facade by providing the existing public run-store artifact APIs.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use the run-store logical key as the only `show` identifier. | The implementation plan explicitly names `ARTIFACT_ID`; list output can expose keys for users who need stage/output context. |
| Verify checksums or existence during list/show. | The v3 phase is metadata/provenance-only; verification needs explicit policy and may be expensive or unavailable. |
| Load artifact payloads with codecs for richer previews. | Payload semantics are domain-owned and Phase 4 explicitly excludes payload loading. |
| Glob artifact files from the local run directory. | It leaks local layout into diagnostics/CLI and misses externally registered artifacts. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| `show` resolves by `artifact_id` and fails on duplicates rather than adding a second identifier. | The v3 public command shape is fixed to `ARTIFACT_ID`; duplicate handling is safer than silent selection. | Revisit if real workflows produce duplicate artifact IDs and need a key-based selector. |
| Artifact inspection does not verify URI existence or checksum validity. | This phase is metadata-only and must not read payload bytes. | Revisit when a verification command or policy is explicitly planned. |

## Reviewability

- Expected PR size and shape: one diagnostics artifact facade addition, one
  artifact CLI command group, formatting helpers, and focused tests plus e2e
  workflow evidence.
- Files and areas to inspect: `src/loom/diagnostics/`,
  `src/loom/cli/artifacts.py`, `src/loom/cli/main.py`,
  `src/loom/cli/formatting.py`, package/import-boundary tests, diagnostics and
  CLI unit tests, integration diagnostics fixtures, and e2e CLI tests.
- Scope-control checks: confirm no payload loading, no codec invocation, no
  checksum verification, no artifact catalog or cleanup behavior, no private
  path traversal outside store internals, and no project stage imports during
  command registration.

## Implementation Steps

1. Add artifact diagnostics models and facade functions over the public
   run-store artifact index, stage output, and stage provenance APIs.
2. Add CLI command group parsing, handlers, text formatting, JSON envelopes, and
   run-state error mapping for artifact list/show.
3. Add package, unit, and contract coverage for public imports, deterministic
   summaries, missing/ambiguous artifact IDs, JSON payloads, and error mapping.
4. Add integration coverage over local run-store fixtures with multiple stages,
   multiple artifact types, metadata, and stage provenance.
5. Add e2e coverage proving successful and failed diagnostic flows through
   preflight, run, status, logs, and artifacts, then run final validation and
   update phase/PR artifacts.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`,
  `tests/package/test_import_boundaries.py`, and
  `tests/package/test_pipeline_store_api.py` if public export expectations
  change
- Required assertions or deferral reason: artifact diagnostics imports remain
  cheap; CLI command registration for `artifacts` does not import diagnostics,
  stores, config, execution, codecs, project modules, or optional dependencies.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/diagnostics/`,
  `tests/unit/loom/cli/`, and `tests/unit/loom/pipeline/stores/` only if store
  API tests need focused additions
- Required assertions or deferral reason: artifact summary models, deterministic
  sorting, payload conversion, missing run/store error wrapping, missing and
  ambiguous artifact IDs, text formatting, JSON envelopes, and CLI error
  mapping.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_store_contract.py` and a focused
  diagnostics artifact contract test if needed
- Required assertions or deferral reason: diagnostics consume
  `read_artifact_index()` and public stage provenance/output readers rather
  than private path layout; the command contract remains metadata-only.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/`
- Required assertions or deferral reason: artifact list/show over local
  run-store or CLI fixtures with multiple stages, multiple artifact types,
  metadata, producer information, available generic provenance, missing
  artifact ID, and clear zero-artifact output for failed runs.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py` or a focused diagnostics e2e
  module
- Required assertions or deferral reason: full local workflow uses `preflight`,
  `run`, `status`, `logs`, `artifacts list`, and `artifacts show` over
  successful and failed synthetic runs.

### Opt-In Suites

- Status: deferred
- Markers affected: `optional_dependency` for config-backed local workflow
  fixtures
- Required assertions or deferral reason: no external service, scheduler,
  container, plugin, network, or remote-store behavior is introduced.

## Risks

- Confusing `ArtifactRef.artifact_id` with run-store logical keys could make
  `show` ambiguous or hard to use unless list output exposes both.
- Accidentally verifying checksums or loading payloads would exceed the phase
  scope and make diagnostics unexpectedly expensive.
- Printing full nested provenance in text output could make golden output
  brittle and noisy.
- CLI registration can become too eager if artifact command modules import
  diagnostics execution APIs at top level.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py -m package
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/diagnostics tests/unit/loom/cli
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py
UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/diagnostics tests/e2e/test_cli_core.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: diagnostics artifact facade first; CLI command
  group and formatting second; focused tests third; full workflow evidence last.
- Tests to run with each slice: diagnostics unit tests after facade work; CLI
  unit tests after command handlers; integration/e2e diagnostics tests after
  command behavior works.
- Decisions the executor must not revisit: no payload loading, no checksum
  verification, no artifact catalog/cleanup, `show` uses
  `ArtifactRef.artifact_id`, duplicate artifact IDs fail clearly, list output
  exposes both logical keys and artifact IDs, zero-artifact known runs succeed,
  and text output stays compact.
- Conditions that require stopping for the manager: artifact show requires
  changing persisted artifact index schema, duplicate artifact IDs need a new
  public selector, or e2e workflow evidence requires future executor behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-07 by managing agent after
  `make validate-pr` exposed a Pyright tuple-narrowing issue and a pytest
  module-name collision; both were fixed and final validation passed.
- PR review: used on 2026-05-07 by managing agent during the pre-submit blocker
  gate; diff scope, whitespace, PR-body evidence, suite evidence, and Phase 4
  boundaries had no blocking findings.
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on 2026-05-07 by managing agent; committed as
  `plan: add phase 4 execution plan`.
- Final phase execution plan: refined on 2026-05-07 by managing agent;
  artifact ID selection, duplicate handling, provenance payload shape,
  zero-artifact behavior, and no-payload/no-verification boundaries were made
  implementation-ready.
- Implementation summary: completed Phase 4 artifact inspection. Added
  metadata-only artifact diagnostics models and facades over the public
  run-store artifact index and stage provenance readers, added `loom artifacts
  list` and `loom artifacts show`, added compact text output and schema-versioned
  JSON envelopes, and preserved no-payload/no-checksum/no-private-layout
  boundaries.
- Implementation validation: targeted package, unit, contract, integration,
  e2e, and Ruff checks passed. Final `UV_CACHE_DIR=/tmp/uv-cache make
  validate-pr` passed with Ruff clean, Pyright 0 errors, default isolated suite
  550 passed/13 skipped/12 deselected, config-extra 396 passed/565 deselected,
  and build artifacts produced. Final `UV_CACHE_DIR=/tmp/uv-cache make
  test-summary` passed with package 48 passed/1 skipped, unit 452 passed/1
  skipped, contract 41 passed/2 skipped, integration 9 passed/6 skipped/12
  deselected, e2e 15 passed, and config-extra 396 passed/565 deselected.
- Refinement summary: implementation refinement completed on 2026-05-07.
  Validation found Pyright needed explicit artifact-match narrowing and pytest
  needed the CLI artifact test basename to avoid colliding with existing
  artifact tests; both fixes were committed and final validation passed.
- Blocker-resolution summary:
- PR preparation: complete on 2026-05-07 by managing agent. PR body drafted at
  `docs/phases/add-artifact-diagnostics-pr-body.md`; PR opened as
  https://github.com/samcantrill/loom/pull/69 and verified with
  `baseRefName=develop`, `headRefName=codex/add-artifact-diagnostics`, and
  `state=OPEN`.
- Stack maintenance: root phase; PR #69 merged into `develop` on 2026-05-07
  with no successor branch dependencies.
- Remaining blockers: none.
