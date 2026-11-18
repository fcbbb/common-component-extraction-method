# IPP → VSIPL / VSIPL++ 迁移 Benchmark 设计

- **文档日期**：2026-11-12
- **目标读者**：本项目组（不要求读者具备信号处理或 VSIPL 背景）
- **文档定位**：这是本目录的**主报告**。它回答“如何构建一个 benchmark，衡量 agent 把 IPP 代码迁移到 VSIPL 的成功率，并比较组件抽取方法与直接迁移方法”。
- **配套文档**：[ipp_to_vsipl_migration_data_survey.md](ipp_to_vsipl_migration_data_survey.md) 是支撑资源调研（目标运行时、公开信号数据、生成工具、API 映射草案），不是 benchmark 本身。

---

## 0. 一句话结论

**你要的不是“信号数据集”，而是一个代码迁移 benchmark。**

每个任务给 agent 一个 IPP 仓库（或其中一部分）和迁移要求，看它能否产出：

1. 能编译、能链接 VSIPL/VSIPL++ 的代码；
2. 数值行为与原始 IPP 程序一致；
3. 不再依赖 IPP；
4. 通过隐藏测试。

然后用同一批任务，配对比较“组件抽取 + agent”与“直接 agent”的迁移成功率、成本和回归率。

---

## 1. 目标与非目标

### 1.1 目标

| 目标 | 说明 |
|---|---|
| 衡量迁移成功率 | 以“可编译 + 数值等价 + 无 IPP 残留 + 隐藏测试通过”为 resolved 标准 |
| 比较两种方法 | A：直接让 agent 迁移；B：先做组件抽取，再让 agent 基于组件迁移 |
| 可重复 | 固定源码快照、IPP 版本、VSIPL 版本、容器环境、随机种子 |
| 可诊断 | 能按任务层级、API 家族、难度分解失败原因 |
| 防泄漏 | 隐藏测试与参考解；组件库在独立语料上 task-blind 构建 |

### 1.2 非目标

- 不是“信号处理算法研究”：不需要追求真实雷达/通信数据的物理保真度。
- 不是“VSIPL 性能 benchmark”：性能只作为辅助指标，不作为主要 resolved 条件。
- 不是“客户代码复现”：在拿不到客户代码前，用合成仓库族 + 公开仓库派生任务近似。

---

## 2. Benchmark 的任务定义

### 2.1 一个任务包含什么

每个任务是一个目录，核心文件是 `task.yaml`：

```yaml
task_id: l2_radar_pulse_compression_001
level: L2                      # L1 函数级 / L2 模块级 / L3 仓库级
domain: radar                  # radar / comms / spectrum / sar / generic
difficulty: medium             # easy / medium / hard（按基线通过率校准）

source:
  repo: corpus/radar_pipeline
  commit: "<fixed-sha>"
  files:
    - src/pulse_compress.cpp
    - src/fir_filter.cpp
    - include/dsp_common.h
  loc: 620
  ipp_apis:
    - ippsFFTInit_C_32fc
    - ippsFFTExecCToC_32fc
    - ippsFFTInv_CToC_32fc
    - ippsMul_32fc
    - ippsFIRSR_32fc
  note: "IPP 版本以容器内 oneAPI IPP 为准"

target:
  api: VSIPL++                 # VSIPL++ 或 VSIPL C
  library: OpenVSIP            # OpenVSIP / TASP / jvsip
  allowed_extra_libs: [fftw3]  # 是否允许补充库，按实验设计决定

spec: |
  将 source.files 中的 IPP 实现迁移到 VSIPL++，保持输入/输出行为不变。
  要求：
  - 不保留任何 ipps*/ippi* 调用；
  - 使用 VSIPL++ 的 fft / fir / vmul 等接口；
  - 保持原有公开函数签名与构建入口；
  - 通过公开测试与隐藏测试。

build:
  command: "cmake -S . -B build && cmake --build build -j"
  artifact: "build/libdsp.so"

public_tests:
  command: "ctest --test-dir build --output-on-failure"
  visible_to_agent: true

hidden_tests:
  command: "python harness/run_hidden.py --task l2_radar_pulse_compression_001"
  visible_to_agent: false

tolerances:
  float32: {rtol: 1.0e-5, atol: 1.0e-6}
  float64: {rtol: 1.0e-12, atol: 1.0e-14}
  fft_scaling: normalized     # 评测前统一缩放约定

gold_patch: gold/patch.diff   # evaluator-only
```

