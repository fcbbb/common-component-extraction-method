# Migration example: s2_spectral_gate

- Capability: `spectral/real-fft-gate`
- Source: synthetic://spectral-gate-v1 @ `synthetic-spectral-gate-v1`
- License: synthetic
- Removed on the target: 

## Layout

`repo/` is the migration workspace in the project's real source layout.
It contains both sides of the completed migration, so local `#include`
directives resolve exactly as they do upstream.  `example.json` records
which files play which role:

- **before** — source-platform implementation and its private headers:
  - `src/plan_ipp.c`
  - `src/window_ipp.c`
  - `src/gate_ipp.c`
  - `src/report_ipp.c`
  - `src/spectral_gate_internal.h`
  - `include/spectral_gate.h`
  - `CMakeLists.txt`
- **after** — completed target-platform implementation:
  - `plan_vsipl.c`
  - `window_vsipl.c`
  - `gate_vsipl.c`
  - `report_vsipl.c`
- **context** — shared headers, callers and contract files
  (0 files listed in `example.json`).
- **tests** — tests that exercise the layer
  (1 files listed in `example.json`).

The migration is complete.  The after files are the answer to the before
files; context and tests show the surrounding contract.

## Task spec

(no spec recorded)
