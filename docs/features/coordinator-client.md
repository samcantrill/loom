# Native Coordinator Client

`loom.coordinator.CoordinatorClient` controls an existing Loom coordinator from
Python. The coordinator owns admission, durable state and scheduling. A client
on the coordinator host uses its Unix socket; a client on another host uses
authenticated HTTPS. Both connections expose the same native operations and
results. A client host needs no worker root, agent registration or supervisor.

Closing a client releases its local resources. Submitted work continues under
the coordinator and workers. Cancellation is a separate, explicit operation.

## Choose A Connection

```python
from loom.coordinator import CoordinatorClient

local_client = CoordinatorClient.from_unix_socket("/run/loom/coordinator.sock")
remote_client = CoordinatorClient.from_connection_file("/path/to/client.yaml")
```

Replace these sample paths with deployment values. Construction does not start
a service or submit work. The first operation connects and negotiates the native
protocol. The facade requires `daemon-control-v1` under application protocol
version 1; an older service fails as unsupported before a dependent mutation.

The remote connection file uses this protected YAML schema:

```yaml
schema_version: 1
kind: loom.coordinator-client
transport:
  kind: https
  url: https://coordinator.example:8443
  server_ca_path: /etc/loom/ca.crt
  certificate_path: /etc/loom/client.crt
  private_key_path: /etc/loom/client.key
expected_coordinator_id: coordinator-production-001
```

Only `expected_coordinator_id` is optional at the top level. The file must be
owned by the invoking user and inaccessible to other users, for example mode
0600. Existing protected deployment input and TLS path rules apply. Relative
certificate/key paths resolve beside the file. TLS checks the server CA and
service name, presents the enrolled client certificate and follows no redirects.
The coordinator's current policy must authorize the client role. Certificate
issuance and enrollment remain deployment operations.

