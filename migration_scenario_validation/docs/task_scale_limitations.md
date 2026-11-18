# 任务规模与仓库级覆盖：已知限制

日期：2026-11-17
状态：**已知限制，未解决**。本文件记录“当前 slate 的题目偏小、缺少仓库级任务”这一事实、成因、对外部效度的影响，以及补题方案。

---

## 1. 结论

当前三场景共 60 题，覆盖**组件级迁移**。

- 它测的是：API 识别与替换、数值/缩放/布局约定、目标库缺口下的分解重组、构建与调试。
- 它**不测**：在数千文件里定位改动点、跨模块重构、多模块依赖与构建系统手术、长上下文维持。
- 因此它可以支撑“组件抽取对重复 API 契约有帮助”的结论，**不能**单方面支撑“能预测真实大仓库上的迁移效果”。对外使用时必须限定适用范围。

## 2. 实测规模

### 2.1 IPP → VSIPL（20 题）

每题可见源码是**一个 `.c` + 一个 `.h`**。`src/` 行数分布：

| 区间 | 题目 |
|---|---|
| ≤ 100 行 | `l1_vec_db_mag` 36、`l1_window_gen` 45、`l3_iir_eq_negative` 75、`l2_dot_norm_stats` 76、`l2_cfar_detector` 91、`l1_aubio_dct` 92 |
| 101–300 行 | `l2_tdfir_bank` 100、`l1_steamaudio_fft` 109、`l1_conv_corr` 120、`l2_fdfir_overlap_save` 132、`l1_juce_fft` 158、`l2_cil_fbp` 172、`l3_spectrum_sensing` 202、`l2_r8brain_fft` 257、`l2_aubio_fft` 260、`l3_comms_demod_frontend` 277 |
| 301–1000 行 | `l3_radar_pulse_compression` 313、`l3_audio_resampler` 349、`l2_saf_stft` 649、`l2_rubberband_fft` 932 |

加上 `include/` 后的最大可见面：`l2_rubberband_fft` 1154 行、`l2_r8brain_fft` 1113 行、`l2_saf_stft` 1068 行；其余均 < 800 行。

8 道“真实仓库”题（来自 7 个上游仓库）也都**只抽出一个后端文件**：aubio `dct_ipp.c`、aubio `fft_ipp.c`、rubberband `FFT.cpp` 的 IPP 后端、SAF `saf_utility_fft.c`、steam-audio `ipp_fft.cpp`、JUCE `juce_FFT.h`、CIL `FBP_filtering.cpp`、r8brain `CDSPRealFFT.h`。仓库本身的规模不进入任务。

### 2.2 Windows → 麒麟（20 题）

`prepare.sh` 物化的是**完整上游仓库**（例如 `l1_poco_thread/work` = 4747 个文件 / 71 MB，`l2_libuv_thread/work` = 461 个文件 / 5.3 MB），但**范围内的迁移改动通常只有 1 个文件**（`Thread_POSIX.cpp`、`Path_UNIX.cpp` 等）。

真正多文件的只有 L3：

| 任务 | gold 范围 |
|---|---|
| `l3_poco_foundation_full` | 17 个 `*_UNIX/_POSIX.cpp` |
| `l3_nginx_full` | 整个 `src/os/unix` 目录 |
| `l3_libgit2_full` | 整个 `src/util/unix` 目录 |
| `l3_curl_build` | `CMakeLists.txt` + `CMake/`（构建系统迁移） |

所以这一场景的 L1/L2 是“仓库里改一个文件”，只有 L3 是仓库级的。

### 2.3 CUDA → MUSA（20 题）

`work/` 是完整 MultiKernelBench 树，但提交物是**单个 Python 文件**（`submission/<op>_submission.py`，内含 `load_inline` 的 kernel 源码）。规模上等同 L1/L2。

### 2.4 设计文档本身的选择

`docs/migration_benchmark_design.md` §3 把分层的上限写死为：

| 层级 | 定义 |
|---|---|
| L1 | 单函数/单文件 |
| L2 | 模块/小链路 |
| **L3** | **500–3000 LOC 的“小仓库端到端”** |

原始设计里的“仓库级”指 500–3000 行。`docs/ipp_to_vsipl_task_slate.md` §7.10 也写明：“L3 指的是整链端到端的形态，不是体量。”

## 3. 为什么没有仓库级 IPP 任务

### 3.1 已记录的原因

1. **IPP 闭源，没有官方样例仓库。** 二进制 + 头文件分发，samples 随安装包发布；`intel/ipp-samples` 在 GitHub 上 404 且无 Wayback 快照（数据调研报告属过程材料，不随仓库分发）。
2. **公开仓库里 IPP 只是可选后端，调用面天然很薄。** 按构建筛选报告实测 11 个仓库，只有 7 个能在打开 IPP 开关后编译（aubio、rubberband、SAF、steam-audio、JUCE、CIL、r8brain），其中只有 aubio 的测试能跑。报告的结论是：差距来自大部分 IPP 调用点缺少可运行的测试/构建路径，代码本身容易找到。
3. **设计不要求大仓库。** 见 §2.4。

