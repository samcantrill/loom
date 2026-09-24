# Run Context: Submission Intent, Identities, And Annotations

Card ID: `PC-42-run-context`.
Status: detailed implementation design independently reviewed and approved;
implementation pending.
Planning manifest: [Stage 42](../planning.md).
Evidence revision: `220358ed26392f30bb2f36bf09d547607a57d442`.

Owned IDs: `FR-42-C01`–`C07`, `EX-42-C01`–`C03`, `VAL-42-C01`–`C05`,
`DQ-42-C01`–`C04`.

## Intent And Existing Owners

Callers can explain submitted work, label it, find it later, and add observations
without changing execution identity or teaching Loom domain concepts. Python
programs, CLI users, and assistants are equally valid callers.

| Evidence | Existing behavior and reuse implication |
| --- | --- |
| `src/loom/pipeline/runtime/options.py::RunOptions` | String tags and a sequence of notes already exist and have safe metadata serialization; do not introduce a competing tag representation without migration design |
| `src/loom/queue/preparation.py::PrepareRunRequest` | Preparation has native intent serialization/digest behavior; added context must have explicit replay treatment |
| `src/loom/coordinator.py::CoordinatorClient` and `src/loom/queue/_coordinator_client.py` | Native submission/operation/inspection paths own client semantics |
| `src/loom/pipeline/stores/local_runs.py` | Existing user metadata read/write support is evidence, not permission to bypass authority-backed mutation ownership |
| `docs/GLOSSARY.md` | `run_uri` is the public/protocol/persisted identifier; stage, queue, assignment, attempt, and artifact identities have different meanings |
| `tests/integration/queue/test_run_operations.py` | Native operation/replay behavior is an existing compatibility obligation |

This card extends context around ordinary runs. It does not add an experiment,
study, experiment-version, tag-registry, or application-configuration entity.

## Functional Requirements

| ID | Required behavior | Validation |
| --- | --- | --- |
| FR-42-C01 | Accept optional caller description, string key/value tags, and typed plain-data metadata with a submission; retain original submitted context | VAL-42-C01 |
| FR-42-C02 | Accept arbitrary valid application keys without a built-in vocabulary, inferencing rule, or registration prerequisite; keep supplied and native fields distinct | VAL-42-C01 |
| FR-42-C03 | Return existing native identities and associations; `run_uri` identifies the run, run plus stage identifies a logical operation, and native operational IDs identify submission/execution activity | VAL-42-C02 |
| FR-42-C04 | Support explicit tag additions/replacements/removals and description/metadata updates that preserve unrelated fields | VAL-42-C03 |
| FR-42-C05 | Add notes with recorded time and available author identity, retain original submission intent, and distinguish later observations from launch motivation | VAL-42-C03 |
| FR-42-C06 | Organizational annotation changes preserve scientific/execution fingerprints, artifact/reuse identity, and lifecycle truth; preserve native submission replay guarantees | VAL-42-C04 |
| FR-42-C07 | Provide concise run inspection joining context, native status/provenance, stage/operational identities, output references, and unavailable/failure evidence | VAL-42-C05 |

## Submission Context

Three kinds of information travel together but keep their owners:

| Information | Producer | Meaning |
| --- | --- | --- |
| Submitted description/tags/metadata | Caller or explicitly selected application code | What the caller said this work was for and how it should be organized |
| Native submission facts | Existing coordinator/operation owner | When the request was received, accepted identity and available authenticated submitter context |
| Recorded execution/provenance facts | Existing run, stage, and provenance owners | What was prepared/executed, with which captured inputs/code/configuration and outcomes |

The initial context remains recoverable after annotations change. Missing
descriptions and unavailable author/provenance information are explicit absence;
Loom does not infer motivation from a command or present caller text as captured
execution evidence. A caller-supplied `status`, `submitted_by`, or `commit` inside
metadata cannot overwrite its native counterpart.

The pipeline/configuration determines execution. A `model=PhysNet` tag is a
label supplied by the application; it does not select a model. The application
may derive tags from resolved configuration using its own code. Ordinary
submission values are the baseline. The detailed design uses ordinary explicit
application submission code, not a new preparation hook or plugin system.

