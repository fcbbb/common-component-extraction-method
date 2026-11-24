# IPP → VSIPL V3 Held-out 结果统计与分析报告

## 1. 实验设置

- 数据集：20 个 held-out 任务
- direct 臂：普通 DSH agent，无组件 bundle
- method 臂：retrieval-only，使用冻结组件库
- 每个任务：direct 1 次、method 1 次
- 同一任务包、同一 judge、同一模型
- method prompt：`config/prompts/method_retrieval_only_system.txt`
- method bundle：`v3/ipp_vsipl/library`

method 不执行 source scan、extract、review、publish。

## 2. 总体统计

| 结果 | 任务数 | 比例 |
|---|---:|---:|
| direct pass / method pass | 13 | 65% |
| direct fail / method pass | 5 | 25% |
| direct fail / method fail | 2 | 10% |
| direct pass / method fail | 0 | 0% |
| 合计 | 20 | 100% |

关键指标：

```text
direct pass: 13/20 = 65%
method pass: 18/20 = 90%
sensitive (direct fail / method pass): 5
both fail: 2
```

满足目标：

```text
direct fail / method pass >= 4
direct fail / method fail = 2
```

## 3. 逐任务结果

| task | direct | method | direct 秒 | method 秒 |
|---|---|---|---|---:|
| h1_power_spectrum | pass | pass | 132.0 | 138.2 |
| h2_sonar_lag | pass | pass | 153.2 | 151.5 |
| h3_stream_lag | pass | pass | 148.1 | 308.0 |
| h4_header_spectral | pass | pass | 737.3 | 187.4 |
| h5_burst_acquirer | pass | pass | 273.3 | 354.1 |
| h6_header_stream | fail | fail | 171.8 | 227.2 |
| h7_header_only | fail | pass | 266.4 | 270.9 |
| h8_header_corr | fail | pass | 181.8 | 195.1 |
| h9_header_spectral_gate | fail | fail | 176.6 | 279.9 |
| h10_header_corr2 | fail | pass | 241.2 | 163.3 |
| h11_header_burst2 | fail | pass | 280.4 | 214.7 |
| h12_windowed_peak | fail | pass | 479.6 | 329.0 |
| h13_spectral_centroid | pass | pass | 349.8 | 212.7 |
| h14_norm_corr | pass | pass | 151.5 | 212.6 |
| h15_corr2d | pass | pass | 334.1 | 335.1 |
| h16_stream_mix_fir | pass | pass | 214.6 | 245.6 |
| h17_cross_coherence | pass | pass | 168.1 | 187.0 |
| h18_iq_metrics | pass | pass | 163.6 | 248.3 |
| h19_overlap_gate | pass | pass | 144.3 | 195.9 |
| h20_mc_fir | pass | pass | 113.4 | 190.0 |

完整调用数、token 和逐任务报告位于：

```text
reports/bench/held_out_20_summary.md
```

## 4. 敏感任务

5 个 `direct fail / method pass`：

```text
h7_header_only
h8_header_corr
h10_header_corr2
h11_header_burst2
h12_windowed_peak
```

这些任务的共同特征：

- 实现代码缺失或高度抽象，direct 只能从 ABI 和 public smoke 推断；
- direct 在 lag 顺序、FIR/NCO 状态、FFT 归一化或窗函数上出错；
- method 通过组件卡片获得这些边界规则，并在同一 judge 下通过。

h7 的直接失败包括 irregular split 的 lag=0 不一致和非二次幂 nfft 未拒绝。h8 的直接失败包括 scale、oversized FFT、reuse 和 reference-copy 检查。h12 的直接失败集中在窗谱契约。

## 5. 双失败任务

```text
h6_header_stream
h9_header_spectral_gate
```

- h6：header-only streaming correlation；direct 和 method 都未通过 capacity/reference replacement 等边界。
- h9：header-only spectral gate；direct 和 method 都未通过完整门限契约。

这两个任务不提供组件优势证据，但满足结果矩阵中“双失败”样本要求。

## 6. 分析与解释

### 6.1 method 的收益

method pass 从 13/20 提高到 18/20，增加 5 个任务。所有增益都来自 direct 原本失败的 header-only/抽象任务，没有出现 direct pass 而 method fail。

### 6.2 为什么 source-present 任务多为 both pass

h13–h20 以及 h1–h5 提供较完整的源码或明确公式，direct 能直接迁移；组件知识不是必需条件。它们用于覆盖基础能力、验证 target API 和增加领域覆盖，不承担敏感性证明。

### 6.3 为什么 header-only 任务更敏感

没有 `src/*.c` 时，direct 必须自行重建：

- FFT 缩放位置
- lag 顺序和共轭
- NCO 相位和 FIR history
- block/frame 边界
- capacity 和报告字段

组件卡片正好记录这些迁移陷阱，因此 method 更容易通过。

### 6.4 双失败的边界

h6/h9 说明组件方法不是万能的。capacity、reference replacement、空块和完整门限语义并没有被组件卡片完全覆盖，method 也会失败。

## 7. 有效性与限制

- 每个任务只运行一次，结果包含模型采样方差。
- 任务是合成工程，不是真实上游仓库。
- h10/h11 是 header-only 变体，独立性弱于 h12–h20。
- h16/h18 的 hidden 检查项较少，敏感性和覆盖度有限。
- 2D 相关任务 h15 使用 dense O(N^2) 参考，不代表大规模性能。
- 不能把 25% 敏感率外推为所有 IPP→VSIPL 迁移的总体比例。

## 8. 结论

在当前 20 个 held-out 任务上：

```text
direct pass: 13/20
method pass: 18/20
direct fail / method pass: 5
direct fail / method fail: 2
direct pass / method fail: 0
```

结果支持“组件检索对抽象迁移任务有正向作用”，但不支持“组件方法普遍优于 direct”。敏感性主要集中在 header-only 和状态化任务，而不是所有任务类型。
