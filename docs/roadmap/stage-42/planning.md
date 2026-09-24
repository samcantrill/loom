# Stage 42: Run Discovery, Annotations, Lineage, And Result Access

Planning layout: `planning-manifest-and-cards-v1`

Status: detailed six-phase plan approved by the maintainer; independent plan
readiness review passed. Documentation publication is authorized; implementation
has not started.

Roadmap source: [v42](../../roadmap.md#v42---run-discovery-annotations-lineage-and-result-access).

Evidence base: `/nas/home/can134/work/loom-worktrees/control-stage-40`, clean
`develop` at `220358ed26392f30bb2f36bf09d547607a57d442`.
Documentation branch: `agent/run-discovery-results-stage` in
`/nas/home/can134/work/loom-worktrees/run-discovery-results-planning`.
The preserved original Loom checkout contains unrelated work and is not the
evidence or write tree for this stage.

## Outcome And Current Task

Loom lets callers describe executions, discover them from recorded facts, trace
their dependencies, and retrieve their published outputs without understanding
the application's domain. This packet records the agreed implementation design,
phase plans, validation obligations and plain-language code walkthrough. The
current handoff publishes that documentation; it does not start implementation.

The maintainer accepted the behavior and illustrative interface walkthrough on
2026-09-24, requested detailed stage documentation, and then requested this
expanded implementation plan. That agreement fixes the intent below. The cards'
detailed implementation sections now propose concrete native methods, durable
ownership/migrations, query consistency, binding capture and artifact access.
The maintainer subsequently approved committing and merging this concrete packet
into `develop`; that approval is recorded below. Product execution remains a
separate explicit request.
Examples are proposed Python-shaped code and sample data; they are not APIs
already available in today's package.

- [Implementation manifest, phase order and review](implementation-plan.md)
- [Plain-language implementation walkthrough with code](implementation-walkthrough.md)

## Planning Card Index

Each detailed requirement, example, validation, and design decision ID has one
authoritative card. Cards link to one another instead of redefining contracts.

| Card | Scope | Owned IDs | Dependencies |
| --- | --- | --- | --- |
| [Run context](planning/run-context.md) | Submission intent, run identities, tags, structured metadata, descriptions, notes, and mutation boundaries | `FR-42-C01`–`C07`, `EX-42-C01`–`C03`, `VAL-42-C01`–`C05`, `DQ-42-C01`–`C04` | Existing native submission and authority/store contracts |
| [Discovery](planning/discovery.md) | Search scope, native/caller fields, typed filters, tag vocabulary, time/provenance semantics, pages and coverage | `FR-42-Q01`–`Q07`, `EX-42-Q01`–`Q04`, `VAL-42-Q01`–`Q06`, `DQ-42-Q01`–`Q04` | Run-context identity and metadata definitions |
| [Output access](planning/output-access.md) | Directed dependencies, committed output selection/history, content access, batch results, application boundary, and client parity | `FR-42-A01`–`A09`, `EX-42-A01`–`A06`, `VAL-42-A01`–`A08`, `DQ-42-A01`–`A05` | Run-context identities and discovery scope/coverage |

## Scope And Ownership

| Owner | Responsibility |
| --- | --- |
| Calling application | Choose pipeline/configuration, supply all domain tags/metadata, declare output types and complete artifact files, interpret retrieved contents |
| Loom coordinator and existing native client | Accept explicit requests, retain submission/operation associations, expose scoped queries and supported annotation/access operations |
| Loom authority and owning stores | Preserve authoritative lifecycle, accepted metadata/intent, committed output and consumption facts; expose supported reads/mutations |
| Loom catalog/read models | Derive searchable projections from owning facts; remain rebuildable and report freshness/coverage |
| Loom artifact access/materialization | Resolve selected references and obtain supported declared files with existing integrity/provenance guarantees |
| Python, CLI, and optional MCP | Present one behavioral contract with transport-appropriate bounded results |

No built-in dataset/model/study vocabulary, experiment entity, scientific metric
query language, config inspection heuristic, or application reader belongs in
Loom. Organizational fields do not become execution or artifact reuse identity.
Recorded native fields remain distinguishable from caller-supplied claims.

Prerequisites: the v40/v41 native client and lifecycle, current authority-backed
run/store/provenance interfaces, catalog discovery, immutable output commits, and
supported artifact materialization. Relevant earlier feature areas are v8,
v9/v10, v12, and v15/v16; historical direct/offline execution behavior is not
reintroduced by this stage.

## Existing Behavior And Minimum Extension

The evidence base already includes runtime tags and notes, an exact-match
`RunCatalog`, native run inspection, artifact references and published commit
history, and explicit materialization primitives. It does not establish the
complete accepted query/annotation/lineage/retrieval journey as one agent-facing
interface. Source and tests named in each card delimit current facts from future
requirements.

Extend those owners. Do not create a second run authority, an independent
experiment database, or a mandatory plugin registry. The current consumers are
people and agents organizing real submitted work and accessing its outputs. A
read-only catalog sidecar can remain a derived implementation detail; a durable
snapshot/query store needs a demonstrated requirement before it is introduced.

## Material Intent Decisions

| Decision | Owner and accepted consequence |
| --- | --- |
| All domain labels are caller supplied | Run context: `dataset` and `model` are valid ordinary tags; Loom never infers their meaning |
| Native and supplied facts are queryable together | Discovery: expose supported fields/operators and preserve types, provenance, time meanings, and missing evidence |
| Use existing identity | Run context: use `run_uri`; retain stage/job/attempt/artifact roles rather than creating another execution ID |
| Lineage follows recorded relationships | Output access: distinguish declared ordering and actual artifact consumption; preserve cross-run reuse origins |
| Output selection and payload retrieval are separate | Output access: default current commits, explicit history, exact selected versions, complete declared files, per-item outcomes |
| Capture why work was launched | Run context: original intent stays recoverable alongside later edits and notes |
| Client behavior is shared | Output access: Python/CLI/MCP use the same native semantics, with bounded transport-specific presentation |

## Design Handoff

The `DQ-42-*` tables now record concrete proposals in their owning cards. The
[implementation manifest](implementation-plan.md) maps accepted requirements,
examples, validation and decisions to six usable merge outcomes: submission
context, annotation mutations, discovery, exact output selection, dependency
lineage, and artifact access. Each phase includes its native interface,
Python/CLI/MCP adapters, tests and documentation.

Material choices made explicit for review are: immutable original submissions
separate from mutable annotations; revision-safe patches and append-only notes;
finite typed predicates with live, non-snapshot pages; original-producer commit
selectors; per-attempt input capture rather than historical guesses; and complete
declared file transfer through existing Unix/authenticated HTTPS infrastructure.
Private helpers, table names and batching implementations remain discretionary.

The [planning workflow](../../../.codex/workflows/roadmap-stage-planning.md) owns
final review, approval and landing. Implementation startup refreshes source drift
and uses the separate persistent stage worktree only after those gates.

## Validation And Review State

The cards record behavioral validation obligations and discriminating examples.
Those describe future implementation acceptance, not tests run for this prose
change. Documentation checks cover links, examples labelled as proposals, ID
ownership, stage numbering, diff hygiene, and scope consistency.

| Gate | State |
| --- | --- |
| Maintainer agreement on intent and illustrative behavior | Accepted in the 2026-09-24 discussion |
| Detailed intent and implementation design | Complete reviewed proposal in the indexed cards |
| Implementation manifest and six phase cards | Complete reviewed proposal, all implementation phases pending |
| Independent complete-packet readiness review | See authoritative receipt below |
| Concrete implementation-plan approval | Accepted; see approval and publication handoff below |
| Packet landing | Publication handoff below owns the PR reference; startup verifies its merged state and exact paths on the selected base |

The [implementation plan review](implementation-plan.md#implementation-plan-review)
is the sole final readiness receipt. The earlier bounded intent documentation
review is superseded for readiness purposes by this materially expanded packet.
Prose/link/example checks are not runtime test evidence. No product implementation
or execution validation is claimed by this planning task.

## Approval And Publication Handoff

On 2026-09-24, after reviewing the detailed implementation walkthrough, the
maintainer explicitly requested committing this packet and merging it into
`develop`. This approves the documented scope, six phase boundaries, risks and
deferrals for publication. It does not request running the implementation phases.

Publication scope is `docs/roadmap.md` and all twelve Markdown files under
`docs/roadmap/stage-42/`. The merge record for
[planning PR #348](https://github.com/samcantrill/loom/pull/348) is the landing authority;
implementation startup must verify these exact paths are tracked, path-clean and
present on its fetched `develop` base. No self-referential merge SHA is stored in
the packet.

The [implementation manifest](implementation-plan.md#execution-context) names
the separate persistent `stage-42` worktree, coordination branch and six phase
branches. Start execution through `$loom-roadmap-implementation` after publication
is verified, not on the planning branch or local `develop`.

## Non-Goals And Reopen Triggers

No separate hosted tracking/catalog server, dashboard, cross-deployment federation,
arbitrary SQL/expression execution, semantic/vector search, metric extractor,
general authorization redesign, automatic rerun/cancellation/deletion, or new
cloud-storage SDK family. Existing scoped coordinator access policy applies.
Application-specific integration changes, such as an rphys summary reader, belong
downstream.

Reopen affected decisions if a required field is not captured today, a supported
artifact backend cannot provide the required files, recorded cross-run identity
cannot establish a needed edge, existing replay/fingerprint rules conflict with
annotations, or a proposed query guarantee needs new durable state. Do not infer
missing provenance or introduce hidden state to make examples appear supported.
