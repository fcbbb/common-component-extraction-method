# Migration Benchmark 基线结果与分析（IPP → VSIPL、Windows → 麒麟）

本文记录两个迁移场景的 **direct 基线**结果和分析。

- 场景：`ipp_to_vsipl`、`windows_to_kylin`
- 条件：`baseline_direct`
- DSH profile：`component-method`
- 模型：`DeepSeek-V4.1-Flash-1017`
- 每任务：1 次运行
- 数据时间：2026-11-18 至 2026-11-19
- 基线不加载组件抽取、组件库、retrieval 或 `component_bundle`；DSH 只提供 Agent 循环和 `controlled_bash`。

> 本文是迁移 benchmark 的基线结果文档，不修改 `docs/final_report_20_tasks.md` 中的 SWE-rebench 结果。

---

## 1. 结果总览

| 场景 | pass | fail | error | skip | 模型调用 | 耗时 | cache hit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| IPP → VSIPL | 20 | 0 | 0 | 0 | 853 | 9362.1s | 59.1% |
| Windows → 麒麟 | 19 | 1 | 0 | 0 | 986 | 14802.2s | 91.0% |

原始证据：

```text
migration_scenario_validation/reports/bench/ipp_baseline_full/
migration_scenario_validation/reports/bench/kylin_baseline_full/
```

---

## 2. IPP → VSIPL

### 2.1 设置

```text
tasks: 20
context_window:
  前 15 题：131072
  后 5 题：262144
model: DeepSeek-V4.1-Flash-1017
profile: component-method
condition: baseline_direct
```

### 2.2 汇总

```text
PASS=20  FAIL=0  ERROR=0  SKIP=0
model_calls=853
total_seconds=9362.1
inputTokens=10411586
cacheReadTokens=15066880
outputTokens=618475
cache hit=59.1%
```

### 2.3 全部任务

| 任务 | 级别 | 状态 | calls | 耗时(s) | inputTokens | cacheReadTokens | outputTokens | cache hit |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| `l1_aubio_dct` | L1 | pass | 19 | 135.4 | 114081 | 296064 | 13696 | 72.2% |
| `l1_conv_corr` | L1 | pass | 95 | 1054.1 | 1287574 | 1293056 | 75364 | 50.1% |
| `l1_juce_fft` | L1 | pass | 35 | 304.8 | 345587 | 459648 | 23372 | 57.1% |
| `l1_steamaudio_fft` | L1 | pass | 120 | 1942.8 | 1519557 | 1767552 | 80361 | 53.8% |
| `l1_vec_db_mag` | L1 | pass | 21 | 134.7 | 141715 | 308736 | 10729 | 68.5% |
| `l1_window_gen` | L1 | pass | 10 | 73.4 | 49913 | 113664 | 9027 | 69.5% |
| `l2_aubio_fft` | L2 | pass | 23 | 218.7 | 225923 | 307968 | 20766 | 57.7% |
| `l2_cfar_detector` | L2 | pass | 25 | 275.7 | 290117 | 312448 | 23072 | 51.9% |
| `l2_cil_fbp` | L2 | pass | 65 | 541.1 | 761937 | 1004032 | 45033 | 56.9% |
| `l2_dot_norm_stats` | L2 | pass | 28 | 261.1 | 272531 | 394880 | 27149 | 59.2% |
| `l2_fdfir_overlap_save` | L2 | pass | 11 | 55.7 | 67889 | 77824 | 5413 | 53.4% |
| `l2_r8brain_fft` | L2 | pass | 140 | 1734.0 | 2043163 | 2029952 | 74451 | 49.8% |
| `l2_rubberband_fft` | L2 | pass | 49 | 559.8 | 665401 | 705152 | 30949 | 51.5% |
| `l2_saf_stft` | L2 | pass | 83 | 893.8 | 1159543 | 1246848 | 52641 | 51.8% |
| `l2_tdfir_bank` | L2 | pass | 18 | 159.7 | 171099 | 219136 | 14383 | 56.2% |
| `l3_audio_resampler` | L3 | pass | 35 | 345.8 | 412851 | 1869568 | 41226 | 81.9% |
| `l3_comms_demod_frontend` | L3 | pass | 19 | 237.9 | 316003 | 840832 | 27655 | 72.7% |
| `l3_iir_eq_negative` | L3 | pass | 7 | 57.9 | 11685 | 33664 | 5512 | 74.2% |
| `l3_radar_pulse_compression` | L3 | pass | 31 | 264.9 | 440976 | 1398016 | 26372 | 76.0% |
| `l3_spectrum_sensing` | L3 | pass | 19 | 110.8 | 114041 | 387840 | 11304 | 77.3% |

