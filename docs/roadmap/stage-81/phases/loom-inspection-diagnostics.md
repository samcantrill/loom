# Phase 12 Execution Plan: Loom Inspection Diagnostics

## Metadata

- Status: in_progress
- Roadmap stage and phase: rphys 81, Loom owner phase 12
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: `agent/stage-81-p12-loom-inspection-diagnostics`
- Worktree: `/nas/home/can134/work/loom-worktrees/stage-81-p12-loom-inspection-diagnostics`
- Base: published Loom `d444284c161a036d5eae759c297bdf42012157f0`
- PR target: `develop` in `samcantrill/loom`
- PR title: `Stage 81 Causal Failure Propagation And Deferred Retained Smoke - Phase 12: Loom Inspection Diagnostics`
- Dependencies: approved rphys diagnostic amendment; P11 PR #287 remotely merged,
  completion metadata published and exact phase cleanup verified.
- Workflow: one executor, both local gates and required independent PR review.
- Blockers: none; no Stage 85 adoption or resource-policy dependency.

## Objective And Contract Owner

When a client cannot inspect persisted experiment failures, explain the actual
inspection failure and its nested causes. This does not create another experiment
failure, change admission state or make a partial list look complete. Producer,
strict diagnostic reader/renderer and the existing admission CLI ship together.

