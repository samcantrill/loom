# Refined Loom Stage Implementation Workflow

Status: approved on 2026-09-10; implemented, validation and independent review in progress
Scope: repository workflow and Git tooling; no Loom runtime changes
Delivery: one maintenance PR to develop, with three bounded implementation units

## Outcome And Rationale

Adapt rphys's refined implementation workflow into Loom's existing workflow
owners. Every roadmap stage uses one persistent Loom worktree from startup
review through final closeout. Each phase retains its own branch and PR. A
mandatory helper checks repository, worktree, branch, merge and synchronization
facts before the manager proceeds.

This addresses the Stage 41 isolation concern with executable checks and one
stable working directory. Independent review remains separate from authorship;
the normal phase uses a manager implementation pass and one independent reviewer.
An executor is optional when size or context isolation justifies delegation.

Keep Loom's accepted behavior, phase boundaries, validation obligations and
domain-neutral architecture. This is an amendment to implementation mechanics,
not a new product roadmap stage or a reopening of Stage 40/41 design approval.

## Source Evidence And Changes

Loom evidence: develop at `a16582d14caeb03c4925980e8c995c592473b18d`.
The rphys reference implementation is `tools/phase_workflow.py`, its repository
tests, `.codex/workflows/roadmap-version-implementation.md` and
`.codex/prompts/phase-loop-management.md`; the latest inspected commit touching
these implementation assets is `9089f06fd312e1e215167fda50fa221a7548dde6`.
Implementation began at that Loom base; the reference helper was adapted in place.

| Owner | Replaced behavior | Implemented change |
| --- | --- | --- |
| [AGENTS.md](../../AGENTS.md) and [implementation workflow](../workflows/roadmap-stage-implementation.md) | One worktree per phase; mandatory executor; conditional independent reviewer | One worktree per stage; optional executor; required independent phase review |
| [Manager prompt](../prompts/phase-loop-management.md) | Manual isolation checks, per-phase worktree removal, local continuation fallback and direct local develop metadata edits | Shared mandatory Git gate, coordination branch, published metadata and synchronization before continuation |
| [Workflow modernization record](workflow-modernization.md) | Records the earlier lean conversion | Update its current implementation summary when this refinement lands; retain lean planning |
| [Stage 40 manifest](../../docs/roadmap/stage-40/implementation-plan.md) and [Stage 41 manifest](../../docs/roadmap/stage-41/implementation-plan.md) | Approved pending phases with per-phase worktree instructions | Amend execution metadata to one stage worktree without changing product contracts |
| rphys Git helper | Implements most required Git mechanics, but hardcodes rphys repository/paths | Adapt to Loom identity and explicit execution paths; no runtime dependency on rphys |

All four Stage 40 and all nine Stage 41 cards already require independent
implementation review. The review-policy change mainly corrects the default
workflow and future templates; it does not add another review round to those
cards. Existing plan review receipts remain usable unless relevant contracts
have changed.

The original Loom checkout contains unrelated work on a preserved branch.
The maintenance work uses its dedicated workflow-refinement-plan worktree.
Control checkout establishment follows publication; preserve other checkouts.

## Fixed Workflow Decisions

1. Use one stage worktree and a named `agent/stage-<N>` coordination branch.
   Keep phase names `agent/stage-<N>-p<P>-<phase-slug>` and one phase PR to develop.
2. Bootstrap the stage worktree before startup review or any implementation
   writes, including changes to the manifest and phase card. All subsequent
   stage work, tests, receipts, metadata and closeout stay there.
3. Require preflight before each agent assignment and manager write, test or
   review pass. Agents receive the verified absolute worktree, branch, evidence
   revision, artifact paths and write boundary. Commands use that working
   directory explicitly. The helper checks admission; it is not a filesystem
   sandbox or a guarantee against later arbitrary shell commands.
4. Require one independent review of each phase's actual PR head. Manager
   implementation is the default; an executor is optional. Preserve bounded
   planners/refiners, existing correction budgets, pointer-only handoffs and
   prohibition on child delegation. Keep Loom's existing model assignments.