### 2.4 观察

- 全部 20 题通过，说明 direct Agent 在 IPP → VSIPL 场景下可以完成这些任务。
- 时间分布很不均匀：`l1_steamaudio_fft` 约 32 分钟、`l2_r8brain_fft` 约 29 分钟、`l1_conv_corr` 约 18 分钟；简单任务只需约 1 分钟。
- 后 5 题在上调上下文后 cache hit 为 77.8%，前 15 题为 53.6%。但前后任务集合不同，不能把差异完全归因于上下文长度。
- direct 基线没有组件复用，主要成本来自反复的“修改 → 编译 → 报错 → 再修改”循环。

---

## 3. Windows → 麒麟

### 3.1 设置

```text
tasks: 20
context_window: 262144
model: DeepSeek-V4.1-Flash-1017
profile: component-method
condition: baseline_direct
```

`l1_poco_thread` 先作为单题预检并通过，随后直接复制到全量结果，不重复调用。  
`l2_curl_tls`、`l2_libarchive_read_disk`、`l3_poco_foundation_full` 使用了修复/重跑结果。

### 3.2 汇总（canonical）

```text
PASS=19  FAIL=1  ERROR=0  SKIP=0
model_calls=986
total_seconds=14802.2
inputTokens=7764080
cacheReadTokens=78259328
outputTokens=984902
cache hit=91.0%
```

这里的 canonical 统计是每个任务选取最有效的一次 attempt。  
包含重跑的实际调用总量为：

```text
calls=1271
cache hit=91.7%
```

### 3.3 全部任务

| 任务 | 级别 | 状态 | agent | build | tests | API | calls | 耗时(s) |
|---|---:|---|---|---|---|---|---:|---:|
| `l1_poco_file` | L1 | pass | Submitted | ok | pass | pass | 39 | 911.6 |
| `l1_poco_path` | L1 | pass | Submitted | ok | pass | pass | 28 | 736.4 |
| `l1_poco_rwlock_semaphore` | L1 | pass | Submitted | ok | pass | pass | 30 | 750.1 |
| `l1_poco_shared_library` | L1 | pass | Submitted | ok | pass | pass | 15 | 670.8 |
| `l1_poco_thread` | L1 | pass | Submitted | ok | pass | pass | 60 | 1381.8 |
| `l2_curl_tls` | L2 | pass | Submitted | ok | pass | pass | 62 | 546.0 |
| `l2_libarchive_read_disk` | L2 | pass | Submitted | ok | pass | pass | 50 | 611.2 |
| `l2_libarchive_write_disk` | L2 | pass | Submitted | ok | pass | pass | 63 | 805.6 |
| `l2_libgit2_file` | L2 | pass | Submitted | ok | pass | pass | 57 | 795.6 |
| `l2_libgit2_process` | L2 | fail | Submitted | ok | pass | fail | 35 | 590.9 |
| `l2_libuv_fs` | L2 | pass | Submitted | ok | pass | pass | 66 | 510.9 |
| `l2_libuv_process` | L2 | pass | Submitted | ok | pass | pass | 59 | 502.6 |
| `l2_libuv_thread` | L2 | pass | Submitted | ok | pass | pass | 24 | 233.8 |
| `l2_nginx_files` | L2 | pass | Submitted | ok | pass | pass | 37 | 264.6 |
| `l2_opencv_highgui` | L2 | pass | Submitted | ok | pass | pass | 69 | 2295.8 |
| `l3_curl_build` | L3 | pass | Submitted | ok | pass | pass | 40 | 451.2 |
| `l3_libgit2_full` | L3 | pass | Submitted | ok | pass | pass | 55 | 723.8 |
| `l3_nginx_full` | L3 | pass | AgentProcessError | ok | pass | pass | 107 | 810.5 |
| `l3_poco_foundation_full` | L3 | pass | AgentProcessError | ok | pass | pass | 84 | 1150.5 |
| `negative_win32_eventlog` | L3 | pass | Submitted | skipped | pass | pass | 6 | 58.5 |

### 3.4 失败和异常

#### `l2_libgit2_process`：API removal gate fail

```text
build=ok
tests=pass
api_removal=fail
```

API gate 在：

```text
src/util/unix/pthread.h:16
```

命中：

