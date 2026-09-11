# Phase 4 Execution Plan: MCP Tools And Portable Loom Skills

## Metadata

- Status: in_progress
- Roadmap stage and phase: 40 / 4
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-40-p4-mcp-skills
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `d9b283b5352b6ab246af30fb9d6f67c51853361b`, published Phase 3 completion metadata.
- PR target: develop
- PR title: Stage 40 Coordinator Client, Agent Preparation, And MCP - Phase 4: MCP Tools And Portable Loom Skills
- Dependencies: Phase 3 PR #302 merged at `82ee364bc73856be2f709ff5ac682fc9a4844b27`; metadata published, synchronization passed and both phase branches retired.
- Workflow path: expanded for assistant mutation/error semantics and dependency isolation
- Blockers: none; no refinement needed

## Objective And Context

A Codex session uses Loom tools to prepare, submit, observe and cancel through the
completed native coordinator API. Four generic operational skills make the same
workflow usable in unrelated projects. Deliver FR-40-10/11/12 using the native
contracts of FR-40-01 through 09 and DQ-40-07.

The MCP adapter owns no scheduling, preparation state, source staging, application
policy or database. Native gaps discovered here go back to their owning phase;
do not repair them with subprocess CLI parsing or an MCP-specific implementation.

## Current Source And Harness

- Phase 1's `loom.coordinator.CoordinatorClient`, Phase 2's preparation APIs and
  Phase 3's staged input support over those same APIs.
- `pyproject.toml`, `uv.lock`: dependency extra and script registration.
- `src/loom/mcp/`: implemented adapter and entrypoint.
- `skills/loom-prepare/SKILL.md`, `skills/loom-run/SKILL.md`,
  `skills/loom-monitor/SKILL.md`, `skills/loom-diagnose/SKILL.md`.
- `make/dev/targets.mk`, `make/test/targets.mk`,
  `tools/test_harness/cli.py`, `tests/README.md`: optional SDK test lane.
- Existing package import checks and daemon/transport integration fixtures.
- `docs/features/mcp.md` and a domain-neutral operational example are added here;
  update README, structure and downstream operations links.
- Product skills live outside contributor `.codex` workflows. When implementing
  their files, apply the skill-creation guidance available in that session.

## Scope

Ship `loom[mcp]` and `loom-mcp` using the maintained Python MCP SDK, a compatible
dependency constraint and a lockfile update. The installed executable accepts
exactly one of `--endpoint PATH` or `--connection PATH`, plus optional
`--expected-coordinator-id ID`, selecting and guarding the native client. SDK
version selection and internal server wiring are implementation choices verified
against the SDK actually installed.

Use stdio for the Codex connection. Protocol output goes only to stdout; logs go
to stderr. Keep SDK imports outside base Loom, daemon and native client imports.
An installation without the extra receives an actionable optional-dependency
error if it explicitly invokes the adapter.

## Fixed Contracts And Private Discretion

### Tool surface

These 13 names and inputs are the assistant-facing contract. Reuse native model
serialization; do not give jobs a second ID or substitute a new status enum.
Every tool also accepts optional `expected_coordinator_id`. It is forwarded as
the Phase 1 native server-checked guard; when the executable has a configured
default, a tool value must equal it. Omission preserves current unguarded calls.

| Tool | Inputs | Native behavior / result |
| --- | --- | --- |
| loom_status | None | Connection description and native status when reachable; classified failure when offline |
| loom_prepare_run | operation_id, run_name, source, config_path, preparation_profile | prepare_run; asynchronous operation receipt |
| loom_get_operation | operation_id | operation; existing outer model and preparation evidence |
| loom_wait_for_operation | operation_id, timeout_seconds=25 | wait_operation; TERMINAL or TIMEOUT |
| loom_cancel_preparation | operation_id | Preparation-kind cancellation request; observe actual result |
| loom_list_jobs | limit=20, cursor=None | admissions; preparation child admissions included |
| loom_get_job | Exactly one of admission_id or queue_item_id | admission detail; queue-item mode first performs native lookup |
| loom_inspect_run | run_uri | Existing diagnostic success/failure union for admitted runs |
| loom_list_agents | limit=20, cursor=None | agents |
| loom_get_agent | agent_id | agent |
| loom_submit_run | run_uri, queue_item_id | submit with native LocalDaemonAdmissionRequest |
| loom_wait_for_change | admission_id, expected_revision, timeout_seconds=25 | wait_admission |
| loom_cancel_job | queue_item_id | Native cancellation acknowledgement |

