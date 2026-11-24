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

## Held-out smoke result

`tasks/h1_power_spectrum` is a separate held-out task, not a library source.
It was used once to check both arms on the frozen library.

```text
direct:  h1_direct_v3           PASS 132.0s  calls=23  build=ok tests=pass api=pass
method:  h1_method_retrieval_v2 PASS 138.2s  calls=16  build=ok tests=pass api=pass
         bundle component_count=1
         selected: real-to-complex-fft-plan-and-bin-adapter-for-a-51087706
```

The method arm used the retrieval-only prompt and the prebuilt library:

```bash
--method-prompt config/prompts/method_retrieval_only_system.txt \
--bundle v3/ipp_vsipl/library \
--method-stage-runtime host
```

It did not scan, extract, review, or publish. `h1_power_spectrum` is not in
`history/spec.yaml`; it is only in `slate.yaml` as held-out.

## Held-out task built after h1: h2_sonar_lag

`tasks/h2_sonar_lag` is the first component-sensitive held-out candidate.
It is built around the `split-complex-fft-matched-filter-correlation-layer`
component and is not a library source.

Contract:

```text
y[k] = sum_j x[j] * conj(ref[j-k]),  k = -(nref-1) .. (nref-1)
out[i] = y[i-(nref-1)]
```

The source uses an IPP complex FFT with an unscaled forward and one inverse
`1/nfft` factor.  Hidden checks cover complex conjugation, lag origin,
amplitude, reference-copy isolation, oversized FFT padding, state reuse and
the first-index tie rule.  These are the exact places where the retrieved
component gives guidance that a direct port can miss.

Gold validation:

```text
gold public: PASS
gold hidden: checks=340 failures=0
verify_task: PASS tasks=5
lint_dataset: PASS tasks=64
```

Pairing result:

```text
direct:  h2_direct_v2          PASS 153.2s  calls=28  build=ok tests=pass api=pass
method:  h2_method_retrieval   PASS 151.5s  calls=23  build=ok tests=pass api=pass
         bundle component_count=1
         selected split-complex-fft-matched-filter-correlation-layer
compare: pass / pass / delta -
```

`h2_sonar_lag` is therefore **not** a direct-fail/method-pass example; it is
saturated for this model.  It stays as a validated held-out task, but it does
not count toward the four sensitive examples.

## h3_stream_lag: second held-out candidate

`tasks/h3_stream_lag` adds a stateful streaming contract: a partial frame
must carry across `sc_process` calls, and different call splits must produce
the same concatenated lag profiles.  It was built around the correlation and
streaming components.

Gold validation:

```text
gold public: PASS
gold hidden: checks=459 failures=0
verify_task: PASS
lint_dataset: PASS
```

Pairing result:

```text
direct:  h3_direct            PASS 148.1s  calls=27
method:  h3_method_retrieval  PASS 308.0s  calls=38
         bundle component_count=2
compare: pass / pass / delta -
```

This is also a both-pass task, not a direct-fail/method-pass example.

## h5_burst_acquirer: third held-out candidate

`tasks/h5_burst_acquirer` combines a continuous complex stream, an NCO
mixer, a decimating complex FIR and per-frame lag correlation.  The source
uses high-level IPP calls rather than exposing the arithmetic, while the
gold backend uses explicit VSIPL vector/FFT operations.

Gold validation:

```text
gold public: PASS
gold hidden: checks=21 failures=0
verify_task: PASS
lint_dataset: PASS
```

Pairing result:

```text
direct:  h5_direct            PASS 273.3s  calls=45
method:  h5_method_retrieval  PASS 354.1s  calls=34
         bundle component_count=2
compare: pass / pass / delta -
```

Still a both-pass sample, not a direct-fail/method-pass example.

## h7_header_only: first sensitive held-out sample

`tasks/h7_header_only` is scheme C: the implementation is absent from the
snapshot.  Only the ABI header, public smoke test and internal state layout
are visible; the implementation must be built on VSIPL.

Gold validation:

```text
gold public: PASS
gold hidden: checks=18 failures=0
verify_task: PASS
lint_dataset: PASS
```

Pairing result:

```text
direct:  h7_direct_v3   FAIL 266.4s  calls=51
         failures: split=0/1/2 lag=0, non-power nfft
         target_api: skipped after test failure

method:  h7_method_v4   PASS 270.9s  calls=45
         bundle component_count=2
         tests=pass, target_api=pass

compare: fail / pass / better
```

This is the first **direct fail / method pass** example.  The direct arm
reconstructed the stream and FIR incorrectly under irregular block splits
and accepted a non-power-of-two nfft; the method arm retrieved the
correlation/streaming component cards, respected the lag/normalization and
target-API rules, and passed.

It is registered as a held-out task and counts as a sensitive sample.

## Held-out matrix (final)

| task | result |
|---|---|
| h1_power_spectrum | both pass |
| h2_sonar_lag | both pass |
| h3_stream_lag | both pass |
| h4_header_spectral | both pass |
| h5_burst_acquirer | both pass |
| h6_header_stream | both fail |
| h7_header_only | direct fail / method pass |
| h8_header_corr | direct fail / method pass |
| h9_header_spectral_gate | both fail |
| h10_header_corr2 | direct fail / method pass |
| h11_header_burst2 | direct fail / method pass |
| h12_windowed_peak | direct fail / method pass |
| h13_spectral_centroid | both pass |
| h14_norm_corr | both pass |
| h15_corr2d | both pass |
| h16_stream_mix_fir | both pass |
| h17_cross_coherence | both pass |
| h18_iq_metrics | both pass |
| h19_overlap_gate | both pass |
| h20_mc_fir | both pass |

Totals: 20 held-out, 5 sensitive, 2 both-fail, 13 both-pass.