```text
_MSC_VER
```

功能测试通过，但源码仍保留 MSVC 条件。正常迁移应删除 Windows/MSVC 分支，只保留 GCC/Unix 分支。

#### `negative_win32_eventlog`：路径修复后 pass

这个任务没有可移植实现。正确行为是：

```text
写 PORTING_NOTES.md
说明 Windows Event Log 没有 Kylin/POSIX 等价物
说明为什么 syslog/journald 不能行为等价替代
不能伪造一个静默丢弃日志的 stub
```

Agent 实际写出了满足要求的内容，但写到了：

```text
/workspace/work/PORTING_NOTES.md
```

hidden test 检查：

```text
/workspace/PORTING_NOTES.md
```

这是 task prompt 的 `work/` 路径映射问题。将同一份文件复制到 workspace 根目录后重新运行 judge：

```text
tests=pass
api_removal=pass
status=pass
```

该修复没有调用大模型。
该任务的 API gate 是 `expect_fail: true`，这里的 pass 表示“按预期检测到 Windows API 残留”，不是“没有 Windows API”。

#### `l3_nginx_full`：判分通过，但 Agent 异常

```text
build/tests/API 全 pass
agent_status=AgentProcessError
```

Agent 最后发出的 `controlled_bash` 参数不是合法 JSON，DSH 报：

```text
MALFORMED_RESPONSE
```

正常应干净提交并结束。当前只能记录为“判分通过、Agent 协议异常”。

#### `l3_poco_foundation_full`：判分通过，但 Agent 异常

第一次 build 失败，缺少 `File_UNIX.cpp`；重跑后：

```text
build/tests/API 全 pass
agent_status=AgentProcessError
```

重跑结束时同样出现 `controlled_bash` 参数 JSON 非法。  
正常应补齐 POSIX 文件、通过 Foundation 测试并干净结束。

---

## 4. build / tests / API removal 的判定语义

`shared/harness/runner.py` 的顺序是：

```text
build
→ hidden tests
→ API removal gate
```

- **build**：在目标 Kylin 镜像中构建；失败后 tests/API 跳过，最终 fail。
- **tests**：运行上游测试或 hidden test；失败后 API 跳过，最终 fail。
- **API removal**：检查构建产物符号和指定源码目录中的 Windows API/宏；普通任务必须 pass，负向任务用 `expect_fail`。

一般任务需要所有适用 gate 都 pass 才最终 pass。  
`negative_win32_eventlog` 是特殊情况：API gate 预期失败，hidden test 必须 pass。

---

## 5. `AgentProcessError` 的含义

`AgentProcessError` 不是判分 gate，而是 DSH Agent 层异常：

```text
工具调用参数不是合法 JSON
tool_result 没有匹配的 tool_call
Agent 循环提前结束
```

当前代码最终 `status` 优先看 judge：

```text
如果 build/tests/API 都 pass
即使 agent_status=AgentProcessError
attempt 仍可能记录为 pass
```

因此 `l3_nginx_full` 和 `l3_poco_foundation_full` 的 pass 应理解为：

```text
判分通过，但不是干净的 Submitted 运行
```

不应和正常 Agent 完成完全等同。

---

## 6. 缓存与成本分析

### IPP → VSIPL

```text
inputTokens=10411586
cacheReadTokens=15066880
cache hit=59.1%
```

### Windows → 麒麟

```text
inputTokens=7764080
cacheReadTokens=78259328
cache hit=91.0%
```

观察：

- Kylin 任务上下文整体较长，cache hit 明显高于 IPP 的第一阶段。
- IPP 前后阶段的上下文长度不同，后 5 题 cache hit 更高，但任务集合不同，不能直接做因果判断。
- 如需确认上下文长度的影响，应固定同一任务、同一模型、同一预算，只改变 `context_window`，重复多次做 A/B。
- direct 基线没有组件复用，调用次数和上下文长度是主要成本来源。

---

## 7. 结论

1. `IPP → VSIPL` direct 基线 20/20 通过。
2. `Windows → 麒麟` direct 基线 19/20 通过；唯一剩余失败是 `l2_libgit2_process` 的 API 源码残留。`negative_win32_eventlog` 修复路径后已 pass。
3. 两个 Kylin pass 带有 `AgentProcessError`，判分通过但 Agent 会话不干净，需要单独标记。
4. 当前结果可作为后续组件方法 A/B 的基线，但不应把 `AgentProcessError` 的 pass 当作完全可靠的 Agent 成功样本。
5. 下一步若要得到更干净的 Kylin 全量数据，应重跑 `l3_nginx_full` 和 `l3_poco_foundation_full`，并调查 DSH 工具调用 JSON 的生成/解析问题。

