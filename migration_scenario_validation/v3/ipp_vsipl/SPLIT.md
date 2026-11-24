# IPP → VSIPL V3 split

```text
library sources:
  s1_radar_correlation    radar FFT correlation
  s2_spectral_gate        real-FFT spectral gate
  s3_channelizer          streaming channelizer

held out:
  h1_power_spectrum      One-frame real power spectrum
  h2_sonar_lag           Passive-sonar complex lag profile
  h3_stream_lag          Streaming complex lag profile
  h4_header_spectral     Header-only real spectral probe
  h5_burst_acquirer      Streaming burst acquirer with NCO, decimating FIR and lag profiles
  h6_header_stream       Header-only streaming correlation ABI
  h7_header_only         Header-only streaming burst acquirer
  h8_header_corr         Header-only correlation ABI
  h9_header_spectral_gate Header-only spectral gate
  h10_header_corr2       Header-only correlation ABI (replicate)
  h11_header_burst2      Header-only burst acquirer (replicate)
  h12_windowed_peak      Header-only Hann-windowed spectral peak
  h13_spectral_centroid  Windowed spectral centroid

Rules:

1. A library source never appears as a held-out task.
2. A held-out repository never appears in `history/spec.yaml`.
3. `src/` is the IPP before state; `gold/` is the completed VSIPL after state.
4. `gold/` is compiled and tested before history extraction.
5. Component cards are produced by extraction and review, never written by hand.
6. The library is frozen (`library_lock.json`) before task construction.
  h14_norm_corr         Normalized real lag correlation
  h15_corr2d            Two-dimensional complex range-profile correlation
  h16_stream_mix_fir    Streaming NCO mixer with decimation and block report
  h17_cross_coherence   Cross-spectrum phase and coherence
  h18_iq_metrics        IQ gain, phase imbalance and block energy
  h19_overlap_gate      Windowed spectral gate with per-bin flags
  h20_mc_fir            Multi-channel FIR with shared taps