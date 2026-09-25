# Accessing selected artifact files

`CoordinatorClient` exposes `describe_artifact`, `read_artifact_chunk`,
`read_artifact`, and `fetch_artifacts`. These consume exact `OutputLocator`
identities from [output selection](output-selection.md). They never substitute
the producer's latest output, execute its codec, or change run annotations.
Native `artifact-read-v1` requests support Unix and authenticated HTTPS; CLIENT
and QUERY credentials use the same authorized resolver.

The supported sources are committed regular files below the selected run's
artifact directory and complete native shared-publication receipt trees admitted
by the coordinator's protected shared-root mappings. A client needs no producer
mounts. Shared publications include every receipt member, even if several outputs
share the tree; `primary` identifies this selection's entry point. No application
manifest is parsed to infer companions. Directories without a declaration return
`unsupported_closure`; cloud/external locations without a supported reader return
`unsupported_backend`. Files outside the allowed roots cannot be read by supplying
a path or editing an artifact reference.

```python
from loom.coordinator import CoordinatorClient
from loom.runs import OutputLocator, OutputSelection

with CoordinatorClient.from_connection_file("client.json") as client:
    page = client.select_outputs(OutputSelection(run_uris=(source_run_uri,)))
    selected = page.items[0]  # Account for all pages and no-output outcomes first.
    locator = OutputLocator.from_dict(selected["locator"])
    declaration = client.describe_artifact(locator)
    preview = client.read_artifact(locator, format="json", limit=262144)
    batch = client.fetch_artifacts([selected], "./retrieved")
```

Description inventories page at 100 members by default (maximum 200), with an
additional response byte bound. Pass `next_cursor` and the returned `declaration`
to subsequent description requests. Chunk requests require that declaration,
a declared relative `member`, byte `offset`, and `length` of at most 262144.
Responses contain base64 `data`. Each call reauthorizes the exact producer and
checks declaration identity. Repeating a chunk is safe after an uncertain reply;
the fetch helper retries a transient failed chunk once with identical arguments.

Previews default to the primary member. `format="text"` uses strict UTF-8 and
labels bounded prefixes as `truncated`, without splitting a character. Invalid
UTF-8 returns `invalid_content`. JSON must fit wholly within the raw limit and
response envelope or returns `too_large`; malformed JSON returns `invalid_content`.
`format="bytes"` returns base64. All formats have a maximum raw limit of 256 KiB;
JSON envelope expansion can further limit presentation. Application `_target_`,
pickle, HTML and codec metadata are never evaluated.

Fetch writes a private temporary directory under the explicit destination,
preserves declared relative paths, and verifies full sizes and recorded SHA-256
digests before atomic publication. Final directory names are declaration digests.
Linux `renameat2(RENAME_NOREPLACE)` provides atomic publish-if-absent; filesystems
without that operation return a failed item. Existing files, symlinks and even
empty destination directories return `destination_exists`; nothing is overwritten.
Only the helper's own temporary tree is cleaned on failure. A cleanup failure
returns its exact `partial_path`. Restart-resumable partial downloads and retention
pins are not provided.

Each result preserves its locator and caller-supplied source/reuse association.
Identical declarations download once per batch, with a result for every input in
input order. `complete` means every input was processed. Inspect `success_count`,
`failure_count` and individual outcomes (`available`, `unavailable`,
`unsupported_backend`, `unsupported_closure`, `integrity_failed`,
`destination_exists`, `failed`, or retained selection outcomes). A failed run may
still have a usable committed output. Deletion or mutation yields failure, never
a successor substitution. `verification="unverified_original"` identifies legacy
files with no recorded checksum: consistent transfer cannot prove original bytes.

CLI commands take JSON native requests with the existing connection flags:

```sh
loom artifacts describe --connection client.json --format json --request '{"locator": {"run_uri": "...", "stage_name": "...", "commit_id": "...", "output_name": "..."}}'
loom artifacts read --connection client.json --format json --request '{"locator": {"run_uri": "...", "stage_name": "...", "commit_id": "...", "output_name": "..."}, "format": "text", "limit": 4096}'
loom artifacts fetch --connection client.json --format json --request '{"selections": [{"locator": {"run_uri": "...", "stage_name": "...", "commit_id": "...", "output_name": "..."}}], "destination": "./retrieved"}'
```

MCP provides `loom_describe_artifact(request)`, `loom_read_artifact(request)` and
`loom_fetch_artifacts(selections, destination, scope)`. Fetch has a local-write
hint and returns `location_context="mcp_process_filesystem"`: these paths belong
to the MCP process host, not necessarily the assistant user's laptop. Use bounded
content previews when that filesystem is inaccessible. Python and CLI report
`client_process_filesystem`.

## Composing discovery, lineage and explicit annotation

The same workflow works for `tags.study=kernel` with type `summary_manifest`, or
`tags.customer=example-company` with type `invoice_report`. Applications supply
those labels and types. The executable two-vocabulary acceptance is
`tests/integration/queue/test_run_discovery_workflow.py`.

1. Exhaust `search_runs` pages for the caller's tag/time query, retaining every
   page's coverage warnings and original submission context.
2. Select source outputs, then exhaust downstream `trace_lineage` pages. Keep
   connecting intermediate nodes and original producer identities. Record the
   mapping from each chosen source run to its downstream report producers.
3. Select the caller's report type from those producers and consume all pages,
   retaining no-output outcomes. Explicitly preview or fetch those selections.
4. Report every retrieval outcome and coverage warning, including unsupported
   entries in a mixed batch. Equal bytes or a reuse association do not establish
   independent observations.
5. For an explicit request to mark **source runs**, intersect the caller-approved
   source set with the recorded source-to-report mapping for successful fetches.
   Read each source's current annotation revision, then explicitly call
   `patch_run_annotations(..., mutation_id=..., expected_revision=...,
   set_tags={"review": "ready"})`. Do not silently annotate downstream producers
   or sources whose requested reports were not obtained. Retrieval itself has no
   tagging side effect.