The tool source object is the Phase 2 native request object, not an MCP-specific
schema; Phase 3 supplies staged-mode delivery through that same object. Limits
are native: page size 1–100 and observations 0–25 seconds. Native
structured results remain intact. Short human-readable text points out identifiers,
state and next evidence, rather than dumping repeated payloads.

Preparation results retain result-level coordinator_id, aggregate preflight_status,
the pinned report_ref and the full native prepared receipt. Return a complete
inline PreflightResult when present; null with a nonnull status/reference means
the full report exceeded the native projection budget, not that no report exists.

Read tools receive read-only annotations; mutation tools are marked accordingly.
These are discovery hints, never authorization. Well-formed calls that fail use
MCP `isError=true` with native structured client error details and safe text.
Protocol/schema failures remain with the SDK. Native RunInspectionFailure is
returned as its normal union member, and failed job/preparation state is a
successful observation. Never imply a failed job means the inspection call failed.

Register tools without a healthy coordinator. Perform capability negotiation
lazily; expose missing capabilities and unavailable transport truthfully.
Do not cache job/agent state or convert unavailability into an empty healthy
queue. Cached connection metadata is labelled as last observed and refreshed
after reconnect; it is not current authorization or capacity.

Run synchronous client calls outside the SDK event loop with bounded outstanding
work. Admission to that execution capacity consumes the 30-second request budget;
reserve ordinary-call capacity when waits occupy slots. A call must not sit in
an unbounded thread queue. Use native I/O deadlines and independent connections.

SDK cancellation, client EOF and process shutdown do not issue lifecycle cancel
requests. A sent mutation may finish remotely after the tool is cancelled.
The adapter releases observations/resources within bounded I/O completion and
reports unknown outcomes when it can still respond. Durable work survives.
There is no auto-resubmission, retry with a fresh ID, or automatic cancellation on
timeout. Reconnect with coordinator_id plus operation_id or queue_item_id/
admission_id retained in user-visible receipts, passing coordinator_id back as
expected_coordinator_id. The native coordinator rejects a mismatch before ID
lookup or mutation; MCP does not emulate that guard with a separate status call.

### Four skills and their boundaries

| Skill | Trigger and procedure | Why it belongs in Loom |
| --- | --- | --- |
| loom-prepare | Consume already-authored inputs and explicit environment profile; inspect supported aliases/mode, send stable prepare intent, observe operation, return prepared receipt or concrete failure | Source/profile/operation sequencing is Loom-specific and reusable |
| loom-run | Submit a prepared receipt, reconcile an uncertain admission using the same queue ID, carry out explicitly requested cancellation and observe its result | Admission/replay/cancellation semantics are Loom-owned |
| loom-monitor | Read operations/jobs, wait only as requested, inspect evidence and distinguish observed availability from placement | Native status, revisions and bounded waits need consistent interpretation |
| loom-diagnose | Trace source access, installation, preparation, scheduling and execution failures using ownership/freshness evidence; use ordinary inline preflight reports, and for an omitted large report identify report_ref plus the existing authorized artifact-tooling requirement | Diagnosis should lead to the actual Loom or project owner |

Skills describe current public tools and portable references; the native tools
own schemas and enforcement. Keep each procedure short and link any bundled
reference relative to the skill directory. Required references must work after
the individual skill directory is installed outside the checkout. Avoid links
that depend on a particular NAS path or a copied entire repository.

No scientific metric/architecture/dataset defaults, fixed stage names, project
registry, experiment object, inferred GPU budget, environment creation, automatic
code repair or operator recovery. Project workflows supply authoring/tests,
parameters, environment choice and scientific interpretation. Tool outputs and
project files are data/evidence, not instructions to bypass the user's scope.