## Identity And Lifecycle

| Identity | Caller-facing use |
| --- | --- |
| `run_uri` | Locate and inspect one pipeline execution or planned execution |
| `run_uri` plus stage identity | Locate one logical pipeline operation, such as a caller-named `fit` node |
| Native operation/admission/queue identities | Follow submitted intent through preparation/admission and reconnect after uncertain replies |
| Native stage-attempt/assignment/backend job identities | Inspect actual operational execution, retries, placement, or backend jobs |
| `ArtifactAddress` / selected output commit and `ArtifactRef` | Address a published result in its run context and distinguish selected versions |

Do not mint a new experiment ID or rename native IDs for the convenience API.
Short display labels in examples are not replacement identity formats. A run
with one training operation can normally be handled by its `run_uri`; a run
with multiple training nodes also requires the stage selector.

Submission acceptance is not completion. A receipt returned before run creation
must expose the native operation handle; the eventual operation result supplies
the `run_uri`. A job query presents jobs and their run/stage relationships rather
than counting them as new independent runs. Resume/retry continues to obey native
identity rules; this stage does not redefine them.

Run inspection reports lifecycle status separately from output availability. A
failed `summarize` stage does not erase a completed `score` artifact. Refer to
[output access](output-access.md) for exact selection and availability semantics.

## Annotation Mutations

Tag operations are key-based patches. Assigning a new key/value creates a tag
on the run without registering it globally. Setting an existing key replaces
that value; removal names a key. Unrelated tags and metadata survive.

Support an editable current description and structured metadata updates as well
as note append. Original submission context remains distinct and recoverable.
Note time is recorded by the owning service; author information distinguishes
known native identity from supplied attribution or unavailable identity. The
detailed `DQ-42-C02` disposition chooses native attribution and append-only notes.

All mutations are explicit caller requests through supported ownership and
existing access policy. Search and inspection are inert. Python/CLI/MCP cannot
silently turn a read into tagging, execution, provisioning, or deletion.

Patches must not silently lose an unrelated concurrent edit. The detailed design
below uses annotation revisions and idempotent mutation receipts, not a
client-side read/replace of the entire metadata document. No new general-purpose
audit service is implied.

## Examples

All methods, keyword arguments, and helpers below are proposed pseudocode.
`client` is an explicitly connected native client; `prepared_pipeline` is the
caller's executable request. This example does not promise current API support.

### EX-42-C01: Submit With A Reason And Derived Labels

```python
submission = client.submit(
    pipeline=prepared_pipeline,
    description=(
        "Increase temporal kernel size to test whether longer temporal "
        "context improves cross-dataset performance."
    ),
    tags={
        "project": "rppg",
        "model": "PhysNet",
        "dataset": "PURE",
        "study": "temporal-kernel-ablation",
        "purpose": "candidate",
    },
    metadata={"temporal_kernel_size": 5, "revision": 3},
)

# Follow the existing operation receipt until preparation supplies a run_uri.
# Admission and terminal execution success remain different outcomes.
```

Expected behavior: all caller context is recoverable, values retain their types,
and the eventual run remains addressable even if tags change. Changing only the
organizational labels does not change which pipeline was requested.

A second application can instead supply
`{"customer": "example-company", "document_type": "invoice", "purpose": "backfill"}`.
It receives the same behavior without an rphys dependency or Loom code change.

### EX-42-C02: Organize And Annotate After Execution

```python
current = client.get_run_context(run_uri).annotations
client.patch_run_annotations(
    run_uri=run_uri,
    mutation_id="review-labels-17",
    expected_revision=current.revision,
    set_tags={"review_status": "candidate", "comparison": "kernel-study"},
    remove_tags=["needs_review"],
)
client.append_run_note(
    run_uri=run_uri,
    mutation_id="review-note-17",
    text=(
        "Training completed. Target-dataset evaluation is still pending; "
        "do not treat this as cross-dataset evidence yet."
    ),
)
```

