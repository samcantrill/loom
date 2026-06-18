# loom.timestamps Specification

## Purpose

`loom.timestamps` provides the small set of time helpers used by run metadata,
state files, provenance records, logs, and path naming.

The module exists so that time handling is predictable across local execution,
subprocess execution, SLURM execution, and future container or remote execution
paths.

The design keeps `loom` on one rule:

```text
internal timestamps are timezone-aware UTC values
```

Local time can be used by callers when presenting information to humans, but it
is not used for persisted runtime metadata.

## Scope

This component owns:

```text
current UTC datetime creation
stable timestamp string formatting
path-safe timestamp string formatting
timestamp parsing for loom-authored metadata
normalization of aware datetimes to UTC
clear rejection of ambiguous naive datetimes in persisted metadata
```

This component does not own:

```text
scheduling
cron syntax
timezone conversion for user interfaces
duration parsing beyond small runtime policies
calendar arithmetic
logical clocks
distributed clock synchronization
```

## Design Goals

Timestamps should be:

```text
explicitly UTC
stable across platforms
safe to serialize as JSON/YAML text
safe to use in filesystem paths when requested
easy to parse back into aware datetime objects
boring enough to use everywhere
```

The module should stay dependency-free and rely on Python standard library
`datetime`.

## Non-Goals

`loom.timestamps` is not a replacement for a full time library.

It should not introduce:

```text
pendulum
arrow
dateutil as a required runtime dependency
pytz
timezone database handling
human-friendly relative time rendering
```

Those features belong either in user code, optional presentation tooling, or
future CLI formatting helpers.

## Core Invariants

All persisted metadata timestamps must satisfy these invariants:

```text
they represent an instant in UTC
they include timezone information in string form
they parse back to timezone-aware UTC datetimes
they do not depend on the machine's local timezone
they are not used as semantic input fingerprints unless explicitly included by project code
```

Wall-clock timestamps are allowed in provenance and state because they describe
execution history. They should not be included in stage fingerprints by default
because that would make every run appear semantically different.

## Public API

Recommended functions:

```python
from datetime import datetime

def utc_now() -> datetime: ...

def utc_timestamp(
    value: datetime | None = None,
    *,
    timespec: str = "seconds",
) -> str: ...

def safe_timestamp_for_path(
    value: datetime | None = None,
    *,
    timespec: str = "seconds",
) -> str: ...

def parse_timestamp(value: str) -> datetime: ...

def ensure_utc(value: datetime) -> datetime: ...
```

The API is intentionally small. Additional helpers should be added only when
multiple components need the same behavior.

## `utc_now`

`utc_now()` returns the current time as a timezone-aware UTC `datetime`.

Expected behavior:

```text
datetime is aware
datetime.tzinfo is UTC-compatible
no local timezone is consulted
```

Example:

```python
started_at = utc_now()
```

This helper should be preferred over direct calls to `datetime.now()` inside
`loom` runtime code.

## `ensure_utc`

`ensure_utc(value)` normalizes an aware datetime to UTC.

Expected behavior:

```text
aware UTC input returns an equivalent UTC datetime
aware non-UTC input is converted to UTC
naive input raises ValueError
```

Naive datetimes are rejected because their meaning depends on caller context.
For persisted runtime metadata, guessing is worse than failing early.

## `utc_timestamp`

`utc_timestamp(value=None, timespec="seconds")` formats a UTC timestamp for
metadata files.

Recommended default format:

```text
YYYY-MM-DDTHH:MM:SSZ
```

Example:

```text
2026-05-03T02:14:09Z
```

When subsecond precision is requested, the function should use standard ISO
8601 precision with a trailing `Z`:

```text
2026-05-03T02:14:09.123456Z
```

Accepted `timespec` values should mirror `datetime.isoformat()` where practical:

```text
seconds
milliseconds
microseconds
```

The default should remain `seconds` unless runtime evidence shows that
microsecond precision is needed broadly.

## `safe_timestamp_for_path`

`safe_timestamp_for_path(value=None, timespec="seconds")` returns a timestamp
string intended for directory and filename segments.

Recommended default format:

```text
YYYYMMDDTHHMMSSZ
```

Example:

```text
20260503T021409Z
```

For microseconds:

```text
20260503T021409123456Z
```

The path-safe form avoids:

