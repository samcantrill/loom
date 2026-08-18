# Shared Subagent Lifecycle

Use this contract only when an active workflow requires a subagent.

1. Admit one bounded task with role, evidence root, allowed writes, expected
   result, and stop conditions.
2. Pass only the role prompt path, artifact paths and exact headings, evidence
   revision, and current blocker or decision. Never paste prompt bodies,
   artifact bodies, diffs, logs, or manager history.
3. Spawn with fork_turns=none. State that the child cannot delegate.
4. Continue independent work, then wait event-first with the maximum supported
   timeout: 3,600,000 ms (one hour). If that wait times out without an event,
   begin another full one-hour wait. Do not poll between waits, list agents,
   send heartbeats, or duplicate healthy work.
5. Accept only a terminal result with the requested artifact, finding, or
   explicit blocker.
6. Verify scope and evidence before advancing.
7. Record only result, status, and any material anomaly in durable state.

If an optional spawn is unavailable, use the documented manager-local path. If a
required expanded-path spawn is unavailable, record the override or block.
