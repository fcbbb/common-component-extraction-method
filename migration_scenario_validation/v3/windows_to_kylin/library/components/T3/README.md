# T3 — Process creation port

- Kind: transformation
- Capability: `process`
- Derived from: `l2_libuv_process` (spawn/stdio/env/wait gold)
- Applies to: projects that expose a process handle and must rebuild it on POSIX
- Confidence: high for spawn/stdio/wait; medium for process-group and privilege
  extensions

## When to use

The missing layer creates child processes, captures stdio, merges environment
variables, sets a working directory, or reports exit status.

## Procedure

1. **Read the contract for required semantics, not just function names.**
   Determine which of these the layer must support:
   argument vector vs command-line string, PATH lookup, environment addition and
   deletion, working directory, captured stdin/stdout/stderr, detached/process
   group, uid/gid switch, exit code vs signal reporting.

2. **Choose the mechanism from the semantics.**

   | Requirement | Prefer |
   |---|---|
   | Exact exec-failure reporting to the parent | `fork` + `execve` with an exec-status channel |
   | Complex fd remapping, cwd, environment | `fork` + `execve`; `posix_spawn` only if its file actions cover the case |
   | Simple spawn with no custom error channel | `posix_spawn`/`posix_spawnp` |
   | Command-line string with shell rules | run through `/bin/sh -c` |

   Do not pick `posix_spawn` merely because it is shorter if the contract requires
   synchronous exec-failure reporting or semantics its file actions cannot express.

3. **Build NULL-terminated `argv` and `envp`.**
   The argument-vector API does not perform PATH lookup; `argv[0]` is the executable.
   The shell API does. Keep that distinction exactly.

4. **Merge the environment explicitly.**
   Caller-supplied variables win. An entry with an empty value can mean “remove this
   key”; decide from the header and preserve it. When a mode provides the full
   environment, do not append the current one. Never mutate the global environment
   as a side effect.

5. **Create pipes only for captured streams.**
   In the child, `dup2` onto the standard descriptors and close the unused ends. In
   the parent, close the child-side ends immediately. Leaked ends are the most common
   cause of hangs.

6. **Report exec failure synchronously.**
   Use a dedicated pipe whose write end is close-on-exec. The child writes a
   fixed-size record containing the failing function and `errno`, then exits; on
   success the exec closes the write end and the parent reads EOF. Only after that
   read should the parent publish the child pid and report success.

7. **Map wait status faithfully.**
   Normal exit yields exit code; termination by signal yields the signal number.
   Reset the handle state after reaping. Formulate the result message from the
   contract, not ad hoc.

8. **Handle signals around writes.**
   A write to a closed child stdin must return an error rather than terminate the
   parent. Suppress SIGPIPE for the duration of the write, with separate threaded and
   non-threaded forms if the project supports both.

## Pitfalls observed in successful migrations

- Declaring start successful before knowing whether exec succeeded.
- Forgetting close-on-exec on the status pipe, so the parent blocks forever.
- Leaving child-side pipe ends open in the parent, so readers never see EOF.
- Using `system`/`popen` and losing argument fidelity, cwd and status mapping.
- Calling `exit` instead of `_exit` in the forked child, running duplicated atexit
  handlers and flushing shared buffers.
- Publishing the pid before the status read, then waiting on the wrong process.
- Treating `EINTR` as fatal in status or stdio I/O.
- Not closing descriptors on the failure path.
- Assuming caller environment entries are additive without key precedence.

## Verification strategy

- Normal child returns the expected exit code.
- A non-existent executable makes start fail, not succeed-then-fail at wait.
- Redirected stdin/stdout round-trips a payload; closing stdin delivers EOF.
- Working directory is honored.
- Signal-terminated child reports the signal.
- Failure path closes descriptors and leaves no zombie.

## Boundary

Covers spawn, stdio, environment, cwd and wait. Detached processes, process groups,
uid/gid switching and terminal control are only covered at the level of “the target
mechanism exists”; they need their own rules if a task depends on them. It does not
cover async process notification or thread-pool integration.