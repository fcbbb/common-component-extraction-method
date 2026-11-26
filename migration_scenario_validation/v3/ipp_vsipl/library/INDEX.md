# Transformation library index

Methodology components extracted from completed migrations. They are
project-agnostic: rules, semantic deltas, pitfalls and verification, not
implementations.

## How to use

1. Identify which layer the task must rebuild.
2. Read every component whose `capability` matches that layer.
3. Treat the workspace contract as authoritative; the component only
   supplies the mapping procedure, deltas and pitfalls.

## Components

| ID | Component | Capability | Use when |
|---|---|---|---|
| `real-to-complex-fft-plan-and-bin-adapter-for-a-51087706` | [Real-to-complex FFT plan and bin adapter for a streaming spectral gate](components/real-to-complex-fft-plan-and-bin-adapter-for-a-51087706/README.md) | `other` | You are rebuilding the FFT-plan and forward-transform module of a streaming spectral gate that was written against a status-code FFT libr... |
| `split-complex-fft-matched-filter-correlation-layer-d152355a` | [split-complex FFT matched-filter correlation layer rebuilt on an opaque-plan array-view signal API](components/split-complex-fft-matched-filter-correlation-layer-d152355a/README.md) | `other` | Use this when a matched-filter correlation layer that runs on a vendor signal-processing library driven by a caller-sized transform speci... |
| `streaming-complex-nco-mix-and-decimate-layer-rebuilt-8b74d63b` | [Streaming complex NCO mix-and-decimate layer rebuilt from block vendor kernels onto a view-based vector signal-processing API](components/streaming-complex-nco-mix-and-decimate-layer-rebuilt-8b74d63b/README.md) | `other` | Use this when a streaming complex channelizer layer (complex NCO mix, decimating complex FIR, per-block output report) was written agains... |

## What these components do not contain

- No target-project file list, symbol list or line references.
- No implementation snippets intended for copying.
- No test names or evaluator commands.
- No current-task gold.
