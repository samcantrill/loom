# loom Run Catalog, Comparison, and Export Specification

## Purpose

The run catalog is a lightweight index over many local `loom` run directories.

It helps users inspect, search, compare, export, and import runs without turning
the core runtime into a database-backed experiment tracking service.

The catalog is derived from run-store metadata. It is not the source of truth.

## Current Support

Loom indexes, lists, compares, exports, inspects, and imports local run
collections from authoritative run-store facts. The catalog sidecar is derived
and rebuildable; it is not a tracking service or deletion authority.

## Quick Start

Run the local catalog and portable-bundle walkthrough:

```sh
uv run python examples/operations/run-catalog-and-bundles/run_catalog_workflow.py
```

## Deferred

Remote tracking services, dashboards, distributed indexes, and catalog-owned
deletion remain outside this feature.

## Scope

This component owns:

```text
discovering local run directories
building a rebuildable local index
listing runs by metadata
filtering runs by status, tag, commit, config hash, and artifact identity
summarizing run records for CLI output
comparing two runs from persisted metadata
exporting a run into a portable bundle
inspecting an exported bundle
importing a bundle into a local run collection
discovering run URIs for candidate-level cleanup orchestration
```

This component does not own:

```text
canonical run state
artifact serialization formats
stage execution
remote tracking services
dashboards
authorization
distributed indexes
deletion authority
cleanup policy
```

The run store remains authoritative for an individual run.

## Design Goals

The design should:

```text
work with plain filesystem run directories
be rebuildable from existing run metadata
avoid a required database dependency for v0
avoid loading large artifact payloads for listing or comparison
support both human CLI output and machine-readable output
preserve enough metadata for archive and review workflows
```

## Local Run Collection

A run collection is a directory containing run directories.

Example:

```text
runs/
  20260503T021409Z-a13f7c/
  20260503T031501Z-c82de1/
  20260504T004233Z-91caa0/
```

The catalog should be able to scan this layout and identify valid `loom` runs
based on run-store marker files or metadata files.

Invalid or partial directories should be reported as warnings, not fatal errors,
unless strict mode is requested.

Stage 21 `loom gc COLLECTION` may use catalog/listing output to discover run
URIs, but the collection path and catalog rows are never deletion authority.
Cleanup still comes from per-run authority cleanup candidates, managed roots
derived per run, explicit delete intent, and cleanup execution result facts.

## Catalog Index

The catalog index is a local SQLite sidecar that can be rebuilt.

Current location:

```text
runs/.loom_catalog/catalog.sqlite
```

The index should contain summaries only:

```text
run_uri
display path
status
created_at
started_at
finished_at
config fingerprint
pipeline fingerprint
git commit when available
tags
notes summary
stage status counts
logical artifact identities
```

The index should not copy large state files or artifact manifests wholesale.

## Rebuildability

The catalog must be rebuildable from run directories.

Implemented command:

```bash
loom runs index runs/
```

Behavior:

```text
scan known run directories
read authoritative run-store metadata
rebuild the derived SQLite sidecar
report unreadable or invalid runs as warnings
```

If the sidecar is missing, listing commands refresh from authoritative run
directories and recreate enough derived state for the current read.

## Run Summary Model

Recommended summary shape:

```python
@dataclass(frozen=True)
class RunSummary:
    run_uri: str
    path: str | None
    status: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    config_fingerprint: str | None
    pipeline_fingerprint: str | None
    git_commit: str | None
    tags: Mapping[str, str]
    stage_counts: Mapping[str, int]
    artifacts: tuple[ArtifactSummary, ...]
```

Summaries should contain only JSON-serializable values.

## Listing Runs

Implemented commands:

```bash
loom runs list runs/
loom runs list runs/ --status FAILED
loom runs list runs/ --tag project=demo
loom runs list runs/ --commit abc123
loom runs list runs/ --artifact build.out=build/out
loom runs list runs/ --format json
```

Useful filters:

```text
run status
tag
config fingerprint
pipeline fingerprint
git commit
stage status
logical artifact identity
artifact checksum
executor
backend
```