5. Preserve `make validate-pr` and `make test-summary` as required implementation
   gates. Reuse fresh results; retain all phase-specific acceptance and live
   qualification obligations. Do not import rphys-specific test selectors or
   reduce these obligations under a generic targeted-validation policy.
6. Require remote phase merge, published completion metadata and synchronization
   before starting the next phase. Remove the local continuation exception.
   A blocked predecessor does not authorize a successor automatically.
7. Author metadata on the coordination branch and publish with an ordinary
   non-force push to develop when authorized. Never edit or commit on local
   develop; update it only by a clean fast-forward.
8. Stop or finish every agent and background process using the stage worktree
   before switching branches. Retain the stage worktree through final metadata
   publication and synchronization; retire only verified phase branches.

## Execution Layout And Repository Identity

Record the selected control path, worktree root and stage path once in the
manifest's execution context. Templates and supporting prompts reference that
context and the manager gate instead of repeating host-specific paths.

Recommended layout for this installation:

```text
/nas/home/can134/work/loom-worktrees/
  control/                   clean linked checkout on develop
  stage-40/                  Stage 40 worktree, retained across its four phases
  stage-41/                  Stage 41 worktree, retained across its nine phases
```

The control checkout is an ordinary linked worktree of the existing Loom
repository. Create it only after checking registered worktrees and verifying
that develop is available and can fast-forward to origin/develop. If an eligible
clean control checkout already exists, use it. Occupied paths, divergent refs or
unrelated edits cause a stop; they never authorize a reset, deletion or branch
takeover. Preserve the original dirty checkout and every unrelated worktree.

The Loom helper accepts explicit control and worktree-root paths. Verify their
shared Git common directory and that origin resolves to `samcantrill/loom` using
the supported GitHub HTTPS/SSH URL forms before remote actions. GitHub calls use
that explicit Loom repository. Tests substitute fixture repositories and a
fake GitHub boundary; production commands cannot silently target rphys.

This is a small Loom-owned tool, not a shared cross-repository workflow package.
Use Python 3.12 and the standard library. Do not import Loom runtime modules or
require rphys to be installed. Private helper structure remains discretionary.

## Git Helper Contracts

Add `tools/phase_workflow.py`, adapting rphys's existing behavior and tests.
Retain the six command roles below. Each receives the execution context and
returns bounded JSON facts or a nonzero failure with a useful reason. No new
workflow database, durable receipt format or metadata sidecar is needed.

| Command | Inputs and successful outcome | Refusal or recovery behavior |
| --- | --- | --- |
| `setup` | Stage, canonical phase suffix, current approved base SHA and required dependency merge SHAs; create the stage worktree, first phase branch and coordination branch at that base | Verify clean control, current remote base and dependency ancestry first. Refuse occupied paths/branches. After partial setup, inspect existing state and resume verified work; never rerun by resetting it |
| `preflight` | Stage and assigned branch; verify actual working directory, common repository, stage identity and current branch; report HEAD and existing edits | In-phase edits are reported for manager ownership review. A requested clean gate refuses them. Wrong repository, path, stage or branch refuses the operation |
| `deliver` | Exact PR number, head branch, title, reviewed HEAD, evidence-reconciled validated HEAD, existing evidence file and manager review/validation dispositions | Require clean matching local HEAD, develop target, accepted review/evidence, non-draft open mergeable PR or the matching already-merged PR. Squash-merge with head matching and verify remotely even after a CLI error |
| `transition` | Current phase and its remotely merged PR; switch the clean stage worktree to its coordination branch and synchronize to published develop | Verify PR identity, merge ancestry and current phase HEAD. Extra local commits, dirty work or unverified merge remain intact and block transition |
| `sync` | Coordination branch after metadata publication; fast-forward only published work and clean local develop; verify stage HEAD, local develop, fetched origin/develop and advertised remote develop match | Refuse unpublished/divergent state and remote advancement. Reconcile unpublished metadata without force-pushing, then repeat the gate |
| `start` | Next phase suffix plus previous PR/branch; create the new phase branch at synchronized develop in the same worktree | Repeat previous-merge and synchronization checks. Refuse an occupied next branch or failed predecessor gate |

