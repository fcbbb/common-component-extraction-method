# Migration example: s3_channelizer

- Capability: `communications/channelizer`
- Source: synthetic://channelizer-v1 @ `synthetic-channelizer-v1`
- License: synthetic
- Removed on the target: 

## Layout

`repo/` is the migration workspace in the project's real source layout.
It contains both sides of the completed migration, so local `#include`
directives resolve exactly as they do upstream.  `example.json` records
which files play which role:

- **before** — source-platform implementation and its private headers:
  - `src/state_ipp.c`
  - `src/mixer_ipp.c`
  - `src/fir_ipp.c`
  - `src/stats_ipp.c`
  - `src/channelizer_internal.h`
  - `include/channelizer.h`
  - `CMakeLists.txt`
- **after** — completed target-platform implementation:
  - `state_vsipl.c`
  - `mixer_vsipl.c`
  - `fir_vsipl.c`
  - `stats_vsipl.c`
- **context** — shared headers, callers and contract files
  (0 files listed in `example.json`).
- **tests** — tests that exercise the layer
  (1 files listed in `example.json`).

The migration is complete.  The after files are the answer to the before
files; context and tests show the surrounding contract.

## Task spec

(no spec recorded)
