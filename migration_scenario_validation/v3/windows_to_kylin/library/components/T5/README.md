# T5 — Build discovery after implementation removal

- Kind: transformation
- Capability: `build`
- Derived from: the build entries of `l2_libarchive_read_disk` /
  `l2_libarchive_write_disk` (CMake source selection), `l2_libuv_*`
  (autotools/CMake) and the migration task packages' preparation steps
- Applies to: tasks that remove a platform directory or a file set rather than a
  single source file
- Confidence: medium-high (rule-based; every build system differs)

## When to use

The removed implementation is selected by the build system rather than included
explicitly by a shared source file. Typical signs:

- the task removes a whole directory;
- the build uses a glob or a configure-time check to pick platform sources;
- a clean configure succeeds but the link fails;
- adding files does not change the build result.

## Procedure

1. **Find how platform sources are selected.**
   Read the build entry for the platform branch: glob pattern, explicit list,
   configure test, generated makefile, or a feature macro. The selection rule, not
   the old file list, determines where new files must go.

2. **Match the selection exactly.**
   Recreate the directory and filenames the rule matches. A glob usually requires
   at least one matching source; a directory with headers only may contribute
   nothing. If the rule is conditional on the target platform, confirm the condition
   is the one being built.

3. **Reconfigure from a clean build directory.**
   Globs and configure results are cached at configure time. Adding files to an
   existing build tree often has no effect. Remove the build directory and configure
   again after the layer exists.

4. **Separate build gaps from contract gaps.**
   - No objects compiled: selection rule / directory problem (`T5`).
   - Objects compiled but unresolved symbols: missing contract surface (`T1`).
   - Compile errors in shared code: a boundary alias or type is wrong (`T1`, `T2`).
   - Configure succeeds, build fails early: conditional branch or generated header.

5. **Do not hand-edit generated files.**
   Feature headers and configure outputs are regenerated. If a feature macro is
   wrong, inspect the detection test and the inputs, not the generated file.

6. **Verify the artifact, not the configure log.**
   Build the final library/executable and run the behavior probes for the rebuilt
   layer. A green configure says nothing about whether the removed files are back in
   the build.

## Rules

- Prefer making the existing selection rule find the new files over editing the
  build system.
- If a build edit is unavoidable, change only the platform-source selection, not
  global flags.
- Keep filenames and extensions consistent with the rule; case-sensitive file
  systems expose mismatches that the source platform tolerated.
- Build out-of-tree if the project supports it; stale in-tree objects mask missing
  sources.

## Pitfalls observed in successful migrations

- Empty glob after the directory was removed; configure passes and link fails.
- Stale build directory retaining old object files, hiding a missing source.
- Source list conditioned on the wrong OS or feature flag.
- Generated feature header not regenerated after a detection change.
- Headers placed in the source directory but no translation unit compiled.
- Editing global build flags to “fix” a missing platform branch.
- Assuming an implicit include path is visible to every translation unit.

## Verification strategy

- Clean configure and clean build from an empty build directory.
- Confirm the new sources appear in the build graph (object files or verbose build
  output).
- Final artifact links with no unresolved boundary symbols.
- Run the layer's behavior probes.
- Rebuild once more without cleaning to detect accidental dependence on stale state.

## Boundary

These are general rules; build systems differ (CMake globs, autotools conditionals,
custom configure scripts, generated makefiles). The component tells the agent what to
inspect and which failure shape maps to which cause. It does not prescribe build
commands for a specific project.