### 2.2 Agent 能看到什么 / 不能看到什么

| 内容 | Agent 可见 | 评测器可见 | 说明 |
|---|---|---|---|
| 源码快照 | ✅ | ✅ | 固定 commit |
| 迁移说明 `spec` | ✅ | ✅ | 必须足够清晰，但不能泄露补丁 |
| 构建命令 | ✅ | ✅ | |
| 公开测试 | ✅（可选） | ✅ | 给 agent 自检用；建议只给少量 |
| 隐藏测试 | ❌ | ✅ | 防止过拟合 |
| golden 输出 | ❌ | ✅ | 由 IPP 版程序生成 |
| 参考解 `gold_patch` | ❌ | ✅ | 人工/强模型编写并验证 |
| VSIPL 头文件与文档 | ✅ | ✅ | 模拟真实迁移条件 |
| 组件库 | 取决于实验条件 | ✅ | A 条件不给，B 条件给 |

**关键原则**：agent 可以看“规格”，不能看“答案”；可以看“少量公开测试”，不能看“全部判分测试”。

---

## 3. 任务分层

| 层级 | 粒度 | 典型内容 | 任务数（MVP） | 作用 |
|---|---|---|---|---|
| **L1** | 单函数/单文件 | 一个 FFT、一个 FIR、一个相关、一个向量运算 | 4 | 诊断 API 映射与数值细节；组件复用最直接 |
| **L2** | 模块/小链路 | 脉冲压缩、解调前端、频谱感知、滤波器组、重采样链、CFAR | 6 | 最接近真实迁移工作；比较两种方法的主力 |
| **L3** | 小仓库端到端 | 500–3000 LOC 的完整 DSP 程序 | 2 | 长程任务；检验规划、构建、调试能力 |

**难度校准**：MVP 完成后，用基线 agent 跑一遍，保留通过率在 20%–60% 的任务；全过或全不过的任务信息量低，需要调整。

---

## 4. 源仓库怎么来

### 4.1 主力：合成仓库族（推荐）

构建 5–8 个小型 C++ 仓库，每个都：

- 使用一组稳定的 IPP API（FFT、FIR、卷积、相关、向量算术、统计、重采样）；
- 有 `CMakeLists.txt` 或 `Makefile`；
- 有自己的公开测试；
- 有真实感的 DSP 链路，而不是玩具函数；
- **共享一套脚手架**（见 4.3）。

建议的仓库族：

| 仓库 | 链路 | 主要 IPP 家族 |
|---|---|---|
| `radar_pulse_compression` | 加窗 → FFT → 匹配滤波 → IFFT → 取模 | FFT、Mul、FIR/Conv |
| `comms_demod_frontend` | 下变频 → 滤波 → 抽取 → 定时/相位 | FIR、Resample、Vector |
| `spectrum_sensing` | 分帧 → 窗 → FFT → 功率谱 → 门限 | FFT、Window、Stat |
| `filter_bank_analysis` | 多相分解 → 多路 FIR → 合并 | FIR、Resample |
| `cfar_detector` | 平方律 → 滑窗统计 → 门限 | Vector、Stat、Threshold |
| `sar_backprojection_small` | 距离压缩 → 插值 → 相干累加 | FFT、Conv、Vector |
| `generic_dsp_utils` | FFT 封装、buffer/view、错误处理、窗函数 | 多个 |

**优点**：

- 许可证干净（自己写的）；
- 难度可控；
- 可以刻意制造跨仓库重复模式，让组件抽取有东西可抽；
- 可以精确控制“哪些任务有 VSIPL 对应 API、哪些没有”。