```text
colon characters
space characters
timezone offset punctuation
locale-specific month or day names
```

This helper is appropriate for generated run IDs, temporary directories, and
sidecar bundle names. It is not a uniqueness guarantee by itself.

## `parse_timestamp`

`parse_timestamp(value)` parses timestamps written by `loom`.

Accepted forms:

```text
2026-05-03T02:14:09Z
2026-05-03T02:14:09.123456Z
2026-05-03T02:14:09+00:00
2026-05-03T02:14:09.123456+00:00
```

The returned datetime is always timezone-aware UTC.

Path-safe timestamps may be parsed by this helper only if that requirement
appears in multiple call sites. Initially, callers that generate path-safe
timestamps should retain structured metadata with the canonical metadata
timestamp as well.

Invalid or ambiguous values should raise `ValueError`.

## Metadata Fields

Common metadata field names should use these conventions:

```text
created_at
started_at
finished_at
failed_at
updated_at
submitted_at
recorded_at
```

Use `_at` for instant timestamps. Use `_seconds` for durations.

Examples:

```json
{
  "run_id": "20260503T021409Z-a13f7c",
  "created_at": "2026-05-03T02:14:09Z",
  "started_at": "2026-05-03T02:14:11Z",
  "finished_at": "2026-05-03T02:19:45Z",
  "duration_seconds": 334.0
}
```

## Run IDs

Timestamps may be part of generated run IDs, but they should not be the only
source of uniqueness.

Recommended generated shape:

```text
{safe_timestamp}-{short_random_suffix}
```

Example:

```text
20260503T021409Z-a13f7c
```

The random suffix avoids collisions from concurrent runs started during the
same second.

## State Integration

State records should store timestamps as strings, not Python datetime objects.

Examples:

```text
run created_at
stage started_at
stage finished_at
stage failed_at
transition recorded_at
heartbeat updated_at
```

The state layer may parse timestamps for sorting or filtering, but it should
write them through `loom.timestamps`.

## Provenance Integration

Provenance records should use timestamps to describe observation time.

Examples:

```text
source inventory resolution time
artifact materialization time
executor submission time
environment capture time
```

These timestamps are historical facts about the run. They are not evidence that
the underlying semantic inputs changed.

## Artifact Integration

Artifact metadata may use timestamps for:

```text
created_at
recorded_at
manifest_written_at
checksum_verified_at
```

Artifact identity should still come from logical identity, fingerprints, and
checksums rather than timestamps.

## Serialization Rules

JSON and YAML serializers should see timestamps as plain strings.

`loom` should avoid relying on serializer-specific datetime support because
different serializers emit different timezone and precision forms.

## Duration Rules

Durations should be stored as numeric seconds.

Examples:

```json
{
  "duration_seconds": 17.432,
  "queue_wait_seconds": 120.0
}
```

Human-friendly duration strings belong in CLI presentation layers, not in
canonical state.

## Error Handling

Errors should be plain `ValueError` unless the calling layer needs a richer
typed exception.

Recommended messages:

```text
timestamp must be timezone-aware
timestamp must be UTC or convertible to UTC
invalid loom timestamp: ...
unsupported timestamp timespec: ...
```

The helper should not silently accept ambiguous local-time strings.

## Testing

Unit tests should cover:

```text
utc_now returns an aware UTC datetime
ensure_utc rejects naive datetimes
ensure_utc converts non-UTC aware datetimes
utc_timestamp default format
utc_timestamp microsecond format
safe_timestamp_for_path default format
safe_timestamp_for_path does not include colon or space
parse_timestamp accepts canonical Z timestamps
parse_timestamp accepts +00:00 timestamps
parse_timestamp rejects invalid input
round-trip formatting and parsing
```

Tests should avoid asserting the exact current time. Use fixed datetime values
for formatting and parsing cases.

## Implementation Plan

1. Implement the helper module with standard library `datetime`.
2. Replace ad hoc timestamp formatting in runtime, state, provenance, and run
   store code.
3. Add focused unit tests for all helpers.
4. Audit persisted metadata examples in docs to use canonical UTC strings.

## Deferred Work

Deferred features:

```text
local timezone display preferences
relative time formatting
duration parsing from values such as 1h30m
path-safe timestamp parsing
monotonic logical event sequence numbers
clock skew detection for distributed controllers
```

These can be added later without changing the canonical persisted timestamp
format.

