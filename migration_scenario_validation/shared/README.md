# Shared migration-benchmark infrastructure

Three scenarios use this package:

| Scenario | Source | Target |
|---|---|---|
| IPP → VSIPL | Intel IPP C/C++ | VSIPL / jvsip |
| Windows → Kylin | Windows/MSVC C++ | Kylin V10, GCC/CMake |
| CUDA → Ascend | CUDA / Triton / PyTorch spec | Ascend C / CANN |

## What is shared

| Piece | File | Used by |
|---|---|---|
| Task schema | [`schema/task.schema.json`](schema/task.schema.json) | all |
| Task model + command expansion | [`harness/taskmodel.py`](harness/taskmodel.py) | all |
| Unified runner | [`harness/runner.py`](harness/runner.py) | scenarios A/B; IPP opt-in |
| API-removal gate | [`harness/api_removal.py`](harness/api_removal.py) | scenarios A/B; IPP has its own equivalent |
| Case container | [`harness/caseio.py`](harness/caseio.py) | scenarios A/B |
| Judge-result checker | [`harness/check_result.py`](harness/check_result.py) | CUDA → Ascend (MKBench `result.json`) |
| TLS probe | [`harness/tls_probe.sh`](harness/tls_probe.sh) | Windows → Kylin (curl) |
| nginx smoke | [`harness/nginx_smoke.sh`](harness/nginx_smoke.sh) | Windows → Kylin (nginx) |
| Remote runner | [`harness/run_remote.py`](harness/run_remote.py) | CUDA → Ascend |
| Static validator | [`harness/verify.py`](harness/verify.py) | all |
| Task factories | [`../tools/`](../tools/) | all |
| Slate/report generator | [`../tools/make_slate.py`](../tools/make_slate.py) | all |

## Common `task.yaml` contract

```yaml
task_id: l2_libarchive_disk
scenario: windows_to_kylin
level: L2
source: {repo: ..., commit: ..., license: ...}
target: {os: kylin-v10-sp3, arch: x86_64, toolchain: gcc-13}
layout: repo          # repo = full pinned snapshot; slice = selected files
spec: |
  ...
build:
  mode: command       # none = the judge does the building
  command: "cmake -S . -B {build} && cmake --build {build} -j"
  artifact: "{build}/libfoo.a"
hidden_tests:
  command: "python3 harness/run_hidden.py --golden {golden}"
regression_tests:       # optional: existing suites that must stay green
  command: "cd {build}/bin && ./testrunner -ignore {work}/cppignore.lnx FileTest"
gates:
  build: ...
  api_removal:
    source_dirs: ["Foundation/src/Thread_POSIX.cpp"]  # default "."
    symbol_regex: "^(__imp_|CreateFile|WaitForSingleObject)"
    source_regex: "windows\\.h|__declspec|_MSC_VER"
    exclude_globs: ["**/*_WIN32*", "**/win32/**"]
    expect_fail: false  # true = negative control
  behavior: ...
```

Placeholders: `{root}`, `{work}`, `{build}`, `{golden}`.  Commands run with
`cwd={work}`; the runner exports `TASK_ROOT`, `WORK_DIR`, `BUILD_DIR`,
`GOLDEN_DIR`.

### Layouts

- `layout: repo` — `prepare.sh` extracts the full pinned commit into `work/`.
  Used by every Scenario A/B task; the upstream build system and test binaries
  must be present.
- `layout: slice` — only `source_files`, `reference_files`, `spec_files`,
  `test_files` are copied into `work/<group>/`.  Gold is never copied.


### API-removal gate

`shared/harness/api_removal.py` scans:

1. **symbols** in build artifacts with `nm` / `objdump` (`symbol_regex`);
2. **sources** under `source_dirs` (`source_regex`), optionally skipping
   `exclude_globs` (fnmatch on relative path or basename);
3. a negative control when `expect_fail: true`: the gate passes only when a
   removed-API hit *is* found.  This is used by
   `v3/windows_to_kylin/tasks/negative_win32_eventlog`, where the correct answer is
   a non-portability report rather than a silent stub.

`source_dirs` exists because real upstream trees legitimately contain
`_MSC_VER`/`__declspec` branches and bundled Windows code; scanning the whole
snapshot produces false positives.  Each task names exactly the files the agent
must recreate.

### Judge-result checker

`shared/harness/check_result.py` reads a flat or nested JSON result and accepts
flags such as:

```bash
python3 shared/harness/check_result.py result.json \
  --require-compiled --require-correct --forbid-cheating
```

It is used where the upstream evaluator (MultiKernelBench) writes a verdict
file instead of returning a useful exit code.  It does not replace the
evaluator; it only rejects missing/negative verdicts.

## Reuse in the existing IPP tasks

The 20 IPP task packages keep their task-specific `run_hidden.py` (it passes
`-DVSIPL_ROOT` and parses the IPP case format).  Their
`harness/check_api_removal.sh` is a standalone `sh` implementation of the IPP
symbol check; it has **not** been refactored to call
`shared/harness/api_removal.py`.  Doing so is mechanical but would change a
working, already-reviewed package, so it is left as an explicit follow-up.

## Design rules

1. **The task owns the source.**  The runner never rewrites source; it only
   runs commands declared in `task.yaml`.
2. **Gold is evaluator-only.**  `prepare.sh` removes target-platform files from
   the agent-visible `work/`; the same files stay in `gold/` or in the upstream
   commit for the evaluator.
3. **No fake results.**  If the target hardware/toolchain is absent, the runner
   reports `skipped`, not `pass`.
4. **Recipes are reproducible.**  Every package records repo, commit, license
   and the exact files removed; `prepare.sh` can rebuild the snapshot.