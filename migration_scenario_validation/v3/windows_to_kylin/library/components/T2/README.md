# T2 — File abstraction layer port

- Kind: transformation
- Capability: `file-system/io`
- Derived from: `l2_libarchive_read_disk` / `l2_libarchive_write_disk`
  (disk traversal and restore gold) and `l2_libuv_fs`
  (open/stat/realpath/directory/readlink gold)
- Applies to: projects with a shared file-abstraction header and a missing POSIX
  implementation
- Confidence: high for the operation families; medium for filesystem-specific
  corners

## When to use

The missing layer owns file descriptors, metadata, directory iteration, path
canonicalisation, timestamps, truncation or file mapping. The shared header names the
operations; the Windows implementation shows the expected behavior.

## Procedure

1. **Enumerate operation families from the header and callers**, not from the
   Windows source file order:
   open/close, sequential read/write, positioned read/write, metadata
   (`stat`/`lstat`/`fstat`), mutation (delete/rename/mkdir/rmdir/chmod/access),
   directory iteration, symlinks (`symlink`/`readlink`), timestamps, truncate/fsync,
   mapping.
2. **For each family, decide direct vs adapted.**
   - Direct libc when semantics match (`open`, `read`, `write`, `unlink`, `stat`,
     `mkdir`, `opendir`).
   - Adapted when the Windows contract includes retries, sharing modes, wide paths
     or a replaced metadata struct. Reproduce only the observable part; drop the
     Windows mechanism.
3. **Preserve the error channel.**
   POSIX calls set `errno`; the port should not translate error codes or overwrite
   `errno` with a library error. Callers inspect `errno` directly.
4. **Keep types and units native.**
   Sizes and offsets are 64-bit at the boundary; metadata is the native `struct
   stat`; timestamps use the native `timeval`/`timespec` split. Do not create a
   project-owned stat struct on POSIX.
5. **Keep paths as byte strings.**
   No UTF-16 widening, drive letters, separator rewriting or case folding. The
   shared path layer is responsible for any normalization.
6. **Distinguish metadata semantics.**
   `lstat` must not follow the final symlink; `stat` and `fstat` do. A non-directory
   path component is `ENOTDIR`; a missing path is `ENOENT`. Windows often collapses
   these; the POSIX behavior is part of the contract.
7. **Handle partial I/O and interruptions deliberately.**
   A read returns the count available. A write helper whose contract is to
   write the whole buffer loops over short writes, advances the offset after
   each one, and returns the total. Retry `EINTR` in restartable calls; do not
   treat it as a hard error.
8. **Verify behavior, not just compilation.**
   Create/append, truncate/extend, stat on files/directories/symlinks/missing paths,
   directory listing, timestamp update, and canonicalisation of existing vs
   non-existing paths.

## Semantic deltas to expect

| Area | Source platform | Target platform |
|---|---|---|
| Paths | UTF-16, drive letters, both separators | byte strings, `/` |
| Open sharing | share modes, retry loops | advisory; no share modes |
| Metadata | project struct, separate time fields | native `struct stat`, `st_mtim`-style fields |
| Rename | replace semantics differ across APIs | `rename` is atomic in-directory, `EXDEV` across devices |
| Directory iteration | handle-based snapshot | live directory stream; entry lifetime is call-scoped |
| Symlinks | privileges and reparse points | normal file system object |
| Time precision | 100 ns file times | `timeval`/`timespec`, filesystem-dependent |
| Missing path | often `ENOENT` for any component | `ENOTDIR` when a component is a file |

## Pitfalls observed in successful migrations

- Translating Windows error codes into `errno` on a platform that already sets it.
- Replacing `struct stat` or defining a parallel metadata type.
- Following symlinks in the non-following metadata call.
- Writing a path-normalisation fallback that corrupts valid byte paths.
- Using buffered stdio in a descriptor-based layer, breaking fsync, locking or
  truncation assumptions.
- Forgetting that readlink does not NUL-terminate and reports truncation via length.
- Mixing path-based and descriptor-based time updates without checking which the
  caller needs.
- Ignoring the feature detection that selects nanosecond field names.

## Verification strategy

- File buffer behavior: create, append, multi-write, commit; failed creation must
  not damage an existing sibling.
- Partial I/O: a short write is completed by the loop; an interrupted write is
  retried rather than reported as failure.
- Truncate/extend across the 2 GB boundary and observe the reported size.
- Metadata matrix: directory, regular file, symlink, missing path, file used as a
  directory component.
- Directory iteration returns usable entries and terminates.
- Canonicalisation succeeds for existing paths and fails for non-existing ones.
- Timestamps update through both path and descriptor entry points.
- Mapping: read-only content is correct; unmap succeeds.

## Boundary

Covers local POSIX file systems and the operation families above. It does not cover
asynchronous I/O, thread pools, network file systems, Windows reparse points, ACLs or
file-change notification. Those need their own components if a task requires them.