Expected behavior: unrelated labels remain, a later note carries its attribution
and timestamp, and inspection can still show why the work was originally
submitted. Existing outputs and fingerprints remain unchanged.

### EX-42-C03: Inspect Useful Outputs Of A Failed Run

```python
run = client.get_run_context(run_uri)
```

Expected overview: native run status `FAILED`, successful `fit`, `predict`, and
`score` nodes, failed `summarize`, original reason, current tags/description,
available provenance, operational identity links, and the committed metric output
reference. Large logs/configuration/payloads require explicit follow-up access.

## Proposed Ownership And Complexity

Extend the existing native request/client, operation receipt, authority-backed
metadata, and inspection paths. Keep context values inert and domain-neutral;
application configuration resolution stays with the application. Existing
`RunOptions.tags` and `notes` need deliberate treatment at the new boundary.

Durable original intent and later attributed notes are justified by the accepted
"why launched / what learned later" consumer. Their storage representation and
mutation protocol have not been designed here. Do not introduce a new execution
lifecycle state, generic registry, or experiment service to carry them.

## Design Decision Disposition

| ID | Decision required before implementation readiness | Direction and constraint |
| --- | --- | --- |
| DQ-42-C01 | Native integration and derivation | Resolved proposal: optional `SubmissionContext` on `PrepareRunRequest`, inherited by `RunRequest`; caller derivation and existing resolved runtime tags suffice; no new callback |
| DQ-42-C02 | Durable context/notes and migration | Resolved proposal: immutable coordinator submission receipts with run links; authority-owned run annotations and append-only notes; preserve unknown legacy attribution |
| DQ-42-C03 | Patches, replay, limits, object scope | Resolved proposal: run-only annotations, compare-and-swap revision, caller mutation ID and durable receipt, top-level metadata patch keys; bounded payloads as below |
| DQ-42-C04 | Digest versus execution identity | Resolved proposal: context participates in submission intent digest when supplied, never in stage fingerprints; later annotation requests have separate IDs/digests |

## Detailed Implementation Contract

This section resolves the decisions above for the proposed implementation plan.
Public names and wire records here are proposed contracts; the earlier intent
examples illustrate behavior and are not a second API definition. Private helper
and table names may change without changing the observable/durable semantics.

### Public Surface And Data Flow

Extend `PrepareRunRequest` in `src/loom/queue/preparation.py` with an optional
`context` field. `RunRequest` already contains that request; do not create another
submit pathway. Extend `CoordinatorClient` with `get_run_context`,
`patch_run_annotations`, `append_run_note`, and `list_run_notes`. The existing
inspection response can link to context rather than embedding unbounded notes.
Export inert request/result values from `loom.runs`; do not add heavy root imports.

Illustrative signatures for the new values, omitting validation/serialization:

```python
@dataclass(frozen=True)
class SubmissionContext:
    description: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

@dataclass(frozen=True)
class RunAnnotations:
    run_uri: str
    revision: int
    description: str | None
    tags: Mapping[str, str]
    metadata: Mapping[str, PlainData]
```

Use the existing plain-data freeze/thaw helpers. Object immutability is deep;
`to_dict()` produces a detached mapping. Values are finite JSON data, not live
Python objects. No field may impersonate native status, submitter, or code facts.

```python
request = RunRequest(
    preparation=PrepareRunRequest(
        operation_id="kernel-five",
        run_name="kernel-five",
        source=source,
        config_path="pipeline.yaml",
        preparation_profile="research",
        context=SubmissionContext(
            description="Test longer temporal context.",
            tags={"model": "PhysNet", "study": "kernel-study"},
            metadata={"temporal_kernel_size": 5},
        ),
    ),
    queue_item_id="kernel-five",
)
operation = client.start_run(request)
```

The request follows `_coordinator_control` validation, existing operation journal,
preparation, and run binding. Context is an annotation input, not a worker stage
argument. The application can derive it before submission. Existing authored
`RunOptions.tags` can still be resolved through normal configuration composition.
No server callback is added to inspect arbitrary application configuration.

