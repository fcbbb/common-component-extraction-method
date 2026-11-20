# Migration Benchmark 修复后 Direct 基线结果与分析

生成时间：2026-11-20 CST  
模型：`DeepSeek-V4.1-Flash-1017`  
条件：`baseline_direct`，DSH profile `component-method`，每题 1 次  
范围：`ipp_to_vsipl`、`windows_to_kylin` 两个迁移场景的 direct 基线

> 说明：本报告只包含 direct。修复后数据集的 origin 记录已清除，等待用 target-aware system prompt 和固定参数重跑；本文不把旧 origin 或新 origin 诊断结果作为正式基线。

## 1. 实验设置

```text
agent 后端        DSH 0.2.2-rc.1 / Node 24.9.0
agent profile     component-method
context_window    262144
max_output_tokens 32768
runs per task     1
judge 顺序        build -> hidden tests -> api_removal -> target_api
```

target API gate 是本轮新增的硬约束：agent 必须实际使用目标 API，单纯实现 portable fallback 不再能通过。

统计口径：

```text
status 来自 attempt.json
calls 来自 agent_model_calls
seconds 来自 duration_s
cacheRead / input / output 来自 agent/dsh_events.jsonl 的 step_end.usage
cache hit = cacheReadTokens / (inputTokens + cacheReadTokens)
```

## 2. 总览

| 场景 | label | pass | fail | error | calls | 总耗时 | inputTokens | cacheReadTokens | outputTokens | cache hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| IPP → VSIPL | `new_ipp_baseline_full` | 20 | 0 | 0 | 509 | 3613.9s | 7,670,421 | 17,872,000 | 462,160 | 69.97% |
| Windows → 麒麟 | `new_kylin_baseline_full` | 13 | 7 | 0 | 1443 | 15846.4s | 23,859,119 | 107,448,960 | 1,435,647 | 81.83% |

## 3. IPP → VSIPL direct

### 3.1 结果

```text
PASS=20 FAIL=0 ERROR=0
calls=509
seconds=3613.9
cache hit=69.97%
```

| task | level | status | agent | build | tests | api | target API | calls | seconds | cacheRead | cache hit |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|
| `l1_aubio_dct` | L1 | pass | Submitted | ok | pass | pass | pass | 26 | 189.0 | 642,304 | 67.0% |
| `l1_conv_corr` | L1 | pass | Submitted | ok | pass | pass | pass | 25 | 207.2 | 596,736 | 66.5% |
| `l1_juce_fft` | L1 | pass | Submitted | ok | pass | pass | pass | 34 | 236.8 | 1,393,152 | 73.0% |
| `l1_steamaudio_fft` | L1 | pass | Submitted | ok | pass | pass | pass | 25 | 203.2 | 708,608 | 67.0% |
| `l1_vec_db_mag` | L1 | pass | Submitted | ok | pass | pass | pass | 16 | 129.3 | 254,592 | 48.1% |
| `l1_window_gen` | L1 | pass | Submitted | ok | pass | pass | pass | 21 | 144.2 | 888,320 | 61.8% |
| `l2_aubio_fft` | L2 | pass | Submitted | ok | pass | pass | pass | 29 | 186.9 | 802,560 | 71.1% |
| `l2_cfar_detector` | L2 | pass | Submitted | ok | pass | pass | pass | 18 | 114.1 | 391,168 | 60.4% |
| `l2_cil_fbp` | L2 | pass | Submitted | ok | pass | pass | pass | 30 | 225.8 | 1,792,768 | 74.3% |
| `l2_dot_norm_stats` | L2 | pass | Submitted | ok | pass | pass | pass | 19 | 156.2 | 228,864 | 50.9% |
| `l2_fdfir_overlap_save` | L2 | pass | Submitted | ok | pass | pass | unverified | 15 | 165.5 | 174,720 | 52.5% |
| `l2_r8brain_fft` | L2 | pass | Submitted | ok | pass | pass | pass | 37 | 199.9 | 1,672,832 | 79.8% |
| `l2_rubberband_fft` | L2 | pass | Submitted | ok | pass | pass | pass | 23 | 243.3 | 997,888 | 61.0% |
| `l2_saf_stft` | L2 | pass | Submitted | ok | pass | pass | pass | 34 | 238.7 | 2,496,128 | 77.4% |
| `l2_tdfir_bank` | L2 | pass | Submitted | ok | pass | pass | pass | 27 | 155.9 | 614,400 | 66.0% |
| `l3_audio_resampler` | L3 | pass | Submitted | ok | pass | pass | pass | 47 | 285.7 | 2,080,896 | 81.1% |
| `l3_comms_demod_frontend` | L3 | pass | Submitted | ok | pass | pass | pass | 23 | 195.2 | 479,488 | 58.4% |
| `l3_iir_eq_negative` | L3 | pass | Submitted | ok | pass | pass | skipped | 6 | 47.0 | 12,160 | 31.8% |
| `l3_radar_pulse_compression` | L3 | pass | Submitted | ok | pass | pass | pass | 25 | 135.7 | 696,960 | 65.0% |
| `l3_spectrum_sensing` | L3 | pass | Submitted | ok | pass | pass | pass | 29 | 154.3 | 947,456 | 68.1% |

