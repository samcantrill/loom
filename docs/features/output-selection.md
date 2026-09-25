# Published output selection

Native output discovery reads committed metadata without opening payloads or
executing codecs. Python, `loom runs outputs`, and MCP `loom_select_outputs`
share the `output-query-v1` coordinator capability over Unix and authenticated
HTTPS. CLIENT and QUERY readers use the same authorized selection behavior.

```python
from dataclasses import replace
from loom.runs import OutputSelection, SelectedOutput

request = OutputSelection(run_uris=(run_uri,), stage_names=("summarize",))
page = client.select_outputs(request)
for item in page.items:
    if item["outcome"] == "selected":
        selected = SelectedOutput.from_dict(item)
        print(selected.locator, selected.artifact)
    else:
        print(item)  # Explicit missing or unavailable selectors remain visible.
while page.next_cursor is not None:
    request = replace(request, cursor=page.next_cursor)
    page = client.select_outputs(request)
    # Process every item and retain every page's warnings and coverage.
```

`OutputLocator(run_uri, stage_name, commit_id, output_name)` names the original
producer's existing commit. `matched_run_uri` and `matched_stage_name` preserve
the run/node through which selection found a reused output. Reuse allocates no
new producing commit. Equal checksums, tags or locations do not establish reuse.
Both the matched run and producer must be authorized in the selected scope;
bindings and locators confer no access rights and do not follow credentials to
other deployments. Restricted producer responses omit hidden identities and refs.

The default `history="current"` reads authority heads and current reuse bindings,
even when a later stage or the run failed. `history="all"` enumerates retained
commits and the current adoption association. Historical adoption facts that
were never retained cannot be reconstructed. `client.list_output_commits(request)`
returns the same bounded page format, grouping selected output facts under their
commit records, and always uses all history. No new index or version identity is
created. `OutputSelection(locator=selected.locator)` resolves the exact producer
commit again, even after a successor becomes current. No retention pin or payload
availability guarantee follows from selection.

Selection accepts exactly one of `run_uris`, `query=RunQuery(...)`, or `locator`.
Optional `stage_names`, `output_name`, `artifact_type` and `metadata` filters are
application-neutral. Metadata matches literal top-level keys using typed JSON
equality; booleans do not equal numbers and absent keys do not match null. Numeric
values compare numerically, including inside JSON containers. Strings and recorded
`_target_` fields remain inert. A query's scope must agree with the selection's
scope. Managed scope uses coordinator journal membership; `CollectionScope()`
uses the configured `run_store` collection, with producer containment checks.
Arbitrary filesystem roots and output-URI overrides are unsupported.

Pages contain at most 200 results (default 50) and may end early at a run or
response-byte boundary. Explicit run and stage lists are each limited to 200;
metadata filters to 64 keys. An item larger than 512 KiB is replaced by an
explicit `metadata_too_large` outcome and continuation still advances. Output
pages target 640 KiB of item/warning content, below the native 1 MiB envelope.
Nested query paging retains discovery warnings and its bounded scan behavior.
Cursors bind the coordinator, scope, operation, filters and limit. Changing
these requires restarting selection. Observations are live, not snapshots;
changes between pages can affect later matches. Keep the selected locator to
refer to a particular version. A terminal page does not erase earlier warnings.

Every selected item reports `availability="not_checked"`, its authority revision,
run status, current/all/exact policy, native commit and artifact facts, and any
retained reuse verification. Recorded checksums and fingerprints are evidence,
not a new byte verification. A caller-modified `ArtifactRef.uri` cannot change
what a locator selects. This metadata surface does not read, preview or fetch
artifacts or guarantee support for their URI backends.

`no_matching_output` records an inspected explicit run/stage without a matching
published output; `run_not_found` means the run is not in the authorized managed
selection. `authority_unavailable`, `producer_restricted`, `producer_unavailable`
and `metadata_too_large` retain associations and make coverage incomplete. An
empty filtered run query is a distinct, successful empty result. Missing payload
files cannot affect these metadata results.

```sh
loom runs outputs --endpoint /path/to/coordinator.sock \
  --run-uri file:///path/to/run --history all --format json
loom runs outputs --connection client.json \
  --selection '{"run_uris":["file:///path/to/run"],"artifact_type":"invoice_report"}' \
  --format json
```

The CLI JSON `result` and MCP structured result carry the native page without
flattening associations or dropping failures. For MCP, pass the same selection
object to `loom_select_outputs`; it is a read-only tool.
