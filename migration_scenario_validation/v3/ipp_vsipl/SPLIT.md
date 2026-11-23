# IPP → VSIPL V3 split

```text
library sources:
  s1_radar_correlation    radar FFT correlation
  s2_spectral_gate        real-FFT spectral gate
  s3_channelizer          streaming channelizer

held out:
  (none yet; tasks are built only after the library is frozen)
```

Rules:

1. A library source never appears as a held-out task.
2. A held-out repository never appears in `history/spec.yaml`.
3. `src/` is the IPP before state; `gold/` is the completed VSIPL after state.
4. `gold/` is compiled and tested before history extraction.
5. Component cards are produced by extraction and review, never written by hand.
6. The library is frozen (`library_lock.json`) before task construction.