### 3.2 分析

- 20/20 通过，direct 没有观察到 target bypass。
- 18 个任务 `target_api=pass`，确认有 `vsip_*` 调用或符号。
- `l3_iir_eq_negative` 是 `fit: C`：VSIPL 没有 IIR primitive，任务本身要求手写实现，因此 target gate 跳过。
- `l2_fdfir_overlap_save` 从已跑过的 flow 结果复制，canonical workspace 缺失，未重新完整判分；其 `workspace.diff` 中存在 `vsip_*` 调用，静态检查通过。
- 没有行为测试失败或 API removal 失败。

## 4. Windows → 麒麟 direct

### 4.1 结果

```text
PASS=13 FAIL=7 ERROR=0
calls=1443
seconds=15846.4
cache hit=81.83%
```

| task | level | status | agent | build | tests | api | target API | calls | seconds | cacheRead | cache hit |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|
| `l1_poco_file` | L1 | fail | Submitted | ok | fail | skipped | skipped | 53 | 634.2 | 2,635,392 | 83.9% |
| `l1_poco_path` | L1 | pass | Submitted | ok | pass | pass | pass | 51 | 604.3 | 2,041,088 | 82.7% |
| `l1_poco_rwlock_semaphore` | L1 | pass | Submitted | ok | pass | pass | pass | 43 | 688.1 | 1,722,112 | 78.5% |
| `l1_poco_shared_library` | L1 | pass | Submitted | ok | pass | pass | pass | 40 | 595.4 | 1,480,064 | 76.4% |
| `l1_poco_thread` | L1 | pass | Submitted | ok | pass | pass | pass | 55 | 778.8 | 4,200,832 | 83.8% |
| `l2_curl_tls` | L2 | pass | LimitsExceeded | ok | pass | pass | pass | 150 | 881.9 | 13,299,200 | 84.6% |
| `l2_libarchive_read_disk` | L2 | pass | LimitsExceeded | ok | pass | pass | pass | 150 | 940.5 | 13,744,128 | 84.1% |
| `l2_libarchive_write_disk` | L2 | fail | AgentProcessError | fail | skipped | skipped | skipped | 22 | 237.4 | 666,880 | 61.8% |
| `l2_libgit2_file` | L2 | fail | Submitted | ok | fail | skipped | skipped | 60 | 423.8 | 3,481,728 | 85.2% |
| `l2_libgit2_process` | L2 | fail | Submitted | ok | fail | skipped | skipped | 55 | 2795.1 | 3,035,392 | 79.4% |
| `l2_libuv_fs` | L2 | pass | Submitted | ok | pass | pass | pass | 69 | 418.4 | 5,731,072 | 80.6% |
| `l2_libuv_process` | L2 | pass | Submitted | ok | pass | pass | pass | 52 | 384.8 | 3,749,120 | 82.1% |
| `l2_libuv_thread` | L2 | pass | Submitted | ok | pass | pass | unverified | 47 | 569.4 | 2,728,832 | 80.8% |
| `l2_nginx_files` | L2 | pass | Submitted | ok | pass | pass | pass | 45 | 283.0 | 2,076,160 | 80.7% |
| `l2_opencv_highgui` | L2 | pass | LimitsExceeded | ok | pass | pass | pass | 150 | 2484.4 | 13,237,888 | 83.3% |
| `l3_curl_build` | L3 | pass | Submitted | ok | pass | pass | pass | 80 | 795.8 | 6,912,000 | 81.2% |
| `l3_libgit2_full` | L3 | fail | Submitted | ok | pass | fail | skipped | 78 | 619.8 | 7,098,240 | 81.2% |
| `l3_nginx_full` | L3 | fail | AgentProcessError | fail | skipped | skipped | skipped | 83 | 442.4 | 5,616,512 | 72.4% |
| `l3_poco_foundation_full` | L3 | fail | LimitsExceeded | ok | fail | skipped | skipped | 150 | 1218.8 | 13,895,808 | 82.9% |
| `negative_win32_eventlog` | L3 | pass | Submitted | skipped | pass | pass | skipped | 10 | 50.1 | 96,512 | 44.0% |

### 4.2 失败任务分析

