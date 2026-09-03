# Managed-Local Terminal Settlement Repair

## Objective

Make a managed-local admission publicly terminal only after every ordinary
local assignment for that run has released its retained capacity, and make a
clean supervisor shutdown return only after the exact supervisor process has
exited.

This is a bounded lifecycle correction. It does not change worker-result
meaning, retry policy, output publication, scheduling, or guarded recovery.

## Evidence and failure mechanism

The lost-resident-worker path correctly contains the worker process group and
creates a durable infrastructure failure. Its finalization order is deliberately
split across owners:

1. record the authority terminal fact;
2. advance the coordinator assignment through `terminal` to
   `logical_released`;
3. release provider claims and publish fresh availability;
4. advance the coordinator assignment to `released`.

That finalization runs in a background future. At the same time,
`LocalDaemonExecution.reconcile_admission()` projects authority truth into the
public admission. It can therefore return `FAILED` after step 1 and before
step 4. `LocalDaemon.wait()` treats that admission state as terminal, so a
caller can observe `logical_released` after `wait()` returns.

The supervisor service is intentionally detached so it can survive a daemon
restart with retained work. `AgentProcessSupervisorClient.shutdown_clean()`
currently waits only for the Unix endpoint to disappear. Endpoint removal
happens immediately before service exit, so the method does not itself prove
that the exact service process has exited.

## Locked behavior

### Ordinary local completion

- Authority truth may become terminal before provider release completes.
- A public admission remains nonterminal while an ordinary local assignment
  for that run is retained.
- Once that assignment reaches `released`, the next reconciliation may publish
  `SUCCEEDED`, `FAILED`, or `CANCELLED` as appropriate.
- No replacement assignment or retry is created merely because release is
  settling.
- The settling diagnostic must describe release progress, not report an
  execution failure or unavailable daemon.

### Guarded recovery

- An assignment explicitly retained by a pending, evidence-confirmed, or
  closed guarded recovery remains exempt from ordinary-release settlement.
- Existing recovery behavior may therefore publish a terminal run while the
  exact assignment remains `unknown` and physically retained.
- Launch or containment uncertainty still fails closed.

### Supervisor lifetime

- The supervisor remains detached from the daemon process.
- Stopping a daemon with retained work continues to leave the supervisor alive
  for a successor daemon.
- A successful `shutdown_clean()` means both that the endpoint is unavailable
  and that the exact service PID observed by the client no longer exists.
- Shutdown never scans for or signals unrelated Loom processes.

## Implementation shape

### 1. Add one authoritative local-settlement query

Add a private `LocalDaemonExecution` query that uses the existing coordinator
retained-assignment inventory for the configured local machine. For the target
run, any retained local assignment means ordinary release is still settling,
unless the daemon's durable recovery records explicitly retain that assignment.

Do not infer settlement from future completion alone. The coordinator's
`released` transition is the durable cross-thread fact and remains the single
owner of assignment-capacity release truth.

### 2. Gate terminal projection at both reconciliation points

After `_terminal_outcome()` returns a candidate terminal outcome, first apply
the existing SLURM-release gate and then the new local-release gate. While the
local gate is active, return `ACTIVE` with a stable settlement diagnostic.

Apply the same helper at both pre-orchestration and post-orchestration terminal
checks so a previously terminal authority snapshot cannot bypass the gate on a
later daemon cycle.

### 3. Prove supervisor service exit

Validate and retain `service_process_id` from the authenticated status response
when constructing `AgentProcessSupervisorClient`.

After a shutdown response, wait until:

1. the protected Unix endpoint is absent; and
2. probing that exact PID reports `ProcessLookupError`.

Use the existing bounded shutdown deadline. Treat an invalid PID or an exact
process that remains alive past the deadline as a supervisor error. Do not add
global process discovery or parent-process coupling.

## Deterministic regression coverage

### Terminal settlement race

Extend the lost-worker production integration test with an injected release
barrier after the authority failure and coordinator logical release are durable
but before final availability publication completes.

While the barrier is held, assert:

- the authority stage is failed;
- the coordinator assignment is `logical_released`;
- the admission remains `ACTIVE`;
- no output or retry is published.

Release the barrier, then assert:

- `client.wait()` returns `FAILED`;
- the assignment is `released`;
- the process group is contained;
- there is exactly one attempt and no output publication or retry.

### Recovery preservation

Run the existing guarded-recovery integration cases unchanged. Their retained
`unknown` assignment remains accepted behavior.

### Supervisor shutdown

Strengthen the supervisor unit test so `shutdown_clean()` is immediately
followed by an assertion that the recorded service PID is absent. Keep the
existing non-quiescent rejection and continuity-rotation coverage.

Run the daemon-restart integration test to prove that stopping with retained
work still preserves the same supervisor and that the successor daemon joins
the same launch.

## Files in scope

- `src/loom/queue/local_daemon_execution.py`
- `src/loom/queue/_agent_process_supervisor.py`
- `tests/integration/queue/test_local_daemon_production.py`
- `tests/unit/loom/queue/test_agent_process_supervisor.py`
- `docs/features/reliability.md` only if the public completion wording is not
  already explicit enough after implementation.

## Validation sequence

1. Run the new deterministic lost-worker test alone.
2. Run supervisor unit tests.
3. Run guarded-recovery and daemon-restart production integration tests.
4. Repeat the deterministic lost-worker test enough times to exercise thread
   scheduling without relying on retries for correctness.
5. Run the complete queue unit and integration files affected by the change.
6. Run `make validate-pr`.
7. Run `make test-summary` before PR preparation if the repair proceeds to a
   Loom PR.

## Exclusions and stop conditions

- Do not change the meaning of `logical_released` or collapse it into
  `released`.
- Do not weaken downstream assertions to accept `logical_released` after
  `wait()`.
- Do not add sleeps as synchronization.
- Do not kill supervisors by name, scan all user processes, or tie supervisor
  survival to daemon parent death.
- Stop and redesign if the terminal gate breaks guarded recovery, or if exact
  shutdown proof requires weakening restart continuity.

## Downstream handoff

After the Loom repair is committed and validated, rphys can update its Loom Git
pin and lockfile, rerun the exact reference integration test, and then rerun its
full PR validation. That downstream pin update is not part of this Loom repair.
