# Migration example: s1_radar_correlation

- Capability: `radar/fft-correlation`
- Source: synthetic://radar-correlation-v1 @ `synthetic-radar-correlation-v1`
- License: synthetic
- Removed on the target: 

## Layout

`repo/` is the migration workspace in the project's real source layout.
It contains both sides of the completed migration, so local `#include`
directives resolve exactly as they do upstream.  `example.json` records
which files play which role:

- **before** — source-platform implementation and its private headers:
  - `src/plan_ipp.c`
  - `src/matched_filter_ipp.c`
  - `src/correlate_ipp.c`
  - `src/profile_ipp.c`
  - `src/radar_pipeline_internal.h`
  - `include/radar_pipeline.h`
  - `CMakeLists.txt`
- **after** — completed target-platform implementation:
  - `plan_vsipl.c`
  - `matched_filter_vsipl.c`
  - `correlate_vsipl.c`
  - `profile_vsipl.c`
- **context** — shared headers, callers and contract files
  (0 files listed in `example.json`).
- **tests** — tests that exercise the layer
  (1 files listed in `example.json`).

The migration is complete.  The after files are the answer to the before
files; context and tests show the surrounding contract.

## Task spec

(no spec recorded)