**注意**：合成仓库必须真的能编译、能跑、能生成 golden 输出；不能是伪代码。

### 4.2 补充：公开 IPP 仓库派生（20%–30%）

可选来源：

- [opentelecoms-org/ipp_audio_codecs](https://github.com/opentelecoms-org/ipp_audio_codecs)：G.729/G.723.1 的 IPP 实现，真实但偏语音编解码。
- OpenCV 的 IPP 路径：`CV_IPP_RUN_*` 调用分散在图像处理模块，适合抽 `ippi*` 任务，但仓库巨大、许可为 Apache-2.0、抽取成本高。
- 其他 GitHub 上使用 IPP 的小项目（需逐个确认许可证与可编译性）。

**建议**：公开仓库只用于补充真实性，不作为 MVP 主力。它们往往难以隔离、依赖复杂、许可证不一。

### 4.3 关键设计：跨仓库重复模式

组件抽取方法要体现优势，benchmark 必须包含**跨仓库的重复结构**。建议每个仓库都包含以下模式的不同变体：

| 模式 | 变体 |
|---|---|
| FFT 计划/执行封装 | 不同长度、实数/复数、正/逆变换、缩放约定 |
| Buffer / View 管理 | 连续/stride/offset、对齐、split/interleaved |
| 滤波器状态管理 | FIR 状态、多相、重采样比 |
| 窗函数生成 | Hamming/Hann/Blackman/Kaiser |
| 错误处理与参数校验 | 统一错误码、边界检查 |
| 构建与测试脚手架 | CMake option、测试数据加载 |

如果每个仓库都各写各的，组件库就没有可复用物，方法 B 会被人为削弱——这会让实验结论失真。

---

## 5. 参考解与测试怎么造

### 5.1 Golden 输出（源侧 ground truth）

1. 在容器内安装固定版本的 Intel oneAPI IPP。
2. 编译原始 IPP 程序。
3. 用固定输入向量运行，保存输出为 `golden/`。
4. 对同一输入，用 NumPy/SciPy 再算一份，作为第三方仲裁。

输入向量不需要真实数据，覆盖以下矩阵即可：

| 维度 | 取值 |
|---|---|
| 信号类型 | 冲激、单音、多音、chirp、PRN、带限噪声、脉冲串 |
| 长度 | 奇数/偶数、2 的幂/非 2 的幂、1K/64K/1M |
| 类型 | float32/float64、实数/复数 |
| 布局 | 连续/stride/offset/非对齐 |
| 边界 | 空、长度 1、短于滤波器阶数、全零、NaN/Inf |

### 5.2 参考迁移解（gold patch）

- 由人工或强模型编写 VSIPL/VSIPL++ 版本。
- 必须通过：
  - 编译/链接；
  - 数值等价（在容差内）；
  - API 合规（无 `ipps*/ippi*` 残留）；
  - 隐藏边界测试。
- 参考解**不展示给被测 agent**。
- 若 VSIPL 没有对应 API（如 Goertzel、Hilbert、部分 IIR），参考解中应给出自研实现，并在任务中标注 `api_gap: true`，这类任务专门测试 agent 的推理与补缺能力。

### 5.3 测试层次

| 测试 | 判什么 | 是否隐藏 |
|---|---|---|
| 编译/链接测试 | 能否在 VSIPL 环境构建 | 否 |
| 数值等价测试 | 与 golden 在容差内一致 | 主要是 |
| API 合规测试 | 静态检查无 IPP 调用/依赖 | 否 |
| 边界/隐藏测试 | stride、奇数长度、零输入、大幅值等 | 是 |
| 回归测试（P2P） | 原仓库已有测试不回归 | 部分 |
| 性能健全性 | 不应慢到不可用（可选） | 否 |

### 5.4 数值容差

| 类型 | 建议 |
|---|---|
| float32 | rtol 1e-5，atol 1e-6 |
| float64 | rtol 1e-12，atol 1e-14 |
| FFT | 按长度放宽；评测前统一缩放/移位约定 |
| 滤波器 | 除数值容差外，检查群延迟/相位一致性 |
| 复数布局 | 评测前统一为 interleaved，避免布局差异误判 |

**重要**：容差不是越严越好。先用参考解跑出实际误差分布，再定阈值；否则会把正确实现判错。

---

## 6. 评分指标

### 6.1 主指标

| 指标 | 定义 |
|---|---|
| **Resolve Rate** | 所有隐藏 F2P 测试通过、且无 P2P 回归的任务数 / 总任务数 |
| **Compile Rate** | 能成功构建的任务数 / 总任务数 |
| **Numerical Pass Rate** | 数值测试通过数 / 数值测试总数 |
| **API Removal Rate** | `1 - 剩余 ipps/ippi 调用数 / 初始调用数` |

### 6.2 辅助指标

| 指标 | 用途 |
|---|---|
| 测试通过比例 | 区分“全错”和“差一点” |
| Patch 规模（文件数/LOC） | 判断是否过度改写 |
| Token / 时间 / 工具调用数 | 成本对比 |
| 人工评审分（1–5） | 代码可维护性、是否符合 VSIPL 习惯 |
| 组件命中率 / 复用率 | 方法 B 的机制指标 |
| 泛化通过率 | 在未参与组件抽取的 holdout 仓库上的表现 |

### 6.3 指标公式

```text
resolve_rate      = resolved_tasks / total_tasks
compile_rate      = compiled_tasks / total_tasks
numerical_pass    = passed_numerical_tests / total_numerical_tests
api_removal_rate  = 1 - remaining_ipp_calls / initial_ipp_calls
component_reuse   = tasks_using_at_least_one_component / total_tasks
```

---

## 7. 配对实验设计

### 7.1 两种条件

| 条件 | 描述 |
|---|---|
| **A：直接迁移** | agent 拿到源码 + 规格 + 构建/测试命令，直接改 |
| **B：组件抽取 + 迁移** | 先在独立语料上 task-blind 构建组件库；agent 拿到同样的源码 + 规格 + 组件检索结果，再改 |

### 7.2 控制变量

- 同一模型、同一版本、同一推理参数；
- 同一系统提示、同一工具集、同一 token/时间预算；
- 同一容器镜像（IPP 与 VSIPL 版本固定）；
- 同一任务顺序或随机化顺序；
- 组件库构建阶段**不得**读取任务说明、测试、gold patch（与你们现有方法一致）。

### 7.3 重复与统计

- 每个任务每个条件跑 **3–5 次**（agent 有随机性）。
- 报告 mean ± 95% CI。
- Resolve Rate 用配对 McNemar 检验；成本用配对 bootstrap 或 Wilcoxon。
- 按 L1/L2/L3、API 家族、难度分别报告，避免平均值掩盖差异。

### 7.4 防泄漏

- 组件抽取语料与评测任务**仓库级隔离**（holdout）。
- 隐藏测试、gold patch 不出现在 agent 上下文。
- 公开测试只给少量，且不覆盖隐藏边界。
- 任务说明不包含“应该用哪个 VSIPL 函数”的逐步答案。
- 检查 agent 是否通过读取测试文件、环境变量、构建缓存等方式作弊。

### 7.5 有效性检查

- **难度校准**：基线通过率应在 20%–60%。
- **区分度**：加入“浅层替换会失败”的任务（布局、缩放、API 缺口），避免 benchmark 退化成字符串替换。
- **可复现性**：固定种子与镜像；记录每次运行的模型版本、token 数、耗时。
- **人工抽检**：对 resolved 的任务抽查，确认不是测试漏洞。

---

## 8. 与你们现有组件抽取方法的关系

你们现有的方法（见上级目录 `README.md`）是：

1. 固定源码快照；
2. task-blind 计算结构/重复/语义信号；
3. 生成协议候选；
4. 抽取、审核、运行时验证组件；
5. 发布组件库；
6. 任务阶段检索组件；
7. 运行直接基线与组件方案；
8. 汇总结果。

本 benchmark 可以直接复用这套流水线的后半段：

| 现有能力 | 在本 benchmark 中的用途 |
|---|---|
| `prepare_workspace.py` | 为每个迁移任务创建工作区 |
| `preflight.py` | 检查 IPP/VSIPL 环境与模型配置 |
| 批量 runner | 跑 A/B 两种条件 |
| P2P/F2P 概念 | 回归测试 + 迁移测试 |
| 组件库与检索 | 条件 B 的输入 |
| 结果汇总 | Resolve Rate 与成本对比 |

**需要新增的**：

- 迁移任务的 `task.yaml` schema；
- IPP golden 生成器；
- VSIPL 构建/测试 harness；
- 数值容差比较器；
- API 合规静态检查；
- 迁移专用评分脚本。

---

## 9. MVP 计划

### 9.1 范围

| 项 | 数量 |
|---|---|
| 源仓库（组件抽取语料） | 5 个 |
| L1 任务 | 4 |
| L2 任务 | 6 |
| L3 任务 | 2 |
| 参考解 | 12 份 |
| 隐藏测试 | 每任务 3–8 个 |

### 9.2 目录结构

```text
migration_scenario_validation/
├── README.md
├── migration_benchmark_design.md
├── ipp_to_vsipl_migration_data_survey.md
└── benchmark/
    ├── corpus/                       # 组件抽取语料（task-blind）
    │   ├── radar_pipeline/
    │   ├── comms_frontend/
    │   └── ...
    ├── tasks/
    │   ├── l1_fft_001/
    │   │   ├── task.yaml
    │   │   ├── source/
    │   │   ├── public_tests/
    │   │   ├── hidden_tests/
    │   │   ├── golden/
    │   │   └── gold_patch/
    │   └── ...
    ├── harness/
    │   ├── build.sh
    │   ├── run_hidden.py
    │   ├── compare_numeric.py
    │   ├── check_api.py
    │   └── score.py
    └── docker/
        └── Dockerfile                # 固定 oneAPI IPP + OpenVSIP/TASP
```

### 9.3 里程碑

| 阶段 | 产出 | 预计 |
|---|---|---|
| M1 | 容器镜像 + task schema + harness 骨架 | 2–3 天 |
| M2 | 5 个源仓库 + 4 个 L1 任务 + 参考解 | 1 周 |
| M3 | 6 个 L2 + 2 个 L3 任务 + 隐藏测试 | 1 周 |
| M4 | 跑通 A/B 基线，校准难度，出第一版结果 | 3–5 天 |

> 工作量为 1 人估算，实际取决于 IPP/VSIPL 环境搭建是否顺利。

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| IPP 环境难装/版本漂移 | golden 不稳定 | 固定 Docker 镜像与 IPP 版本 |
| VSIPL 实现功能缺口 | 参考解写不出 | 标注 `api_gap`，参考解用自研补齐；统计缺口 |
| 任务太简单 | 两种方法都满分 | 加入布局/缩放/边界/缺口任务，做难度校准 |
| 任务太难 | 两种方法都零分 | 增加 L1、减少 L3；给出更清晰的规格 |
| 组件库泄漏任务信息 | 条件 B 被人为抬高 | 组件构建 task-blind；仓库级 holdout |
| 测试过拟合 | agent 改测试或硬编码 | 隐藏测试；评测时重置测试文件；静态检查 |
| 数值容差定错 | 正确解被判错/错误解被判对 | 用参考解误差分布定阈值；多实现交叉验证 |
| 公开数据不可达 | L3 任务缺输入 | L1/L2 用合成向量；L3 用自生成数据 |
| 题目规模偏小（组件级而非仓库级） | 外部效度：无法预测大仓库上的迁移表现 | 分层报告并单独列出 Patch 规模；补整仓构建题与合成仓库族；见 `task_scale_limitations.md` |

---

## 11. 与现有公开 benchmark 的关系

截至 2026-11-12，**没有检索到 IPP→VSIPL 的公开迁移 benchmark**。可借鉴的相近工作：

| 工作 | 关系 | 可借鉴点 |
|---|---|---|
| [XStack](https://arxiv.org/abs/2611.08472)（2026-11） | ML 仓库在 PyTorch/GPU 与 JAX/TPU 之间迁移 | 仓库级任务、以源仓库发布结果为 ground truth、按统一标准判分 |
| SWE-bench 系列 | 真实仓库任务评测范式 | 隐藏 F2P 测试、P2P 回归、resolved 定义 |
| [CodeTransOcean](https://github.com/WeixiangYAN/CodeTransOcean)、[xCodeEval](https://github.com/ntunlp/xCodeEval) | 代码翻译 benchmark | 多语言/多任务组织方式、测试驱动评分 |
| CUDA→HIP 迁移工具 | 工程实践 | 编译/运行/逐轮修复的 agent 循环 |

**结论**：borrow 方法论，不 borrow 题目；IPP→VSIPL 的任务集必须自建。

---

## 12. 下一步

1. 确认 benchmark 的三层任务划分与 MVP 范围（本报告第 3、9 节）。
2. 搭建 Docker 环境：oneAPI IPP + OpenVSIP/TASP。
3. 先做 4 个 L1 任务，跑通“源程序 → golden → 参考解 → 隐藏测试 → 评分”闭环。
4. 再扩到 L2/L3，并接入你们现有的组件抽取流水线。
5. 用 3–5 次重复跑 A/B，出第一版对比结果。

---

## 附录 A：一个 L1 任务的完整示例

```text
tasks/l1_fft_001/
├── task.yaml
├── source/
│   ├── CMakeLists.txt
│   └── fft_wrap.cpp          # 使用 ippsFFT*，对外暴露 fft_c2c()
├── public_tests/
│   └── test_basic.cpp        # 只测一个单音
├── hidden_tests/
│   ├── test_lengths.py       # 奇数/非 2 的幂/大尺寸
│   ├── test_scaling.py       # 正/逆变换缩放
│   └── test_layout.py        # stride/offset
├── golden/
│   ├── input_0001.bin
│   └── output_0001.bin
└── gold_patch/
    └── patch.diff            # 用 VSIPL++ fft 重写，含缩放适配
```

`task.yaml` 中 `level: L1`、`ipp_apis: [ippsFFT*]`、`tolerances` 按 5.4 设置。

---

## 附录 B：隐藏测试的判定伪代码

```python
def evaluate(task, agent_repo):
    build = run(task.build.command, cwd=agent_repo)
    if build.returncode != 0:
        return {"resolved": False, "reason": "compile_failed"}

    api = check_api(agent_repo, forbidden=["ipps", "ippi"])
    if not api.ok:
        return {"resolved": False, "reason": "ipp_calls_remaining"}

    p2p = run(task.public_tests.command, cwd=agent_repo)
    if p2p.failed:
        return {"resolved": False, "reason": "regression"}

    for case in task.hidden_tests:
        actual = run_case(agent_repo, case.input)
        if not within_tolerance(actual, case.golden, task.tolerances):
            return {"resolved": False, "reason": f"numeric_mismatch:{case.id}"}

    return {"resolved": True}
```

---

## 附录 C：术语

| 术语 | 含义 |
|---|---|
| IPP | Intel Integrated Performance Primitives，Intel 高性能函数库 |
| VSIPL | Vector Signal Image Processing Library，OMG 标准化 C API |
| VSIPL++ | VSIPL 的 C++ API 标准 |
| golden 输出 | 由原始 IPP 程序在固定输入上产生的正确输出 |
| F2P | fail-to-pass，迁移前失败、迁移后应通过的测试 |
| P2P | pass-to-pass，迁移前后都应通过的回归测试 |
| resolved | 编译通过 + 隐藏测试通过 + 无回归 + 无 IPP 残留 |
| holdout | 不参与组件抽取、只用于评测的仓库/任务 |