Time-range filters, pagination, sorting controls, and a general query language
are deferred.

## Catalog Consistency

Default CLI and API reads use current refresh-on-read behavior.

Listing commands should make staleness visible:

```text
index missing
index older than run metadata
run directory disappeared
run metadata unreadable
```

The catalog should never silently override authoritative run-store records.

## Comparison

Run comparison explains why two runs differ using metadata.

Implemented command:

```bash
loom runs diff runs/ RUN_A RUN_B
```

Comparison should include:

```text
run status
resolved config summaries
config fingerprints
pipeline fingerprints
stage actions and statuses
stage fingerprints
input artifact identities
output artifact identities
selected provenance facts
executor identities
environment summaries
```

Comparison should not require loading domain artifact payloads.

## Comparison Result Model

Recommended shape:

```python
@dataclass(frozen=True)
class RunComparison:
    left_run_uri: str
    right_run_uri: str
    sections: tuple[ComparisonSection, ...]

@dataclass(frozen=True)
class ComparisonEntry:
    key: str
    left: object
    right: object
    status: str
```

Statuses:

```text
same
different
left_only
right_only
unknown
```

Path examples:

```text
run.status
fingerprints.config
stages.train.fingerprint
artifacts.evaluate.metrics.checksum
provenance.git.commit
```

## Comparison Boundaries

Comparison should be explicit about what it can and cannot compare.

It can compare:

```text
metadata values
fingerprint values
checksums
artifact logical names
stage status records
```

It should not compare by default:

```text
large artifact payloads
domain-specific metrics semantics
binary file diffs
notebook rendering
```

Domain-specific comparison can be added through plugins later.

## Export

Run export creates a portable bundle from an existing completed run.

Implemented command:

```bash
loom runs export RUN_URI run.tar
```

The v12 local bundle format is:

```text
tar archive
manifest.json
completed-run metadata
source identity facts
target-local import policy facts
optional selected payload/log/workspace refs
diagnostics and extension fields
```

Metadata-only export is the default. Payload movement is explicit:

```bash
loom runs export RUN_URI run.tar --include-payloads
loom runs export RUN_URI run.tar --include-logs
loom runs export RUN_URI run.tar --include-workspace
loom runs export RUN_URI run.tar --verify-checksums
```

When artifacts carry Stage 15 external, published, location, or unsupported
materialization summaries, export preserves those summaries in the bundle
manifest extension `stage_15_artifact_summaries`. This is metadata only: export
does not contact remote stores, check credentials, download payloads, or treat
the local bundle format as a provider protocol.

Stage 16 keeps that default and adds an explicit Python API materialization
path for supported payload handlers. A caller may request backend
materialization for selected payload refs by passing both a materialization
option and a handler:

```python
from loom.runs import RunBundleExportOptions, export_completed_run_bundle

result = export_completed_run_bundle(
    metadata,
    "run.tar",
    options=RunBundleExportOptions(include_payloads=True, materialize_payloads=True),
    payload_handler=fake_or_plugin_payload_handler,
)
```

If the handler is missing, does not implement the payload protocol, reports
unsupported materialization, fails checksum evidence, or returns an invalid
result, export fails closed with structured diagnostics. Successful
materialization records the operation evidence in the bundle manifest extension
`stage_16_materialization_operations` and preserves the original remote source
URI in the materialized payload ref extension. The CLI does not expose provider
materialization flags in Stage 16 because core has no first-party backend
registry or credential surface.

The local bundle archive is one first-party adapter over portable-run exchange
records. It is not the protocol for later remote stores or external tracking
providers.

## Export Manifest

Every bundle should include a manifest.

Example:

```json
{
  "format": "loom.run_bundle.v1",
  "created_at": "2026-05-03T02:14:09Z",
  "run_uri": "file:///abs/runs/20260503T021409Z-a13f7c",
  "entries": [
    {
      "path": "state/run.json",
      "kind": "run_state",
      "sha256": "..."
    }
  ]
}
```

The manifest should allow inspection without trusting arbitrary bundle paths.

## Export Safety

Export must guard against:

```text
path traversal
symlink surprises
partially written runs
missing artifact payloads
large unexpected files
```