### Original Intent, Reconciled Runs, And Initial Labels

The coordinator operation is the authoritative original submission record. Retain
context, native receipt time, authenticated principal ID, operation ID, and the
eventual `run_uri` association even if preparation fails before a run exists.
Do not overwrite `request_json` when current annotations change. Add an explicit
accepted timestamp if the operation table lacks one; use the daemon's accepted
UTC clock and preserve it on replay. Older missing timestamps remain null.

Several reconciled submissions may bind to the same run. They remain distinct
submission records with distinct original descriptions. A run context view links
all those submissions and identifies which submission initialized its annotations.
A later submission does not silently relabel an already existing run. This is why
"what did we submit yesterday?" also needs a submission query, not just one row
per run. `submission.description` on a run means its initializing submission;
searching every launch reason uses `search_submissions`.

On first binding, initialize run annotations once from the effective resolved
runtime tags plus explicit context tags, with explicit context winning per key.
If the same key is supplied through both explicit `run_options.tags` and explicit
context with different values, reject the conflicting request before effects;
identical values coalesce. Existing authored runtime tags are the lower-precedence
baseline. Preserve the originally supplied context separately from this effective
initial tag set. Context metadata/description initialize only their own fields.

Run initialization must be replayable across the coordinator/authority boundary:
the existing binding operation identity supplies an idempotency key, the authority
checks an expected absent annotation record, and repeating the same initializer
returns the original result. Persist the coordinator's binding receipt only after
the authority acknowledges initialization. An interruption resumes that step;
do not start target work while required context initialization is unresolved.
No new execution lifecycle status is required. Rebinding an existing run returns
the existing initializer and does not erase later annotations.

### Durable Ownership And Compatibility

Add authority-owned records for run annotations, note entries, and annotation
mutation receipts. Use explicit schema migrations in both embedded SQLite and
`src/loom/authority/_repository.py`; expose methods through the existing authority
protocol, service adapters, and coordinator-scoped client. Organizational writes
must not require a live worker/controller lease, but they still require authorized
access to an existing run. Do not route them through local `run.json` replacement.

Logical durable fields (table layout is private):

| Record | Identity and retained data |
| --- | --- |
| Submission context | Existing coordinator operation ID + principal, accepted time, immutable submitted context, binding receipt/run URI |
| Run annotations | `run_uri`, annotation revision, description/tags/metadata, initializer operation/coordinator reference |
| Note | `run_uri`, stable note ID, text, native author/time, optional unknown legacy attribution |
| Mutation receipt | Principal + caller mutation ID, request digest, target run, committed result/revision; same owner transaction as effect |

Empty/omitted `context` preserves old request serialization byte-for-byte for
native digest purposes: do not inject a new default key into historical replay.
Nonempty context participates in the operation digest; replay with changed context
and the same operation ID conflicts. Negotiate a new `run-context-v1` capability
before sending the new field, rather than having an older server drop it.

Migrate existing effective tags/notes as legacy evidence without fabricating an
original submission description/time/author. Legacy notes appear in the note view
with `source=legacy_runtime` and unknown attribution. Initialize the writable
annotation revision through an explicit migration/first-write transaction, never
as a side effect of a read. Preexisting caller metadata remains accessible in its
legacy view; do not reinterpret its arbitrary keys as native fields.

Stage fingerprints continue to use stage config, declared inputs, and existing
semantic production inputs. Do not put context into `ArtifactRef.metadata`,
`stage_config`, or `fingerprint_fields` merely for discoverability. Initial authored
configuration fingerprints still describe the configuration actually captured;
this plan does not redefine historical configuration hashing. Later annotations
do not rewrite any captured fingerprint.

### Safe Patches And Notes

`patch_run_annotations` accepts a caller `mutation_id`, `run_uri`, required
`expected_revision`, key-wise tag/metadata sets and removals, and an optional
description change. Missing description means leave unchanged; explicit null
clears it. Set-to-null metadata is distinct from removing a key. Nested metadata
objects may be replaced as a top-level value; arbitrary deep patch languages are
unnecessary. A key in both set and remove is invalid.