### 3.2 推断（未在仓库其他文档中记录）

“大型 IPP 仓库”这个前提本身可能就不成立，原因不在检索，而在 IPP 的生态形态：

- **IPP 是叶子依赖，不是框架。** 它提供内核（FFT/FIR/向量），不提供对象模型、内存管理、调度。集成方式必然是“在热点处塞一个 `#ifdef USE_IPP`”，不会围绕它建架构。
- **闭源 + CI 不可得，把 IPP 挡在默认构建之外。** 开源项目在 CI 里拿不到 IPP，只能默认走 FFTW/KissFFT/PFFFT；IPP 分支长期不编译、不测试、不演进，因此长不大。HISE、Open3D 编不过也是同一条约束的体现。
- **API 面小且模板化。** 几百个“指针 + 长度 + stride”的向量内核，每个调用点都是一层薄 wrapper，不产生深耦合。
- **OpenCV 是反例式证据。** 它重度使用 IPP，但走闭源 `ippicv` 预编译包——**IPP 代码不在仓库里**，仓库内只有调用点，因此无法作为迁移源。
- **商业客户代码不公开。** IPP 的主要使用者是商业软件厂商，其代码库不公开；这既解释了公开语料稀缺，也说明“真实大仓库”只能来自客户侧。

### 3.3 这个推断的可检验推论

如果客户的真实代码也是“每个内核一层薄 wrapper”，那么当前组件级设计与实际迁移单位一致，规模不是缺陷；如果客户代码是十万行、IPP 调用散落在业务模块、并与自研抽象层纠缠，则当前 L3 明显不具代表性。

**需要向客户确认的问题**（拿到真实代码前无法回答）：

1. 有多少文件、多少行直接调用 IPP？
2. IPP 调用集中在少数适配层，还是散落在业务代码中？
3. 是否存在自研的 FFT/FIR/重采样抽象层？迁移单位是“换实现”还是“逐调用点映射”？
4. 典型迁移 PR 改动几个文件、多少行？
5. 是否有必须保留的公开 API / ABI 约束？

## 4. 对外部效度的影响

核心主张是“组件抽取 + agent 迁移 优于 直接 agent 迁移”。当前规模下：

- **能证明的**：组件库能复用同一批语义坑的处理方式（FFT 缩放、CCS/Perm 布局、流式状态、窗函数约定），从而降低 API 映射类错误。
- **不能证明的**：组件抽取对仓库级能力（定位、跨文件一致修改、依赖手术、预算管理）的收益。
- **可能被高估的**：单文件任务里，agent 的上下文压力小、定位成本接近零，直接迁移臂可能因此显得比真实场景更容易；这会让 A/B 差值偏向某一侧，方向不确定。
- **风险**：若所有模型都通过 L1/L2，题目失去区分度（`migration_benchmark_design.md` §3 的难度校准目标是通过率落在 20%–60%）。

**当前尚未测量**：三场景 condition A 的真实模型基线未开跑；`task.yaml` 里的 `difficulty` 是作者标注（IPP 12 medium / 3 easy / 5 hard，Kylin 7 medium / 10 hard / 3 easy，MUSA 7 medium / 7 hard / 6 easy），不是实测通过率。因此“这些题到底简单还是难”目前没有数据答案。

## 5. 缓解方案

按性价比排序：

1. **分层报告，不混总分。** 按 L1/L2/L3、场景、fit 分别报告 resolve rate；把 `Patch 规模（文件数/LOC）`（`migration_benchmark_design.md` §6.2 已有该辅助指标）作为独立列，暴露“只改了 1 个文件”的题。
2. **整仓构建题（不改素材）。** 用 rubberband 全仓（`-Dfft=ipp` 已验证可建）或 aubio 全仓：任务是“在只有 VSIPL 的环境里让整个项目构建并通过自带测试”。改动仍可能是 1 个文件，但考的是构建系统、依赖与测试定位。
3. **合成仓库族。** 按 `migration_benchmark_design.md` §4.1 的原计划，把现有 12 个合成内核拼成 3–5 个共享脚手架（FFT plan / buffer / 窗 / 流式状态）的多模块仓库，考跨模块一致性与组件复用——这也正是 A/B 实验最需要的形态。
4. **客户真实代码到位后作为 L3。** 这是唯一能真正解决外部效度问题的方式。
5. **不推荐**：HISE（需要全部 submodule）、Open3D（需要完整构建）——成本高且 IPP 面很浅。

## 6. 相关文档

- `docs/migration_benchmark_design.md` §3（分层定义）、§6.2（Patch 规模指标）、§10（风险表）
- `docs/ipp_to_vsipl_task_slate.md` §7.10（“L3 不是体量”）
- 过程材料（不随仓库分发）：IPP 数据调研、IPP 构建筛选、两场景 v1 方案