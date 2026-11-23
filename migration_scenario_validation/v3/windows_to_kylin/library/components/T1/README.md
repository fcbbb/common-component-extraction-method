# T1 — Platform contract recovery

- Kind: transformation
- Capability: `platform-abstraction`
- Derived from: successful ports in `l2_libuv_process`, `l2_libuv_thread`,
  `l2_libuv_fs`, `l2_libarchive_read_disk`, `l2_libarchive_write_disk`
- Applies to: C/C++ projects where the target platform implementation of an existing
  abstraction is missing, while shared headers and callers remain
- Confidence: high

## When to use

The task removes a platform implementation (a directory, a set of files, or a
feature layer) and expects the agent to rebuild it on POSIX. The Windows
implementation, shared headers and callers are visible; the target implementation is
not.

## Procedure

1. **Treat the shared header as the contract.**
   The platform layer exists to satisfy names that shared code already uses. Start
   from declarations and call sites, not from the source-platform file layout.

2. **Inventory the required surface.**
   Collect every name the shared code expects from the platform boundary:
   declared functions/macros, types, constants and implicit fields. Link errors and
   implicit-declaration warnings are contract gaps, not noise.

3. **Classify each name into one of four buckets.**

   | Bucket | Action |
   |---|---|
   | Direct libc equivalent | Map to the POSIX call; keep the same name and arity. |
   | Needs state or context emulation | Wrap the POSIX mechanism inside the existing name; do not change callers. |
   | Needs a different mechanism (error channel, handle lifetime, ownership) | Reproduce the observable contract, not the source-platform structure. |
   | Build/framework-only | Leave to the build layer; do not reimplement. |

4. **Recover implicit assumptions.**
   Shared code sometimes assumes platform-specific field names, typedefs or macros
   that the source-platform header provided. Scan shared code for identifiers that
   only exist on the source platform. If the shared code is not going to change,
   the target platform header must supply those names.

5. **Restore aliases at the boundary, gated by build detection.**
   When a name exists only because the build system detected a feature, restore it
   conditionally on that feature macro. Unconditional aliases break on other
   platforms and can silently disagree with the build's detection result.

6. **Keep the target header thin.**
   The source-platform header is usually a compatibility shim (emulated behavior,
   replaced types). The target header should be the opposite: direct mappings plus
   the aliases shared code needs. Do not copy the shim's struct definitions.

7. **Verify by build, link and behavior.**
   A successful configure is not success. The layer must link with no unresolved
   boundary symbols, and the behavior probes for the affected layer must pass.

## Rules

- Shared headers and callers are read-only unless the task explicitly allows
  contract changes; adapt at the platform boundary.
- Prefer the direct POSIX call when its semantics match. Emulate only the deltas.
- Never satisfy a name by changing the caller to a different name; that moves the
  port into unrelated code and breaks cross-position consistency.
- Every restored field alias or macro must have a single, documented selection rule.

## Pitfalls observed in successful migrations

- **Missing symbol discovered only at link time.** The layer compiles but the archive
  does not link. Inventory before writing.
- **Copying the source-platform shim wholesale.** It brings replaced types, error
  translation and path conventions that are wrong on the target.
- **Duplicating a name already implemented for non-source platforms.** Check the
  common/shared layer first.
- **Restoring an alias without its feature macro.** Works on the build machine,
  breaks on a different libc or detection result.
- **Fixing the caller instead of the boundary.** Produces many small edits and
  inconsistent behavior across call sites.
- **Treating a clean configure as success.** Removed directories can configure fine
  and fail only at link or at runtime.

## Verification strategy

- Symbol inventory: declared boundary names vs defined names.
- Clean configure and build, with warnings examined (implicit declarations).
- Link the final artifact, not just compile objects.
- Behavior probes per bucket (direct mapping, emulated state, error channel).
- Check that the new layer contains no source-platform headers or calling
  conventions.

## Boundary

This procedure assumes the shared contract is visible. If the contract exists only
in the removed implementation, recover it from callers and the source-platform
implementation, and record the uncertainty. It does not cover build-system surgery
(see `T5`) or layer-specific semantics (see `T2`–`T4`).