# IPP → VSIPL V3 — self-built library sources

This directory contains three **self-built, multi-file migration projects**
used only as library sources. They are not copies of the V1 task packages.

Each project is a complete small repository:

```text
tasks/<source>/
  include/          public contract
  src/              IPP implementation (before)
  gold/             VSIPL implementation (after)
  test/             public smoke test
  harness/          hidden evaluation test
  CMakeLists.txt
  task.yaml
  provenance.json
```

The three projects deliberately cover different migration problems:

| Source | Domain | Main migration surface |
|---|---|---|
| `s1_radar_correlation` | radar | complex FFT plan, zero-padded linear correlation, conjugate matched filter, inverse scaling, split/interleaved complex layout |
| `s2_spectral_gate` | spectral analysis | real FFT half-spectrum, IPP CCS packing vs natural complex bins, Hann window, magnitude/noise gate |
| `s3_channelizer` | communications | streaming NCO phase, decimating complex FIR, history/tap order, block-size invariance |

These are synthetic projects, not upstream repositories. The provenance is
therefore `synthetic://...` and `source_kind: synthetic`. Components extracted
from them must still be derived from the real `src -> gold` diff; no component
card is written by hand.

## Build and verify a gold implementation

```bash
cd tasks/s1_radar_correlation
cmake -S . -B build-gold -DUSE_GOLD=ON \
  -DVSIPL_ROOT=/home/luoyexx/.local/opt/jvsip \
  -DBUILD_HIDDEN_TESTS=ON
cmake --build build-gold -j2
./build-gold/public_test
./build-gold/hidden_test
```

The same pattern applies to `s2_spectral_gate` and `s3_channelizer`.

## History corpus

```bash
./tasks/s1_radar_correlation/prepare.sh
./tasks/s2_spectral_gate/prepare.sh
./tasks/s3_channelizer/prepare.sh

python3 tools/build_history_corpus.py \
  --spec v3/ipp_vsipl/history/spec.yaml --force
```

`history/spec.yaml` lists exactly these three repositories as
`library_source_repos`. No held-out repository is present in this phase.

## What the components are expected to expose

- `s1`: plan ownership and scaling, convolution/correlation lag order,
  conjugate replica construction, zero-padding to avoid circular alias.
- `s2`: real FFT output layout, CCS deinterleave, half-spectrum boundary bins,
  window/normalization, magnitude floor.
- `s3`: streaming state continuity, NCO phase wrap, decimation/history
  alignment, tap order, split complex layout.

These are coverage targets, not pre-written rules. A target only becomes a
component if the extracted transformation is supported by the actual diff and
passes review.
## Extracted library

The current library is the reviewed extraction output, not a hand-written card set:

```text
library -> library_generated/
manifest.json
library_lock.json
components/
  real-to-complex-fft-plan-and-bin-adapter-for-a-51087706
  split-complex-fft-matched-filter-correlation-layer-d152355a
  streaming-complex-nco-mix-and-decimate-layer-rebuilt-8b74d63b
```

All three components have `review_verdict: publish` in `library_lock.json`.
The gold hidden tests pass for all three sources. The first extraction attempt
used Node 26 and was archived under `history/runs_failed_node26_20261123_2145/`;
the successful run used Node 24.9.0.

## Correct incremental order

Do not run all examples as one batch. The supported order is one source at a time:

```text
freeze spec for one source
  -> build + public + hidden
  -> extract that source
  -> review that component
  -> rework if the verdict is rework
  -> finalize/publish that component
  -> verify the registry hash
  -> remove the run's temp/build directories
  -> next source
```

A new component is appended; an existing component ID/hash is never rewritten.
If a stage fails, stop before the next source, fix the environment or the
contract, archive only the failure reason, and remove the failed run directory
once it is no longer needed.