Unix connections retain owner permissions and peer identity checks. Client
permissions are deployment-wide. A query, worker or operator credential does
not gain client actions by selecting this file. A fleet worker host uses the
same client independently of its worker agent. See
[protected role deployment](../downstream-operations.md#protected-coordinator-and-agent-roles)
for service configuration and initialization.

## Submit And Observe

The run must already be prepared by a supported Loom workflow. Its URI identifies
coordinator-owned state; the client need not be able to open that path locally.

```python
from loom.coordinator import CoordinatorClient
from loom.queue import LocalDaemonAdmissionRequest


def submit_and_observe(connection_file, prepared_run_uri, queue_item_id):
    with CoordinatorClient.from_connection_file(connection_file) as client:
        coordinator_id = client.describe_connection().coordinator_id
        admission = client.submit(
            LocalDaemonAdmissionRequest(
                queue_item_id=queue_item_id,
                run_uri=prepared_run_uri,
            ),
            expected_coordinator_id=coordinator_id,
        )
        detail = client.admission(
            admission.admission_id,
            expected_coordinator_id=coordinator_id,
        )
        observation = client.wait_admission(
            admission.admission_id,
            expected_revision=detail.admission.revision,
            timeout_seconds=25,
            expected_coordinator_id=coordinator_id,
        )
        return coordinator_id, admission, observation
```

Keep the coordinator ID, caller-chosen queue item ID, returned admission ID and
run URI. Admission `ACTIVE` means admitted work; use native owner projections
to determine actual execution. Agent availability observes capacity and does
not reserve a worker.

## Python Operations

Every method accepts optional keyword `expected_coordinator_id`. Successful
results reuse native models at their existing import paths.

| Method | Result and meaning |
| --- | --- |
| `describe_connection()` | Typed protocol version, transport, coordinator ID/epoch, capabilities, source modes and safe preparation profile/root aliases |
| `status()` | `DaemonStatus` |
| `admissions(limit=20, cursor=None)` | `AdmissionPage` and opaque next cursor |
| `admission(admission_id)` | `LocalDaemonAdmissionDetail`, including owner evidence |
| `admission_for_queue_item(queue_item_id)` | `LocalDaemonAdmission` for that caller ID |
| `agents(limit=20, cursor=None)` | `AgentPage` |
| `agent(agent_id)` | `AgentProjection` |
| `inspect_run(run_uri)` | Existing `RunInspectionResponse` success/failure union for a managed admitted run |
| `operation(operation_id)` | `LocalDaemonOperation` |
| `wait_operation(operation_id, timeout_seconds=25)` | `OperationWaitResult`: `TERMINAL` or `TIMEOUT` |
| `submit(request)` | `LocalDaemonAdmission` for a `LocalDaemonAdmissionRequest` |
| `wait_admission(admission_id, expected_revision=..., timeout_seconds=25)` | `AdmissionWaitResult`: `CHANGED`, `TERMINAL` or `TIMEOUT` |
| `cancel(queue_item_id)` | Admission acknowledging the native cancellation request |
| `wait(queue_item_id, timeout_seconds=None)` | Terminal admission; explicit deadline expiry raises `TimeoutError` |

Pages accept integer limits from 1 to 100. Preparation aliases/modes are empty
when that capability is unavailable. Connection metadata describes supported
policy and identity; it is not a reservation or proof of later authorization.

The bounded observation methods accept finite durations from 0 to 25 seconds.
Zero performs one nonblocking observation. `TIMEOUT` means the window ended;
it does not mean the job failed or stopped. The explicitly requested terminal
convenience `wait()` renews observations until terminal state or its overall
deadline. Passing `None` deliberately permits an unlimited overall wait. I/O
failure remains an error and is never converted into terminal job state.

Queue lookup followed by admission detail is two observations. Inspection also
joins native owners with their own revisions and freshness, rather than one
atomic snapshot. A failed run or native `RunInspectionFailure` returns diagnostic
evidence, preserving the existing union and nested failure information.

## Reconnect And Reconcile

Guard saved IDs with their coordinator identity:

```python
from loom.coordinator import CoordinatorClient


def reconnect(connection_file, coordinator_id, queue_item_id):
    with CoordinatorClient.from_connection_file(
        connection_file,
        expected_coordinator_id=coordinator_id,
    ) as client:
        return client.admission_for_queue_item(queue_item_id)
```

The guard may come from the file, constructor or individual call. A call value
must agree with the configured connection default. The effective guard travels
with every request and is checked by the coordinator before lookup or mutation.
A mismatch is a `conflict` containing expected and observed coordinator IDs;
mutations report `not_applied`. A successful earlier handshake alone cannot
guard a later request after an endpoint changes.

`CoordinatorClientError` belongs to the `QueueServiceError` family. Structured
fields are `code`, `boundary`, `operation`, `ids`, `evidence_refs` and
`mutation_outcome`. Wire errors add schema-1 `error_detail` beside the existing
readable `error`; successful payloads retain their native shape.

| Mutation outcome | Meaning |
| --- | --- |
| null | This was a read |
| `not_applied` | Authoritative evidence establishes that the mutation did not apply |
| `applied` | Authoritative evidence establishes that the mutation applied |
| `unknown` | The request may have committed; retain its IDs and reconcile |

A lost submit reply is unknown. Look up its original queue item ID or replay
the exact original request. Immediate not-found can race the original request
and does not prove non-acceptance. Changing the run URI under the same ID retains
native conflict behavior. A new ID after an uncertain reply can duplicate work.
There is no blanket mutation retry.

Codes distinguish `invalid_request`, `unauthorized`, `not_found`, `conflict`,
`unsupported`, `unavailable`, `deadline_exceeded`, `capacity_exhausted`,
`result_too_large`, `invalid_response` and `internal_error`. Boundaries identify
connection, authentication, client protocol or coordinator failure. Native
operation and diagnostic codes stay in their own results. An old HTTP 403 alone
does not establish authorization failure.

Cancellation acknowledgement is not proof of process containment or resource
release. Observe the admission's native evidence for the actual result.
Disconnecting, closing a context or timing out does not issue cancellation.

## Bounds And Transport Behavior

Finite calls share a cumulative 30-second budget across capacity admission,
connection, writes and response reads. Slow response fragments do not restart
it. HTTP observations renew server waits of at most five seconds under the
existing ten-second per-call bound; Unix retains half-second server slices.
Bounded separate connections and reserved ordinary capacity allow control and
worker traffic to progress alongside waits.

Responses are bounded at 1 MiB, including inspection. Oversized results fail
explicitly; admissions and nested diagnostic evidence are never silently
truncated. Worker-message and diagnostic structural limits keep their existing
owners. Client operations use existing Unix names and
`POST /v1/client/<operation>` routes, including reads. Authentication happens
on every request; native application authorization remains authoritative.

## CLI And Compatibility

Client commands under `loom queue` select exactly one of `--endpoint PATH` or
`--connection PATH`, with optional `--expected-coordinator-id ID`. Existing
names, positional arguments, JSON fields and exit meanings remain unchanged.
For example, using deployment-specific paths and an already-prepared run:

```sh
loom queue daemon-status --connection /path/to/client.yaml --format json
loom queue daemon-submit --connection /path/to/client.yaml example-001 file:///srv/loom/runs/example
loom queue daemon-admissions --connection /path/to/client.yaml --limit 20 --format json
loom queue daemon-admission --connection /path/to/client.yaml ADMISSION_ID --format json
loom queue daemon-wait --connection /path/to/client.yaml example-001 --timeout 30 --format json
loom queue daemon-cancel --connection /path/to/client.yaml example-001 --format json
```

Substitute `--endpoint /run/loom/coordinator.sock` on the coordinator host.
Guard a reconnect with `--expected-coordinator-id ID_FROM_RECEIPT`. CLI page
defaults remain 100 and legacy CLI wait durations renew bounded observations
where needed. Administration, recovery and role initialization retain their
separately authorized interfaces; see [CLI details](cli.md).

`LocalDaemonSocketClient` remains available at its established import path. Its
constructor, page default of 100, timeout keywords, `AdmissionNotFoundError`,
other legacy queue errors and terminal `TimeoutError` are preserved. Its
old-server subset does not require the new capability handshake. The original
Unix inspection adapter preserves its broader local entrypoint; the new facade
uses the managed-admission restriction on both transports. Query-only inspection
retains its distinct read-only credential policy.

The facade and compatibility adapter share lower-level control behavior and
codecs. `loom.coordinator` combines these values with diagnostics above queue;
queue/runtime modules do not import the facade or an MCP SDK. `QueueClient` and
`QueueService` keep their existing queue semantics.