#### `l1_poco_file` — tests fail

```text
build=ok
tests=fail
target_api=skipped（未执行到 target gate）
```

判分日志中 Foundation `FileTest::testFileAttributes1` 失败：

```text
"fail: file does not exist - must throw exception"
```

说明：文件属性/错误抛出行为没有完全符合目标平台契约；这是行为测试失败，不是 target bypass。

#### `l2_libarchive_write_disk` — build fail / AgentProcessError

```text
build=fail
tests=skipped
target_api=skipped
```

CMake 配置阶段报：

```text
Cannot find source file: archive_write_disk_posix.c
No SOURCES given to target: archive_static/archive
```

说明：目标平台的 `archive_write_disk_posix.c` 没有生成或被错误删除，构建失败。

#### `l2_libgit2_file` — tests fail

```text
build=ok
tests=fail
target_api=skipped
```

判分日志中 `path::core::13_cannot_prettify_a_non_existing_file` 失败：

```text
GIT_ENOTFOUND != git_fs_path_prettify(&p, NON_EXISTING_FILEPATH, NULL)
```

说明：不存在的路径应返回 `GIT_ENOTFOUND`，实际返回了其他结果。

#### `l2_libgit2_process` — tests fail / timeout

```text
build=ok
tests=fail
target_api=skipped
```

这一题在重判时触发 hidden tests 超时（原 direct attempt 也是 tests fail）。说明目标 POSIX process 实现没有在时限内完成上游测试，或测试中存在挂起。

#### `l3_libgit2_full` — API removal fail

```text
build=ok
tests=pass
api_removal=fail
target_api=skipped
```

API removal 命中：

```text
src/util/unix/pthread.h:14  _MSC_VER
```

说明：目标目录中的兼容头仍含 `_MSC_VER`，被 Windows API removal 正则命中。该任务的行为测试通过，但 API gate 失败；这属于任务/正则边界问题，不是 target bypass。

#### `l3_nginx_full` — build fail / AgentProcessError

```text
build=fail
tests=skipped
target_api=skipped
```

构建日志显示：

```text
implicit declaration of function ‘ngx_setproctitle’
implicit declaration of function ‘waitpid’
-Werror=implicit-function-declaration
```

说明：目标 nginx 编译依赖的头文件/原型没有补齐，`-Werror` 将其放大为构建失败。

#### `l3_poco_foundation_full` — tests fail / LimitsExceeded

```text
build=ok
tests=fail
target_api=skipped
```

判分日志显示 ThreadTest 4 个错误：

```text
Poco::SystemException: thread already running
Poco::InvalidAccessException: cannot change stack size of running thread
```

以及 `FileTest::testFileAttributes1` 失败。  
说明：线程生命周期/栈大小状态机以及文件属性错误语义仍有问题；同时 agent 触发 LimitsExceeded，不是 target API 绕过。

### 4.3 target API gate 结论

- 11 个通过任务 `target_api=pass`，未观察到类似旧 IPP origin 的 portable fallback 通过。
- 7 个失败任务在 build/tests 阶段已经失败，未进入 target gate。
- `negative_win32_eventlog` 是 negative control，跳过 target gate。
- `l2_libuv_thread` 是从 flow 复制的成功结果，canonical workspace 缺失，未重新完整判分；其 `workspace.diff` 中有目标平台标记，静态检查通过。

## 5. 缓存命中

| 场景 | inputTokens | cacheReadTokens | outputTokens | cache hit |
|---|---:|---:|---:|---:|
| IPP → VSIPL direct | 7,670,421 | 17,872,000 | 462,160 | 69.97% |
| Windows → 麒麟 direct | 23,859,119 | 107,448,960 | 1,435,647 | 81.83% |

direct 的 cache 来自 DSH step usage 汇总；本报告不包含 origin，原因是修复后数据集的 origin 记录已清除，等待重跑。

## 6. 结论

```text
1. IPP direct: 20/20，target gate 未发现绕过，模型结果可复用。
2. Windows → 麒麟 direct: 13/20，失败集中在行为测试、构建和 API 正则边界，不是 target bypass。
3. direct 不需要重新调用模型；本轮已完成无模型 rejudge。
4. origin 需要后续用 target-aware system prompt + target API gate + 固定配置重跑。
```

## 7. 证据与详细表

```text
reports/bench/new_ipp_baseline_full/report.md
reports/bench/new_ipp_baseline_full/summary.json
reports/bench/new_kylin_baseline_full/report.md
reports/bench/new_kylin_baseline_full/summary.json

../../tmp/new_IPP_to_VSIPL_direct_全量结果.md
../../tmp/new_Windows_to_Kylin_direct_全量结果.md
```