Bind phase suffixes to the supplied stage number, rather than accepting any
syntactically valid branch from another stage. The manager still owns phase
ordering, dependency completeness, metadata contents and acceptance judgment;
the helper does not infer them from Markdown.

Evidence must identify what was tested and reviewed. A metadata-only delta may
carry existing validation forward after inspection; relevant source changes
require affected checks. Independent review covers the final submitted change,
with affected corrections confirmed within the existing review budget. Do not
create self-referential commit-SHA receipts or claim that an approval flag proves
test coverage.

After a verified merge, remote branch retirement must check the expected ref
and use a lease so a concurrent push is preserved. Unknown cleanup outcomes
remain unknown. Local branch/worktree cleanup stays manager-owned and uses exact
recorded identities; no prefix-wide deletion. Squash-merged phase commits require
verified PR-head/merge evidence rather than a normal ancestry-only deletion test.

Hosted CI remains disabled. A rejected merge is inspected against the actual
rule. Do not bypass failing validation, conflicts or required hosted checks.
Retain Loom's narrow review-only admin exception only after local evidence and
independent review pass and the protection rule is verified; do not fall back
to admin automatically for any merge error. Missing independent review requires
an explicit recorded maintainer override or remains blocked.

## Implementation Units And File Ownership

Deliver these units as reviewable commits in one maintenance PR. Activating only
the prose or only the helper would leave contradictory execution instructions.
This is ordinary repository maintenance, not an extra Stage 41 product phase.

| Unit | Owned changes | Reviewable outcome |
| --- | --- | --- |
| 1. Port and test the Git gate | New `tools/phase_workflow.py`; new `tests/integration/tools/test_phase_workflow.py`; relevant test documentation | All six commands work against temporary real Git repositories and a fake GitHub boundary, including a two-phase lifecycle |
| 2. Make the workflow use the gate | `AGENTS.md`; implementation workflow; manager prompt; active supporting prompts, templates and agent descriptions; workflow README and modernization record | One authoritative procedure covers startup, authorship/review, delivery, metadata, synchronization and cleanup; callers refer to that procedure |
| 3. Adopt it for pending stages | Stage 40/41 manifests and affected phase metadata; execution examples; this plan's completion facts | Both approved plans point at the same persistent-stage mechanism; their behavior and validation obligations are preserved |

For Unit 2, inspect and update `phase-execution-plan-draft.md`,
`implementation-phase-execution.md`, `pull-request-review.md`,
`pr-body-draft.md`, `implementation-test-refinement.md`,
`phase-execution-plan-refine.md` and `subagent-lifecycle.md` where their existing
instructions assume another owner or isolation model. Remove duplicated Git
procedures from those callers; the manager prompt owns sequencing and the helper
owns mechanical checks.

Update the active phase/manifest templates to record the stage worktree,
coordination branch and required independent review. Adjust executor/reviewer
role descriptions to match optional execution and mandatory review; preserve
their authority boundaries and configured models. Audit references to retired
sidecar templates and change only still-consumed conflicting instructions.
Leave completed historical plans and retired unreferenced artifacts alone.
Planning stays lean; this change does not require independent review for every
ordinary documentation task or every planning pass.

For Unit 3, replace per-phase worktree creation/removal wording in the pending
Stage 40/41 manifests and cards. Preserve phase names/order, fixed contracts,
walkthroughs, approval records, review focus and all validation requirements.
Record this as an execution-mechanics amendment. Update source/harness references
only where the workflow change makes them stale. Other unfinished stages are
audited when resumed, not bulk-migrated in this PR.

## Validation And Acceptance

Adapt rphys's existing tests to Loom's integration suite instead of adding a
repository-specific marker or separate test harness. Use disposable repositories
with a local bare origin for Git behavior and controlled GitHub responses for
PR operations. No tests push to real develop, merge a real PR, delete a real
worktree or launch Loom services.