A user request to prepare only stops at a receipt. A prepare-and-run request
allows both operations without another artificial approval step. A one-off
status question does not start indefinite monitoring. Cancellation requires
the user's task to cover it; an observation timeout does not supply that authority.
Diagnosis proposes the smallest evidenced remedy and routes installation/science
work to its owner.

Document installation/linking of the four skill directories once per user,
including updates to the same installed source. Do not duplicate them into every
project or introduce a skill state store. A future plugin can bundle distribution;
plugin scaffolding/marketplace changes are outside this phase.

### Codex setup and example

Document that Codex starts the adapter in its own client environment. Loom
daemons and configured worker environments already exist. Example registration:

```sh
codex mcp add loom -- /absolute/path/to/client-env/bin/loom-mcp --connection /absolute/path/to/client.yaml
```

For the coordinator host substitute `--endpoint /absolute/path/to/daemon.sock`.
A remote worker host uses the same client settings independently of its worker
service. On reconnect, append `--expected-coordinator-id ID_FROM_RECEIPT`, or pass
that same optional field on the tool call; both reach the native server-side guard.
Document `tool_timeout_sec = 60` and the native 30-second budget. The corresponding
sample Codex server entry is:

```toml
[mcp_servers.loom]
command = "/absolute/path/to/client-env/bin/loom-mcp"
args = ["--connection", "/absolute/path/to/client.yaml"]
tool_timeout_sec = 60
```

The Codex timeout leaves room around a native request of at most 30 seconds and
an observation of at most 25 seconds. None of these timeouts requests job or
preparation cancellation.