---

## 8. 产物

```text
migration_scenario_validation/reports/bench/ipp_baseline_full/summary.json
migration_scenario_validation/reports/bench/ipp_baseline_full/report.md
migration_scenario_validation/reports/bench/kylin_baseline_full/summary.json
migration_scenario_validation/reports/bench/kylin_baseline_full/report.md
```

对应分析文档：

```text
docs/migration_benchmark_baseline_results.md
```

---

## 8. Origin one-shot baseline

项目新增第三种基线：

```text
arm = origin
condition = origin_one_shot
```

它不启动 DSH，也不是 Agent。流程是：

```text
prepare task
→ 收集任务 spec、文件树、预算内源码
→ 直接调用一次 /chat/completions
→ 解析返回的文件映射
→ 写入 workspace
→ 交给同一个 build/tests/API judge
```

没有工具调用、没有构建反馈、没有重试、没有多轮修复。

### 8.1 入口

```bash
./run-origin.sh --scenario ipp_to_vsipl --only l1_aubio_dct \
  --runs 1 --model DeepSeek-V4.1-Flash-1017 --label origin_aubio
```

统一入口：

```text
migration_scenario_validation/run-origin.sh
migration_scenario_validation/tools/origin_trial.py
migration_scenario_validation/tools/bench.py --arm origin
```

### 8.2 单题 smoke 结果

任务：

```text
scenario: ipp_to_vsipl
task: l1_aubio_dct
label: origin_aubio_real1
```

结果：

```text
status: pass
agent_status: OneShot
agent_model_calls: 1
agent_tokens: input=5,331 output=15,303
origin.context_chars: 15,248
origin.context_files: 6
build/tests/API: ok/pass/pass
duration: 95.1s
```

模型返回的文件操作：

```text
src/dct_vsipl.c   写入
src/dct_ipp.c     删除
```

这说明 origin 路径已经能完成：

```text
上下文打包
→ 单次模型调用
→ 文件解析与应用
→ judge
```

当前只做了单题 smoke，没有做 20 题全量 origin 结果，因此不能把单题通过当成该方法在全部任务上的成功率。

### 8.3 与其他基线的关系

```text
origin
  = plain LLM / one-shot
  = 只有模型生成能力，没有环境闭环

default
  = minimal agent
  = 有 controlled_bash 和多轮构建/测试反馈

method
  = component-method agent
  = 在 default 基础上增加组件抽取、review、retrieval 和 bundle
```

因此三者分别回答：

```text
origin: 一次生成能写出什么
default: 有最小工具闭环时能做到什么
method: 有组件复用和工具闭环时能做到什么
```

### 8.4 限制

```text
origin 只支持 ipp_to_vsipl 和 windows_to_kylin
cuda_to_musa 需要远端执行面，当前不作为 origin 支持范围
一次性模型响应的 JSON/文件路径必须可解析
长仓库可能因上下文预算丢文件
```

结果目录：

```text
migration_scenario_validation/reports/bench/origin_ipp_full/l1_aubio_dct/run1/
```

### 8.5 IPP origin 全量结果

后续已对 `ipp_to_vsipl` 的 20 题运行 origin 全量；`l1_aubio_dct` 复用单题结果，剩余 19 题通过单次上下文调用完成，4 个截断 error 用 65536 输出预算修复重跑。

canonical 结果：

```text
PASS=12  FAIL=8  ERROR=0  SKIP=0
model_calls=20
inputTokens=170,614
outputTokens=498,670
totalTokens=669,284
totalSeconds=2805.0
```

8 个失败全部停在 build，主要是 jvsip API 签名/执行函数名错误；没有进入 hidden tests/API gate。

完整逐题结果和分析见：

```text
../tmp/IPP_to_VSIPL_origin_全量结果.md
migration_scenario_validation/reports/bench/origin_ipp_full/
```

与 direct 基线对比：

```text
direct: 20/20 pass, 853 canonical calls, 9362.1s
origin: 12/20 pass, 20 canonical calls, 2805.0s
```

origin 的成本明显更低，但缺少编译器反馈，失败集中在目标 API 签名错误。当前 origin 的上下文包只包含 workspace 文件，没有包含 `/opt/vsipl/include/vsip.h`。
