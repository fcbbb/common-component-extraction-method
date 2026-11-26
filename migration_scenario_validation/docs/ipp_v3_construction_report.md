# IPP → VSIPL V3 Held-out 任务构造报告

## 1. 范围

本报告记录 IPP → VSIPL V3 迁移场景的 held-out 任务构造方法、任务边界、难度覆盖和验证结果。

- 场景：`ipp_to_vsipl`
- 目标库：VSIPL / jvsip
- 目标工具链：gcc-13
- 任务目录：`v3/ipp_vsipl/tasks/`
- 任务清单：`v3/ipp_vsipl/slate.yaml`
- 组件库：`v3/ipp_vsipl/library/`

V3 的 held-out 与 library source 严格分离。任务不参与组件提取、review 或 publish。

## 2. 组件库

当前冻结库包含 3 个组件：

| 组件 | 来源 | 主要覆盖面 |
|---|---|---|
| `split-complex-fft-matched-filter-correlation-layer` | s1 | FFT 相关、lag 顺序、归一化、共轭 |
| `real-to-complex-fft-plan-and-bin-adapter` | s2 | real FFT、自然 bin、未缩放前向、门限 |
| `streaming-complex-nco-mix-and-decimate-layer` | s3 | NCO 相位、抽取 FIR、history、块不变性 |

任务通过 `library_manifest` 指向该库。method 臂只做 retrieval，不从 held-out 重新建库。

## 3. 两种任务构造模式

### 3.1 Source-present

`src/` 提供 IPP 实现，agent 直接迁移。适合验证完整流水线和中等难度任务。

### 3.2 Scheme C：header-only

`src/` 只保留 ABI 和内部状态声明，不提供实现。agent 必须从公开契约、public smoke test 和组件库重建实现。hidden test 和 gold 仍完整。

Scheme C 用于验证组件知识是否真正降低迁移失败率，而不是让 agent 照抄已有循环。

## 4. 任务矩阵

| task | level | domain | 模式 | 主要契约 |
|---|---|---|---|---|
| h1_power_spectrum | L1 | spectral | source-present | 单帧 real power spectrum |
| h2_sonar_lag | L2 | sonar | source-present | 复数 lag correlation |
| h3_stream_lag | L2 | sonar | source-present | 流式 correlation、pending frame |
| h4_header_spectral | L1 | spectral | header-only | real spectral probe ABI |
| h5_burst_acquirer | L3 | communications | source-present | NCO + decimating FIR + lag profiles |
| h6_header_stream | L2 | sonar | header-only | streaming correlation ABI |
| h7_header_only | L3 | communications | header-only | 无实现 streaming burst acquirer |
| h8_header_corr | L2 | sonar | header-only | 无实现 correlation ABI |
| h9_header_spectral_gate | L3 | radar | header-only | 无实现 spectral gate |
| h10_header_corr2 | L2 | sonar | header-only | correlation ABI variant |
| h11_header_burst2 | L3 | communications | header-only | burst ABI variant |
| h12_windowed_peak | L2 | spectral | header-only | Hann 窗 spectral peak |
| h13_spectral_centroid | L2 | spectral | source-present | 窗谱质心 |
| h14_norm_corr | L2 | radar | source-present | 归一化 lag correlation |
| h15_corr2d | L3 | radar | source-present | 2D 复数 lag grid |
| h16_stream_mix_fir | L3 | communications | source-present | 流式 NCO + 抽取 + report |
| h17_cross_coherence | L2 | spectral | source-present | cross-spectrum phase/coherence |
| h18_iq_metrics | L2 | communications | source-present | IQ gain/phase/energy |
| h19_overlap_gate | L3 | spectral | source-present | 窗谱 per-bin flags |
| h20_mc_fir | L3 | communications | source-present | 双通道共享 taps FIR |

说明：h10/h11 是早期 header-only 变体，沿用 h7/h8 的 ABI 形态；h12–h20 为独立构造，不是 h1 的复制。

## 5. 设计控制

1. 每个任务有独立 `task.yaml`、`provenance.json`、`gold/`、`hidden_test`。
2. hidden test 不作为 agent workspace 内容；只由 judge 编译。
3. 所有任务都要求 target API gate（VSIPL 符号）。
4. 所有任务都要求 `api_removal`，不能残留 IPP 符号。
5. gold 必须先通过 public 和 hidden，才允许进入 direct/method 配对。
6. 任务不得从 library source 直接复制为 held-out。
7. 复制任务不得用于补任务编号。早期 h12–h20 的 h1 复制已删除。

## 6. 验证

最终校验：

```text
verify_task: PASS tasks=23   (3 library sources + 20 held-out)
lint_dataset: PASS tasks=82
```

每个任务的 hidden test 由 judge 编译并运行。gold 正控结果记录在各自的 `reports/bench/` 目录。

## 7. 难度分布

```text
L1: h1, h4
L2: h2, h3, h6, h8, h10, h12, h13, h14, h17, h18
L3: h5, h7, h9, h11, h15, h16, h19, h20
```

L3 任务覆盖：

- h5/h7/h11：流式 NCO + FIR + frame carry
- h15：二维复数相关网格
- h16：流式 NCO + 抽取 + block report
- h19：窗谱门限 flags
- h20：双通道共享 taps FIR

## 8. 限制

- 任务是合成工程，不是上游真实项目快照。
- h10/h11 属于早期 header-only 变体，独立性弱于 h12–h20。
- hidden 覆盖深度不完全一致；h16/h18 的检查项较少。
- 每个任务只运行一次 direct 和一次 method，不做重复方差分析。
- 结果不能外推为所有 IPP→VSIPL 工程的普遍结论。