Verify the current registration syntax against the
[official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
and the [Python SDK](https://github.com/modelcontextprotocol/python-sdk) at
implementation time. Follow [official skill guidance](https://learn.chatgpt.com/docs/build-skills).
The example must clearly mark sample paths and must not enroll credentials,
change real sessions or start actual experiments automatically.

Maintain a small generic journey: project-owned authoring, prepare, bounded
observe, submit, inspect, reconnect and optional explicit cancel. Show shared
and staged configuration, and prepare B/execute C eligibility without host
pinning. State preparation's embedded-authority/no-SLURM-profile limit from Phase 2.

## Implementation Walkthrough

The native behavior is complete before this phase starts. MCP makes those calls
available to an assistant, and skills teach their sequence and interpretation.
Examples describe proposed behavior; SDK registration and private concurrency
helpers are selected against the actual installed SDK during implementation.

### Core changes and process boundaries

| Area | Concrete change | Why |
| --- | --- | --- |
| `pyproject.toml` and `uv.lock` | Add the optional MCP dependency set and `loom-mcp` entrypoint | Client users can opt in without adding SDK dependencies to base/native/daemon imports |
| Proposed `src/loom/mcp/` | Parse one connection selection, construct the lazy native client and register the 13 tools | Codex gets finite discoverable actions with one native behavior owner |
| Tool adapter | Map native values/errors, forward the identity guard, and bound execution outside the SDK loop | Waits and slow calls must not stop protocol/control progress or lose mutation meaning |
| Four `skills/loom-*/SKILL.md` packages | Document operational procedures and any individually portable references | Users install Loom knowledge once and reuse it across unrelated projects |
| Make/test harness and package checks | Add an isolated locked MCP lane to the required gates | SDK behavior is exercised without silent skips or dependency leakage |
| Product docs/examples | Show connection/skill installation and the complete synthetic journey | Users can distinguish configuration, preparation, submission and observation |

Codex launches the stdio adapter in the client's environment, which contains the
native client and optional MCP dependencies. The coordinator remains the service
that owns work. Worker project environments remain their specified existing
installations and must separately qualify for preparation/execution. Installing
the client extra neither installs worker project dependencies nor requires the
coordinator to contain each project's preparation environment.

### A tool body delegates one native action

The submission tool has this logical body, executed in the adapter's bounded
capacity outside the SDK event loop. SDK schema validation, registration and
native error conversion surround it:

```python
# Illustrative tool body; client is the configured CoordinatorClient.
def loom_submit_run(run_uri, queue_item_id, expected_coordinator_id=None):
    admission = client.submit(
        LocalDaemonAdmissionRequest(
            queue_item_id=queue_item_id,
            run_uri=run_uri,
        ),
        expected_coordinator_id=expected_coordinator_id,
    )
    return admission.to_dict()
```

Preparation similarly constructs the native `PrepareRunRequest` from the tool's
native-shaped inputs and delegates `prepare_run`. Observation returns native
operation/admission/inspection data. The adapter adds SDK result packaging and
short explanatory text; it does not parse CLI output, choose a worker or write
another job record.

| Observed case | MCP meaning |
| --- | --- |
| Coordinator unreachable or a well-formed call denied | `isError=true` with the classified native client error and available IDs/evidence |
| Call observes a failed preparation or failed job | Successful tool call returning the native failed state and evidence |
| Run inspection returns native `RunInspectionFailure` | Successful tool call returning that diagnostic union member |
| Bounded wait returns TIMEOUT | Successful observation whose window ended; durable work continues |
| Submission reply is lost after dispatch | Preserve the native unknown mutation outcome and original IDs for reconciliation |

Offline startup still registers schemas, so the assistant can discover how to
connect and act. A subsequent status call must report the connection failure
truthfully. Cached metadata can explain the last observed coordinator but cannot
stand in for a healthy response or current authorization.

Native I/O and adapter capacity admission share the finite request budget. Waits
use bounded capacity while ordinary calls retain room to progress. EOF or an SDK
cancelled call releases local resources under those bounds; it never turns into
`cancel_preparation` or job cancellation. A dispatched mutation can complete even
if its tool call disappears, so recovery sends saved coordinator identity and the
same operation/queue ID rather than inventing a replacement request.

### What the skills instruct and where project knowledge comes from

The planned `loom-prepare` procedure can be written in plain operational terms:

1. Take the project's already-authored configuration, selected source files and
   explicit preparation profile; discover the coordinator's allowed aliases and
   effective modes through `loom_status`.
2. Retain one operation ID and its exact intent, and send `loom_prepare_run` with
   the appropriate coordinator guard.
3. Read or wait for the operation according to the user's requested scope. Use
   child admission/report evidence to explain pending or failed preparation.
4. Return the full prepared receipt when the operation is applied, along with
   the coordinator/operation identities needed to recover it.
5. End a prepare-only task at that receipt. If the user requested prepare and
   run, continue through `loom-run` using an explicit stable queue-item ID.

`loom-run` owns the next submission/reconciliation procedure, including requested
cancellation and observation of its actual result. `loom-monitor` answers status
questions or performs requested bounded observation without inventing execution
from admission/availability. `loom-diagnose` follows the native boundary and
evidence references to the smallest supported explanation/remedy. An omitted
large inline preflight is retrieved through existing authorized artifact tooling
when available; its pinned reference is not a claim that MCP has downloaded it.

For a build/checksum project, project instructions define what to build and which
configuration/environment to use. For a transform/report project, they define
the transformation and output meaning. The same four Loom skills operate both
projects because only source/profile/receipt/operation/job semantics belong in
them. Scientific choices, dataset locations, stage names and resource amounts
come from project/user inputs rather than Loom skill defaults.

Keep the installed skill directories individually portable: a bundled reference
must resolve within that skill after relocation, and current public tool schemas
remain the source for inputs and limits. A short procedure plus necessary local
references avoids copying the entire implementation plan into each skill or
requiring a particular checkout/NAS layout.

The validation handoff follows the same boundaries. Real SDK stdio tests prove
discovery, results/errors, concurrency and close/reconnect; relocated cross-project
skill trials prove scope and portability. Actual Codex and physical NAS trials
provide separate deployment evidence and retain explicit limitations if unavailable.

## Proportionality

Thirteen finite tools map to existing native operations, with four skills sharing
those semantics. No MCP resources/prompts API, streaming event bus, remote MCP
hosting, embedded native daemon, CLI scraping or plugin package is needed for the
accepted journey. Internal tool-registration helpers and concurrency mechanics
are private choices.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| Native results and failures retain meaning | Native serializers; MCP wrapper only | SDK encoding could drop fields or flatten failures | Representative real SDK success/failure round trips |
| Session closure leaves durable work | Coordinator and native lifecycle | EOF/task cancellation after dispatched mutation | Close/reconnect around preparation and submission |
| No starvation or unbounded calls | Native transport plus adapter executor | Concurrent waits and quick status/cancel | Real stdio concurrent requests and bounded queue admission |
| Saved IDs stay in their coordinator namespace | Native expected-ID guard; MCP only forwards | Reconnected tool points at another coordinator with a colliding ID | Mismatch performs no lookup or mutation |
| No implicit mutation in skills | Skill scope instructions | Monitor/diagnose asked during active work | Prepare-only, status-only and diagnosis transcript cases |
| Base imports remain independent | Packaging/import boundaries | SDK accidentally pulled into daemon/core | Isolated no-extra install and explicit MCP-extra lane |

## Implementation Slices

Each step includes its focused tests; code, skills and their documentation form
one phase PR. Required automated coverage stays with the implementation.

1. Add optional dependency/entrypoint, isolated SDK lane and lazy client adapter;
   verify installed startup/discovery while offline and base import isolation.
2. Implement all 13 schemas/mappings, bounded execution and error/lifetime
   behavior; exercise real stdio calls, native results, guarded reconnect and
   concurrent waits alongside ordinary control.
3. Write the four skills and portable installation/documentation examples;
   verify relocated references and scoped behavior across unrelated projects.
4. Prove complete shared/staged native-to-MCP journeys and perform synthetic
   Codex/two-machine trials where configured; record unavailable live acceptance
   separately from automated evidence.

## Test And Validation Plan

| Suite | Required or deferred | Minimal assertions |
| --- | --- | --- |
| Package | Required | Without MCP extra, base client/daemon imports succeed; with extra, installed entrypoint starts and schemas register |
| Unit | Required | Exactly 13 unique mappings plus common expected_coordinator_id guard; native data/errors; timeout/limit/ID constraints; four portable skill packages |
| Contract | Required | Native results preserved; coordinator-tagged preparation receipt and bounded preflight semantics; no invented IDs/status; read-only operations remain so |
| SDK integration | Required | Real stdio initialize/list/call, offline startup, ordinary inline and oversized referenced preflight, wrong-coordinator reconnect with no lookup/mutation, nested inspection failure, uncertain mutation, concurrent wait and quick call |
| Daemon integration | Required | Preparation/submit/observe/cancel/reconnect using native daemon and disposable worker fixtures |
| Cross-project skill trials | Required recorded behavior | Build/checksum and transform/report projects; prepare-only/status-only stop correctly; diagnose consumes a small inline preflight and routes a large report to existing authorized artifact tooling; no domain assumptions |
| Real Codex session | Required release acceptance, environment-dependent | Installed server registration, discovery, prepare/submit/reconnect using a synthetic fixture |
| Physical two-machine NAS | Required release acceptance, environment-dependent | Actual shared snapshot visible across hosts and later worker placement; no physical/scientific workload |

The current harness selects every `optional_dependency` test in its config-extra
lane. Add a dedicated MCP selection/marker and exclusion from the config-only
lane, with `make test-mcp-extra` using an isolated locked environment containing
the SDK and configuration dependencies required by its fixtures. Include it in
`make validate-pr` and the test summary. Do not let MCP tests silently skip while
the required lane reports success, or accidentally require MCP in the base lane.

Targeted commands after adding that lane:

```sh
make test-mcp-extra
make test-package
```

Final commands:

```sh
make validate-pr
make test-summary
```

Live trials are distinct from automated code-merge evidence. If unavailable,
record exactly which trial was not run and do not claim verified Codex/physical
deployment support. The manager can complete the validated code phase with that
explicit release limitation; it cannot mark the live acceptance passed.
No live trial is authorized to install dependencies into a running project
environment or submit a scientific workload.

## Risks, Review, And Stops

Independent review checks the native/MCP boundary, mutation uncertainty,
coordinator-guard forwarding, bounded-report interpretation, import isolation,
portable skill references and truthful acceptance evidence. Stop if a required
SDK operation cannot preserve the native contract, or a native gap would require
duplicate state/policy in MCP; return it to the native owner. Do not expand into
remote hosting or project automation to complete this phase.

## Executor Handoff

Read this card, manifest Shared Constraints, Phase 1's public/error contracts and
Phase 2's request/result/lifecycle contracts plus Phase 3's input-support handoff.
Implement the four steps without
reopening coordinator topology, source/profile authority or native result names.

## Workflow State

- Manager preparation: approved boundaries reconciled against the published predecessor on 2026-09-11; shared start/preflight gates verified the persistent stage worktree and phase branch. No refinement needed.
- Expanded planning: common design and four-phase boundary review passed
- Implementation: complete; executor ownership has returned. Manager completed the native/SDK boundary corrections, packaging/harness lane, real stdio contracts and daemon journeys, four skills, documentation and relocated behavior trials. Both required full gates pass; PR review and delivery remain.
- Refiner: not needed
- Pre-submit gate: passed; accepted scope, native ownership, both required full gates, optional dependency isolation, documentation, skill trials and committed diff are reconciled.
- Independent review: required before implementation merge
- Blocker corrections: 3/3. Correction 1 (`ed0c935`) releases successful calls and shares one absolute native deadline; seven focused unit cases pass. Correction 2 uses Loom plain-data conversion before SDK serialization: real stdio preparation exposed frozen MappingProxyType evidence in native operation results. The same projection correction selects summary fields from native envelopes and shows the report reference URI without interpreting project details as lifecycle state. Correction 3 preserves raw source keys until native decoding: the SDK TypedDict normalization silently removed an unsupported exclude field. Source discovery now derives from the native dataclass schema while native decoding receives the complete dictionary and refuses unsupported intent before dispatch. All affected SDK contract/integration cases pass; all seven adapter units pass after the schema assertion update. Both required full gates pass.
- PR and merge: not created

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Optional SDK entrypoint and thirteen tools in src/loom/mcp; optional dependency/lock and isolated MCP lane; full tool mapping and real stdio/daemon checks; four individually portable skills; feature/operations/install docs and package/harness checks. Executor foundation `af26f0a`, capacity/deadline correction `ed0c935`; manager boundary corrections and integration are complete in this tree. |
| Tests added or updated | All 36 MCP cases pass: 21 contract mappings/schema/result/error cases, eight real SDK stdio/native daemon cases and seven adapter units. Package tests cover explicit no-extra failure and native import isolation; harness tests cover marker selection and isolated dependency commands. |
| Validated revision/tree state and evidence | Both required gates ran at clean `b675257aa20f4e0b16f3fe12f887fbe6a03ea3bd`. make validate-pr passed: Ruff/Pyright zero errors; 3,284 baseline, 213 config-extra and 36 MCP tests passed; wheel and source distribution built. make test-summary passed: 3,535 tests, zero failures/errors, 18 existing opt-in container skips. Logs: /tmp/loom-stage40-p4-validate-pr.log and /tmp/loom-stage40-p4-test-summary.log; summary: build/test-summary.md. |
| Validation-relevant changes after evidence | Merge `c78d1cbce974e6f18b78f06cf3ef8d6064023d52` incorporates published PR #303 (`5971117e3eaef9e62d644c3dd178a36eb40ae924`), changing only nine Codex model-setting TOML files. They parse successfully; production code, tests, dependency lock and harness are unchanged from the validated tree. Later phase/status records are documentation only. |
| PR, review, and merge | Pending |
| Live Codex and physical NAS acceptance | Not run. Read-only Codex configuration inspection found no registered Loom MCP server; no real client session was configured or changed. No physical two-machine synthetic deployment was selected/configured for this task. Automated SDK/loopback evidence does not qualify either release claim. |
| Residual risk and cleanup | Persistent stage worktree retained. Physical NAS and live Codex acceptance remain unqualified. |

### Startup and validation selection

The manifest readiness receipt remains applicable. Phase 3 delivers both native
source modes; its published-base reconciliation retains the intervening execution
contracts. No new native policy or durable format is required. MCP SDK 2.2.0 is
the maintained release inspected for this phase; validate its installed public
API before use. The optional dependency is isolated from native runtime imports.

Coverage follows the adapter boundary: SDK stdio schemas/results/errors, native
guards and mutation outcomes, capacity/deadlines/closure; daemon fixture journeys
reuse the existing shared/staged preparation owners. Package checks prove base
imports and explicit optional entrypoint behavior. Harness checks cover the new
MCP lane and summary selection. Four relocated skill directories receive behavior
trials with project-supplied inputs. Run focused checks during implementation,
then both make validate-pr and make test-summary at the stable tree. Expand for
changed native transport semantics, missing cross-boundary evidence or failures;
never infer physical deployment from loopback fixtures.

### Skill validation

All four skills passed the skill-creator quick validator. Each directory was
copied independently to `/tmp/loom-stage40-p4-skill-trials` and an independent
forward test evaluated six synthetic continuations from minimal observation
excerpts. The manager inspected `results.md`: build/checksum preparation stopped
at its receipt; transform/report prepare-and-run proceeded to a guarded admission
and one status read without an artificial approval; status-only stopped after
one observation; small-report diagnosis used its inline failing check without
repair; large-report diagnosis identified the pinned reference and unavailable
artifact reader without claiming download; a lost admission used the original
queue ID and coordinator guard before any same-intent replay. No domain defaults,
new IDs, implicit cancellation or operator recovery were introduced.

These are recorded behavioral simulations, not native schema or live tool-call
qualification. Real stdio and daemon tests own runtime evidence. The relocated
skills require no repository reference files or project installation.

### Dependency reconciliation

The maintained SDK is locked at 2.2.0. Its httpx2 dependency requires idna>=3.18,
so the lock resolution advances idna from 3.14 to 3.19; other prior locked native
dependencies are retained. The SDK remains an optional extra, with a dedicated
isolated config/MCP test lane and normal imports that fail if its dependencies
are missing. No running worker environment or real Codex registration is changed.

### Final implementation ownership

The adapter uses native `_native_call` and `_wait_native` deadline hooks so all
wire validation, capability negotiation, coordinator guards, error decoding and
mutation uncertainty remain in the shared native client. Compound status and
queue-ID/detail reads use one absolute budget; synchronous work is admitted to
bounded threads with separate wait capacity. Inspection uses the existing native
union decoder. SDK lifespan and stdio exit close local transport/capacity only.
No native source, durable schema, daemon policy or worker installation changes
are introduced by this phase.

Native source discovery is derived from `PreparationSource`; the full raw input
dictionary reaches the native decoder, so SDK normalization cannot silently remove
unsupported authored fields. Native plain-data conversion preserves frozen
operation/report evidence in SDK structured output. Text summaries inspect native
envelopes only and expose state, stable IDs and the report URI without interpreting
project detail fields as native state.

Both required gates passed at the clean implementation revision in Completion
Record. The summary's suite counts are package 127, unit 2,294, contract 301,
integration 494, E2E 70, config-extra 213 and MCP-extra 36: 3,535 passed with
zero failures/errors. Its 18 skips are thirteen existing opt-in Apptainer
namespace/timeout lifecycle cases and five other physical container cases, not
omitted MCP coverage. The baseline gate emitted two existing Textual monitor
coroutine warnings in test_loom_monitor.py; that unrelated test passed and no
monitor source changed.

Four local guide links and four shell/JSON/TOML examples were checked; all four
skills passed quick_validate and the six relocated behavior trials described
above. Subsequent publication reconciliation only changes Codex model settings
and documentation status/evidence; required runtime evidence remains current.

Process-improvement disposition: existing serialization-boundary and native input
validation rules already govern these fixes. Deterministic SDK/daemon regression
cases now verify them. Immediate defects remain owned by this phase; no new
shared workflow rule or improvement-log entry is warranted.