Canonical fixed contract is FR-81-31, DD-81-24, EX-81-18 and VAL-81-03/05 in
[the published diagnostic card](https://github.com/samcantrill/rphys/blob/b6f49c0dffa1933d92f51c4a11d39c0ebf4265b3/docs/roadmap/stage-81/planning/diagnostic-failures.md#inspection-failure-contract--dd-81-24).
The manager verified this section at the clean canonical rphys stage tree. Read
that section for contract questions, not the whole historical planning packet.
This is another rphys Stage 81 owner contribution, not a new Loom milestone.

## Current Source And Harness

`queue/local_daemon_execution.py::_run_result_owner_view` currently returns exactly
seven fields. It reads a plan, resolved pipeline and each failed stage's persisted
failure, validates identity/attempt and discards the live exception on any failed
read. It deliberately returns an empty failure list when a later read fails.
`build_local_daemon_owner_views` separately catches authority snapshot errors
before calling this helper. Capture there before the original exception is lost.
Retain the existing cancellation-receipt and other owner-state semantics; a
failure unrelated to facts required by run-result inspection is not a new reason
to change that view's availability.

`diagnostics/__init__.py` owns import-light public exports. The existing
`diagnostics/run_inspection.py::RunInspectionFailure` is a separate closed-code
protocol and stays unchanged. Add the current diagnostic behavior under the
existing diagnostics package; private file/helper names remain discretionary.
`docs/structure.md` sections 4 and diagnostics ownership prohibit lower pipeline,
store and executor modules from importing diagnostics. Queue readiness/probe
composition already consumes diagnostic models; the owner-view composition may
consume the new diagnostic projector without moving it into pipeline code.

`cli/queue.py::handle_daemon_admission` reads the existing socket endpoint and
currently uses `_emit_daemon_payload`, whose text branch prints mapping values.
Use the new public renderer for this admission diagnostic presentation, leaving
JSON as the existing generic envelope and unrelated daemon output unchanged.
No new endpoint or queue-to-CLI dependency is needed.

Known tests: `tests/integration/queue/test_local_daemon_production.py` contains
the complete-or-unavailable test and actual socket owner-view assertions;
`tests/unit/loom/cli/test_queue.py`, `tests/e2e/test_queue_cli.py`,
`tests/integration/queue/test_cli_operations.py`, existing diagnostics unit tests,
and `tests/package/test_import_boundaries.py` own adjacent boundaries. Locate
actual assertions before selecting or extending them; a test name alone is not
coverage. Existing closed owner-key assertions must gain the eighth field.

`make validate-pr` and `make test-summary` are both required. The config-extra
environment must execute its selected cases; physical container acceptance is
opt-in and outside this phase. Do not change the harness or dependencies.

## Scope And Fixed Contracts

1. Add exactly `diagnostic_failure` to the existing `run_result` owner mapping:
   null when available, detached diagnostic mapping when unavailable. Preserve
   `diagnostic=run_store_unavailable`, `failures=[]` on any required read failure,
   and all original owner/state/time/ordering/attempt checks.
2. Use exactly the canonical `loom.diagnostic.v1` shape: root schema/type/message/
   links; nested type/message/links; ordered cause/context/group_child links with
   exactly record or cycle/limit truncation. Root-inclusive projection admits
   128 materialized occurrences, explicit cause wins, suppressed context is
   omitted, group order and active-ancestry cycle detection are preserved.
   Native messages may be empty; broken formatting uses
   `<exception message unavailable>`. No tracebacks, notes, locals, environment
   dumps, arbitrary exception attributes or downstream dependency.
3. Capture the actual authority/store/codec error at the read owner. Missing
   required facts raise a specific owner-authored explanation. Higher wrappers
   preserve causes. The returned mapping retains no live exception.
4. Expose `loom.diagnostics.render_diagnostic_failure(value)`, which strictly
   validates the canonical shape before rendering nested types/messages/relations.
   Invalid external data raises a diagnostic boundary error; never import the
   named type or stringify arbitrary input. The projector can remain private.
5. Current admission text uses that public renderer. Preserve its JSON mapping,
   endpoint authorization, ordinary successful/empty views and application
   failures. Messages and paths are private diagnostic content; document that
   existing authorized inspection access can disclose them. This is not a new
   sanitization policy or an endpoint-access redesign.
6. P8 owns downstream dependency adoption and its old-seven-field reader behavior.
   Do not implement a second rphys decoder or edit rphys in this Loom phase.

Out of scope: Stage 85 composition/preparation, the resource-policy draft,
application failure schemas, execution/cancellation/retry changes, new stores,
inspection indexes, endpoints or wait states, physical runs and hosted CI.

## Proportionality And Validation

The existing owner mapping is extensible PlainData; do not bump unrelated outer
schemas. The diagnostic format has current CLI and downstream presenter consumers.
One diagnostics owner validates its format; existing lower owners continue to
validate their own facts. Keep primitive/generic transport codecs generic.

| Boundary | Required discriminating evidence |
| --- | --- |
| Diagnostic projection and strict rendering | Native nested cause/context, suppression, ordered group children, shared child versus true cycle, 128-occurrence limit, broken formatting and malformed external shapes |
| Complete failure owner | Existing `test_run_result_owner_projects_complete_failures_or_fails_closed` variants retain distinct missing/corrupt/read/authority reasons and never leak a partial list after a later failed read |
| Authority handoff | Real injected authority-read error survives outer owner assembly, not a newly fabricated replacement message |
| Endpoint and admission CLI | Actual socket response carries the new mapping, text renders its chain, JSON retains it, and success/empty/ordinary application failure behavior remains correct |
| Import/public contract | Import-light diagnostics public renderer, no lower-layer diagnostics dependency or downstream imports, intended public exports and documentation |

Use existing fixtures and entrypoints. Select focused new diagnostic tests plus
the named owner/CLI/public tests while developing, then run both final commands
on one stable source/test tree. Preserve exact command, revision/tree, reports,
raw JUnit and skipped-case disposition in this card. Keep raw final-gate logs
when practical. No physical proof is required. Expand only for an affected
current consumer, demonstrated defect or missing accepted oracle.

## Review, Coordination And Executor Handoff

P11 changed only static validation/CLI owners; published PR #286 changes lifecycle
ownership but not these result-view functions. The reviewed canonical amendment
therefore remains current without another planning pass. Stage 85 P7 is separately
active in its own worktree: it owns `queue/managed_local_preparation.py`, its lazy
queue export and preparation tests. Preserve those changes and avoid adopting
unpublished code. Its docs/public-test edits may require scoped merge reconciliation
on then-current develop, not a change to P12 requirements.

Executor owns only diagnostics implementation/public exports, the two owner-view
functions and their necessary imports/private handoff, admission CLI presentation,
affected tests/user docs, and this card's completion record. You are not alone;
preserve others' work. Do not edit the manifest, rphys, Stage 39/85, dependencies,
workflows or other worktrees. No child agents, PR creation, merge or physical run.
Stop for an actual accepted-contract conflict; private wiring is discretionary.
Return coherent commits, clean worktree and terminal revision-bound evidence.
Manager owns independent actual-PR review, publication, merge and cleanup.

## Workflow State And Completion

- Manager setup: complete on clean published base; canonical readiness reused.
- Implementation: complete at `c4f9120645e14b1dce8b8e8685b40371256b5e48`;
  the initial implementation is `bc270a4362271796d592d1f93f68d870af1657cf`.
- Optional planner/refiner: unused; correction 1/3 completed for the boundary
  evidence gap by the same executor.
- Independent review: required after implementation and both local gates.
- PR, merge and cleanup: pending; correction validation is recorded below.

Manager pre-submit verification: corrected revision
`c4f9120645e14b1dce8b8e8685b40371256b5e48`, tree
`5d9e1a88b43d59551b3df869e281c839968f314e`, has both required passing gates.
The delta to executor completion `5f964b0d1f23bc8869d6f359ec05fb45b45f878c` is this
card only. Manager inspected both raw gate logs and parsed the six JUnit groups:
3,179 passes, no failures/errors and 18 opt-in container skips. All damage
variants, diagnostic tests and both real endpoint/client/CLI parameter cases
executed successfully. Scope, import direction and the correction diff align
with the fixed contract; no runtime change accompanied the test correction.
Fetched Loom develop remains `d444284`, with no source/dependency drift. This
receipt and the manifest update are documentation-only. Independent actual-PR
review is the remaining pre-merge gate.

### Manager Pre-submit Correction

The real socket assertions added by the implementation exercise an available
view whose `diagnostic_failure` is null. Unavailable diagnostics are checked
only through direct owner assembly, and admission text/JSON uses a mocked
socket client. This does not yet prove the accepted non-null nested diagnostic
survives the actual endpoint boundary. The damage variants other than authority
failure assert only nonempty type/message, so a generic replacement would pass
instead of each original missing/corrupt/read reason. These are gaps in the
approved Endpoint And Admission CLI and Complete Failure Owner oracles, not
new product criteria.

Smallest correction: extend the existing actual socket fixture to return an
unavailable owner view with a real captured nested reason; inspect it with the
real client and admission CLI, checking that `failures` remains empty and the
specific cause survives text/JSON transport. Strengthen the existing damage
variants' reason assertions. Keep successful/empty and ordinary application
failure cases. Also make the existing limit test render/serialize its projected
128-node value: manager read-only probes already pass direct rendering, plain
conversion, freezing and JSON round-trip, but that accepted boundary is not
asserted by the test. Do not create a backend matrix or alter runtime semantics
without a demonstrated regression.

Localized documentation correction in the same scoped pass: move the new
inspection paragraph out of the middle of the existing cancellation paragraph
in `docs/features/queue.md`, preserving both meanings and Stage 85's separate
preparation ownership. Preserve initial evidence as historical; run the focused
owner/endpoint/CLI/diagnostic tests and refresh both final Loom gates on the
stable corrected tree. No new public API or planning decision is required.

Resolved at `c4f9120645e14b1dce8b8e8685b40371256b5e48`: the actual
socket/client/CLI unavailable-diagnostic oracle, distinct damage-reason
assertions, and 128-node serialization/render assertion now cover this bounded
gap; the queue documentation paragraph is in the admission section.

## Completion Record

- Implementation and changed paths: added the detached `loom.diagnostic.v1`
  projector/strict renderer under `src/loom/diagnostics`, added the eighth
  `run_result.diagnostic_failure` member and authority-cause handoff in local
  daemon owner assembly, rendered it only for admission text output while
  retaining the generic JSON envelope, and documented the existing authorized
  disclosure boundary in `docs/features/queue.md`. The admitted correction
  added only boundary assertions and relocated that documentation; it made no
  runtime change.
- Commits: `bc270a4362271796d592d1f93f68d870af1657cf` (`Add Loom inspection
  failure diagnostics`), `c4f9120645e14b1dce8b8e8685b40371256b5e48`
  (`Strengthen inspection diagnostic boundary tests`).
- Tests added or updated by suite: diagnostics projection/strict-renderer unit
  coverage; queue CLI text/JSON presentation unit coverage; local-daemon
  owner-view, authority-cause, actual socket, and eight-owner-key integration
  coverage; diagnostics public-import coverage. The correction adds an actual
  socket/client/admission-CLI unavailable-diagnostic oracle, exact
  missing/corrupt/read/authority damage-reason assertions, and the projected
  128-node plain-data/JSON/render round trip.
- Initial targeted validation: `uv run pytest`
  `tests/unit/loom/diagnostics/test_diagnostic_failure.py`
  `tests/package/test_import.py::test_import_loom_diagnostics_public_api`
  `tests/unit/loom/cli/test_queue.py::test_queue_daemon_admission_renders_private_diagnostic_failure`
  `tests/integration/queue/test_local_daemon_production.py::test_run_result_owner_projects_complete_failures_or_fails_closed`
  `tests/integration/queue/test_local_daemon_production.py::test_daemon_projects_stage_failure_to_authority_run_and_admission`
  passed 15 tests. Changed-path Ruff and Pyright both passed.
- Correction targeted validation: `uv run pytest`
  `tests/unit/loom/diagnostics/test_diagnostic_failure.py`
  `tests/unit/loom/cli/test_queue.py::test_queue_daemon_admission_renders_private_diagnostic_failure`
  `tests/integration/queue/test_local_daemon_production.py::test_run_result_owner_projects_complete_failures_or_fails_closed`
  `tests/integration/queue/test_local_daemon_production.py::test_daemon_projects_stage_failure_to_authority_run_and_admission`
  passed 14 tests. Changed-path Ruff and Pyright both passed.
- Initial `make validate-pr` result: passed at the initial validated revision.
  Default lane: 3,018 passed, 155 opt-in deselections; config-extra: 161
  passed, 18 expected opt-in skips; package build passed. Raw receipt retained
  at `build/phase-12-validation/validate-pr.log`.
- Corrected `make validate-pr` result: passed at the corrected revision. Default
  lane: 3,018 passed, 155 opt-in deselections; config-extra: 161 passed, 18
  expected opt-in skips; package build passed. Raw receipt retained at
  `build/phase-12-validation/validate-pr-correction-1.log`.
- Initial `make test-summary`: passed at the initial validated revision; raw
  gate log: `build/phase-12-validation/test-summary.log`.
- Corrected `make test-summary` and `build/test-summary.md`: passed at the
  corrected revision. Package 122, unit 2,149, contract 300, integration 379,
  e2e 68, and config-extra 161 passed; config-extra retained 18 expected
  opt-in skips. Summary: `build/test-summary.md`; raw JUnit/coverage receipts:
  `build/test-summary/{package,unit,contract,integration,e2e,config-extra}/`;
  raw gate log: `build/phase-12-validation/test-summary-correction-1.log`.
- Validated revision or tree state: clean source/test/configuration tree at
  `c4f9120645e14b1dce8b8e8685b40371256b5e48` before this completion-record-only
  edit; the initial gate evidence at
  `bc270a4362271796d592d1f93f68d870af1657cf` remains historical above.
- Later validation-relevant changes: none; this completion-record edit changes
  no source, tests, dependencies, build, or validation configuration.
- Scope or fixed-contract variance: none.
- Residual blocker or risk: no blocker. Physical/container acceptance remains
  opt-in and outside P12; its 18 config-extra skips are explicitly reported
  above.
