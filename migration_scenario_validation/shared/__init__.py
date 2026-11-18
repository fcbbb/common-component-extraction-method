"""Shared infrastructure for the migration-scenario benchmarks.

Used by all three scenarios:
  * Intel IPP -> VSIPL
  * Windows C++ -> Kylin
  * NVIDIA/CUDA -> Moore Threads MUSA

The package intentionally has no third-party runtime dependency beyond PyYAML.
"""