| Boundary / supported failure | Required evidence |
| --- | --- |
| Setup from a stale base, missing dependency, occupied path/branch or dirty control | Refusal preserves files and refs; clean setup creates the expected stage and coordination branches |
| Invocation from control, another repository/stage or an incorrect branch | Preflight refuses the wrong execution location; owned in-phase edits are reported and preserved |
| PR head/title/base mismatch, missing evidence or unmergeable PR | No merge request occurs; a different local HEAD also refuses delivery |
| Merge succeeds remotely but CLI reports failure, or CLI success is not followed by remote merge | Reconciliation uses the actual PR result and never claims an unverified merge |
| Remote branch moves during retirement | The lease preserves the new commit; authentication failure is not reported as successful deletion |
| Transition with extra phase commits, dirty control or unpublished coordination metadata | Work is preserved; no next phase starts |
| Two sequential phases with published metadata, interrupted delivery and remote advancement | One stage path is reused; each phase has its own branch; restart repeats the appropriate gate; advancement requires reconciliation |
| Final closeout | Coordination metadata is published and synchronized before exact stage cleanup; retained unknown/unmerged work prevents a false completion claim |

One temporary two-phase scenario owns the successful end-to-end proof. Add
focused refusals at the corresponding public/Git/GitHub boundaries rather than
a Cartesian matrix. Test shell/process calls as argument arrays; no command
interpolation of repository paths or PR bodies.

Run the affected integration tests during development, then the existing
`make validate-pr` and `make test-summary` gates on the stable implementation.
Check links, active instruction consistency and preservation of Stage 40/41
contracts. Independent review covers the actual maintenance PR diff, particularly
repository identity, destructive operations, metadata publication and evidence
freshness. Do not repeat a passed gate without a relevant change or failure.

Validation and delivery facts are recorded in Completion below. Git tests use
disposable repositories; they do not establish Stage 40/41 product execution.

## Rollout, Bootstrap And Open Decisions

The maintenance PR must bootstrap without depending on its unmerged helper.
Use a dedicated ordinary Loom worktree and maintenance branch from current
develop, existing local validation and an independent review. Merge under current
Loom policy; the refined workflow becomes authoritative once the coherent change
is published. Do not execute an untested new helper against real branches to
prove its own merge gate.

After publication, establish or verify the clean control checkout and exercise
the first authorized stage startup. Do not create a Stage 41 execution branch
against an incomplete dependency: all Stage 40 implementation phases must be
merged and their completion metadata published before Stage 41 starts. Merged
planning documents alone do not satisfy that requirement. Stage 40 is the first
candidate for adoption if still unstarted when this work lands.

If execution begins concurrently before adoption, finish or pause the active
phase, stop its processes and verify its exact branch/worktree/PR ownership.
Preserve it and make one explicit transition at a safe boundary. Do not move or
switch an actively used worktree or rewrite an open PR as a routine conversion.

No product behavior decision is open. Resolve these mechanical facts from the
live repository when implementation starts:

- Whether an eligible clean control checkout already exists, and the exact
  available control path and local develop state.
- Whether pending stages remain unstarted; otherwise identify the safe adoption
  boundary without changing accepted phase scope.
- Whether current branch protection permits the existing metadata-publication
  procedure. If it rejects publication, retain the coordination branch and
  record the exact blocker; do not silently weaken the synchronization gate.

A reusable multi-repository workflow package, code-intelligence rollout, model
changes, new planning roles, automatic acceptance parsing, global Git locking
and CI activation are outside this change. The manager serializes transitions
for its stage; the helper detects relevant mutable-state changes but does not
claim to lock out all external Git users.

Complete when the helper and tests are delivered, active Loom instructions agree,
the pending-stage metadata is amended, required validation and independent review
pass, and the maintenance PR is merged. Record any environment-dependent adoption
check still pending separately; do not claim Stage 40 or Stage 41 implementation
has started or completed as part of this workflow migration.

## Completion

- Implementation: six-command Loom Git helper and integration coverage added;
  active instructions and all thirteen pending Stage 40/41 phase cards use the
  shared stage-worktree contract. Product contracts and phase order preserved.
- Targeted evidence: 53 integration tests passed in the initial implementation
  run. Required final gates and independent review are pending.
- Delivery: pending maintenance PR and merge; no Stage 40/41 runtime work started.
- Control/adoption: clean control checkout establishment follows publication.