```python
current = client.get_run_context(run_uri).annotations
result = client.patch_run_annotations(
    run_uri,
    mutation_id="review-label-17",
    expected_revision=current.revision,
    set_tags={"review_status": "ready"},
    remove_tags=("needs_review",),
)
```

One owner transaction checks an existing mutation receipt first, checks the
expected annotation revision, applies only requested changes, increments that
revision, and stores the mutation result. Lifecycle revision is a separate value.

```python
def commit_annotation_patch(store, principal, mutation_id, request_digest,
                            run_uri, expected_revision, patch):
    with store.transaction():
        replay = store.find_mutation(principal, mutation_id)
        if replay is not None:
            return require_same_digest(replay, request_digest)
        current = store.read_annotations(run_uri)
        require_revision(current.revision, expected_revision)
        updated = apply_patch(current, patch)  # preserve unrelated keys
        store.write_annotations(updated)
        store.record_mutation(principal, mutation_id, request_digest, updated)
        return updated
```

This code illustrates the transaction, not private method requirements. A stale
revision returns `conflict` with the current revision. The caller may re-read and
deliberately rebase the patch using a new mutation ID. An uncertain reply is
replayed with the same ID/request; do not automatically rebase it.

Notes are append-only in this stage. `append_run_note(run_uri, mutation_id, text)`
uses the same receipt discipline but need not require a stale full-run revision:
independent note appends can both succeed. The native owner supplies author/time;
the caller cannot assign authenticated authorship. Corrections are new notes.
List notes in native time plus note-ID order with bounded continuation. Editing
or deleting notes is deferred, not a hidden interpretation of a description edit.

### Transport And Limits

Use existing native control request/error envelopes and expected-coordinator
guards. Advertise `run-context-v1`; add mutations to `MUTATION_OPERATIONS` so
uncertain replies retain commitment evidence. Existing client principals can
request writes; read-only query principals get read methods only. Extend both
Unix and authenticated HTTPS dispatch and their capability lists deliberately.

Keep requests below the current 64 KiB HTTPS application-body limit. Proposed
defaults: description/note text at most 16 KiB UTF-8, annotation/context serialized
payload at most 48 KiB, at most 128 tag keys, key at most 128 UTF-8 bytes and tag
value at most 1 KiB. The complete encoded request must also fit the transport
budget. Advertise limits; do not silently truncate stored values. These limits
are public proposed defaults, distinct from private storage choices.

CLI routes use the existing `loom runs` family (`context`, `annotate`, `notes`)
with JSON machine output. MCP adds corresponding context/patch/note tools using
the native client. Neither adapter implements a second mutation transaction.

## Validation Obligations

These are acceptance obligations for the future implementation, not evidence
that new behavior already runs. Select concrete tests during phase planning.

| ID | Reachable producer and consequence | Minimal discriminating check |
| --- | --- | --- |
| VAL-42-C01 | Two applications submit different keys; numeric metadata or native facts could be conflated with labels | Round-trip both vocabularies through native submission, keep number `3` distinct from string `"3"`, preserve original description, and reject native-field overwrites |
| VAL-42-C02 | An asynchronous preparation or retry has operational IDs before/alongside a run | Receipt/reconnect resolves to correct `run_uri` and stage/attempt associations without claiming acceptance is completion |
| VAL-42-C03 | Two callers patch unrelated labels or append observations; a whole-document replacement could lose information | Preserve unrelated updates, expose specified conflicts, and retain original intent and attributed later notes |
| VAL-42-C04 | A caller annotates completed work or replays an uncertain submission | Annotation leaves execution/artifact identity intact; identical request replay remains native and changed intent follows the existing conflict contract |
| VAL-42-C05 | A late stage fails after earlier output commits | Overview shows both failure and useful committed outputs, with no payload download as a side effect |

Expansion triggers: changes to native request digests, authority schemas, runtime
metadata serialization, or inspection unions require their affected contract and
integration suites. No GPU, dataset, or physical fleet is needed to validate the
generic context behavior.
