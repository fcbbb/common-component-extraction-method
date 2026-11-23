# T4 — Thread and synchronisation port

- Kind: transformation
- Capability: `threading`
- Derived from: `l2_libuv_thread` (thread/mutex/cond/rwlock/TLS gold)
- Applies to: projects whose platform layer hides threads, locks, condition variables
  or thread-local storage
- Confidence: high for the primitive mapping; medium for timed waits and attributes

## When to use

The missing layer provides thread creation/join, mutexes, condition variables,
read-write locks, thread ids or TLS keys to the rest of the project.

## Procedure

1. **Inventory the primitives and their convention.**
   For each primitive, record whether the project uses macros, inline functions or
   real functions; whether success is `0` and failure `-1`, or a positive error
   number; and whether static initialization is required.

2. **Map the primitive family, not the Windows call.**
   - Thread: create, join, exit, current id, optional attributes (stack size,
     detach state).
   - Mutex: init, lock, trylock, unlock, destroy. Use default attributes unless the
     contract requires error-checking or recursive behavior.
   - Condition variable: init, wait, timed wait, signal, broadcast, destroy.
   - Read-write lock: init, read lock/unlock, write lock/unlock, destroy, static
     initializer.
   - TLS: key create/set/get/delete, destructor semantics.
   - Atomics: usually shared code, not the platform layer; do not move them.

3. **Decide where TLS lives.**
   Some projects implement TLS in the shared thread layer on POSIX and only wrap the
   native key API on Windows. Check which side of the boundary owns it before
   writing the platform header. Duplicating TLS in both places is a common failure.

4. **Match the error convention exactly.**
   pthread functions return a positive error number, not `-1`. If the project's
   contract is `-1`/`errno`, adapt at the boundary; if callers already accept the
   native convention, do not add a translation layer that changes success/failure
   detection.

5. **Preserve the locking contract.**
   If the source platform does not support recursive read locks, the port must not
   silently add them. Keep separate read/write unlock names if the shared code uses
   them, even when both map to one native unlock. Condition wait must be called with
   the mutex held; document the clock choice for timed waits.

6. **Provide static initialization where the project expects it.**
   Registry-style locks are often statically initialized. A missing static
   initializer is a link/compile failure or an uninitialized lock.

7. **Verify concurrency behavior, not just compilation.**
   Thread result values, abrupt exit, parallel error handling, lock contention and
   TLS destructor order.

## Semantic deltas to expect

| Area | Source platform | Target platform |
|---|---|---|
| Thread handle | OS handle / `_beginthreadex` | opaque `pthread_t` |
| Thread id | numeric handle-derived id | `pthread_self()` cast to an integer |
| Mutex | critical section / SRW lock | `pthread_mutex_t` |
| Condition variable | condition variable + sleep/wake | `pthread_cond_t`; timed waits need a clock |
| Read-write lock | SRW lock or project wrapper | `pthread_rwlock_t`; one unlock function |
| TLS | FLS / TLS index | pthread key + destructor |
| Error return | `-1` plus last-error, or boolean | positive error number, `0` on success |
| Thread attributes | explicit creation flags | `pthread_attr_t` or defaults |

## Pitfalls observed in successful migrations

- Mixing the native positive-error convention with callers that test `< 0`, so
  failures are invisible.
- Implementing TLS in the platform header while the shared layer already does it.
- Adding recursive read locks that the source platform never supported.
- Forgetting the static initializer used by registries.
- Using C11 `<threads.h>` when the project contract and callers use pthread names.
- Assuming a timed wait uses the same clock as the source platform.
- Destroying a mutex/condition variable while another thread can still use it.
- Not linking the platform thread library, or linking it only for some targets.
- Passing the wrong argument to join (status pointer vs value).

## Verification strategy

- A thread returns a value through join; an abrupt thread exit returns its value.
- Several threads mutating error or cache state produce no corruption.
- A statically initialized lock works.
- Read and write locks serialize correctly; separate unlock entry points behave.
- TLS values are per-thread and destructors run at thread exit.
- Build both with and without the project's threading feature flag if it is
  switchable.

## Boundary

Covers the primitive mapping and the common locking contract. It does not cover
thread pools, work queues, async notification, atomics or futex-level tuning; those
are shared-layer or separate components. Timed-wait clock semantics depend on the
project contract and must be checked per task.