The export command has explicit flags for payload selection:

```text
metadata-only default
--include-payloads
--include-logs
--include-workspace
--max-payload-count
```

The default should be conservative and documented.

## Inspect

Bundle inspection reads the manifest and summaries without extraction.

Implemented command:

```bash
loom runs inspect run.tar
loom runs inspect run.tar --verify-checksums
```

It should report:

```text
bundle format
run ID
run status
created_at
stage summary
artifact summary
included payload count and size
checksum validation status when requested
```

Inspection does not extract files into the current directory. Unsafe paths,
duplicate archive members, unsupported schemas, checksum mismatches, and
malformed archives surface as structured diagnostics.

Inspect output preserves the `stage_15_artifact_summaries` extension when it is
present, so external references remain visible without reading or extracting
payload members.

When `stage_16_materialization_operations` is present, inspect preserves that
plain operation evidence in manifest extensions. It still does not extract files,
download remote payloads, or probe backend credentials.

## Import

Run import copies a bundle into a local run collection.

Implemented command:

```bash
loom runs import run.tar runs/
```

Import should:

```text
validate the bundle manifest
reject unsafe paths
create a target-local run directory
preserve source run URI and bundle identity as provenance
write imported metadata
verify checksums under the strict default policy
refresh the local catalog view after a successful import
record historical-only resume readiness blockers
```

Import should not execute project code.

For Stage 15 summaries, import preserves the manifest extension in import
provenance and keeps imported artifact refs metadata-only unless payloads were
explicitly included and copied. Unsupported remote materialization is recorded as
a warning diagnostic, not as an implicit download attempt.

The Stage 15 and Stage 16 extensions are stable metadata and evidence handoffs.
They are not provider protocols and should not be used to infer that a remote URI
is reachable or writable. Adapter-specific import behavior must remain opt-in
and capability-checked.

Imported runs are historical-only in v12. Live migrated resume, merge,
overwrite, fork, remote payload materialization, signed/encrypted bundles,
deduplication, automatic post-run export dispatch, provider plugins, and
concrete SSH/object-store transfer handlers are deferred.

Offline evidence remains a separate authority-owned adapter. It shares portable
import result semantics but is not converted into a local bundle before import.

## Run Store Boundary

The run store is authoritative for:

```text
run state
stage state
attempt records
artifact records
provenance records
```

The catalog reads these records and writes derived summaries. If there is a
conflict, the run store wins.

## Artifact Store Boundary

Export/import must use artifact store APIs when possible.

For local artifact stores, export can copy payload files after validating they
belong to the run. For future remote stores, export may need a staging step or a
metadata-only mode.

The catalog should not assume all artifact payloads are local files.
It should also not infer materialization readiness from preserved remote URIs or
bundle extension evidence. Catalog summaries remain metadata-only unless a
future stage explicitly adds derived materialization projection with matching
tests.

## Testing

Tests should cover:

```text
scan empty run collection
scan collection with valid runs
scan collection with invalid directories
build and rebuild local index
filter by status
filter by tag
filter by fingerprint
CLI index/list/diff text and JSON output
compare identical metadata
compare different stage fingerprints
metadata-only export
export manifest checksums
inspect bundle without extraction
reject path traversal on import
import into temporary run collection
stale index detection
```

Tests should use temporary directories and small fixture files.

## Implementation Plan

1. Define run summary and catalog index models. Implemented in v8.
2. Implement run directory discovery from run-store markers. Implemented in v8.
3. Implement SQLite index rebuild and current direct scan fallback.
   Implemented in v8.
4. Add listing, exact-match filters, and CLI JSON output. Implemented in v8.
5. Implement metadata-only run comparison and CLI diff output. Implemented in
   v8.
6. Implement safe export manifest creation.
7. Implement inspect and import around the manifest.

## Deferred Work

Deferred catalog features:

```text
remote run catalog service
dashboard UI
domain-specific artifact diffs
large payload deduplication
signed bundles
incremental catalog watchers
cross-machine catalog synchronization
```

These should wait until local run-store metadata and artifact manifests are
stable.
