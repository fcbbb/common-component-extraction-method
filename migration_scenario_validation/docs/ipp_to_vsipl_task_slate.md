# IPP → VSIPL 迁移任务 Slate（20 个）

日期：2026-11-14
上游依据：
- `ipp_to_vsipl_migration_data_survey.md`（数据与库调查）
- `migration_benchmark_design.md`（任务/评分/实验设计）
- `ipp_to_vsipl_build_screening.md`（2026-11-14 构建筛选）

本文件只回答一件事：**这 20 个任务分别是什么，源在哪，映射到什么 VSIPL API，怎么判分。**

---

## 1. 选型前先确认的能力边界

任务不是凭想象切的，先实测了两端：

**IPP 侧（`ipp-static` 2021 / 2026，静态库 + 头文件）**

| 能力 | 是否有 | 关键符号 |
|---|---|---|
| FFT / DFT（实数、复数、原地/非原地） | ✅ | `ippsFFTInit_R_32f`, `ippsFFTFwd_RToCCS_32f`, `ippsFFTInv_CCSToR_32f`, `ippsFFTInit_C_32fc`, `ippsFFTFwd_CToC_32fc` |
| DCT-II/III | ✅ | `ippsDCTFwdInit_32f`, `ippsDCTFwd_32f`, `ippsDCTInv_32f` |
| FIR（单速率、流式） | ✅ | `ippsFIRSR_32f` |
| IIR | ✅ | `ippsIIRGetStateSize_32f`, `ippsIIRInit_32f`, `ippsIIR_32f` |
| 卷积 / 相关 | ✅ | `ippsConvolve_32f`, `ippsCrossCorrNorm_32f` |
| 多相重采样 | ✅ | `ippsResamplePolyphaseFixed_32f` |
| 窗函数 | ✅ | `ippsWinHamming_32f`, `ippsWinHann_32f`, `ippsWinBlackman_32f`, `ippsWinKaiser_32f` |
| 向量算术 / 统计 / 阈值 | ✅ | `ippsMul_32f`, `ippsMagnitude_32f`, `ippsLog10_32f_A21`, `ippsSqr_32f`, `ippsMean_32f`, `ippsStdDev_32f`, `ippsThreshold_32f`, `ippsDotProd_32f` |
| 实/复转换 | ✅ | `ippsRealToCplx_32f`, `ippsCplxToReal_32fc` |
| 矩阵转置 | ✅（图像接口） | `ippiTranspose_32f_C1R` |
| **QR / SVD** | ❌ | 头文件里没有 —— 见 §5 |
| 图像算子（resize/filter/remap） | ✅ | `iwi*`、`ippi*`（但 VSIPL 无对应） |

**VSIPL 侧（jvsip，VSIPL 1.3 C 参考实现，MIT）**

已实际编译并跑通探针程序（`~/work/ipp_screening_20261114/vsipl_probe/`）：

```
FFT roundtrip maxerr < 1e-6   (N=8/64)
FIR ok / QR ok / SVD ok
```

jvsip 覆盖：`fft/fftm`、`fir`、`convolve1d/correlate1d`、`qrd`、`svd`、`chol`、`lu`、
`vadd/vmul/vsma/vdot/vmag/vlog10/vclip/vlgt/vhisto/vinterp_linear|nearest|spline`、
`vcreate_hanning/blackman/kaiser/cheby`、`mtrans`、`mmul`、`cumsum`、`sortip`。

jvsip **没有**：IIR、DCT、Hamming 窗、多相比率重采样、图像算子、形态学。

这两张表直接决定了下面的 fit 分级。

---

## 2. fit 分级定义

| 级 | 含义 | 对实验的作用 |
|---|---|---|
| **A** | VSIPL 有对应 API，一对一映射 | 测 API 识别与参数/缩放约定 |
| **B** | 无直接 API，但可用 VSIPL 原语组合实现 | 测分解与组合能力，组件库收益最大 |
| **C** | VSIPL 完全无对应，只能手写或等效替换 | 负样本：只判 API 移除率与行为等价 |

C 类不能多，否则"迁移"退化成"重写"，但必须有 —— 否则 agent 会形成"所有 IPP 调用都能在 VSIPL 里找到"的错误预期，API 移除率指标也会失去区分度。

---

## 3. 20 任务总表

层级：L1 单函数/单文件；L2 模块链路；L3 小仓库端到端。

| # | task_id | 层 | 域 | 来源 | LOC | 主力 IPP API | VSIPL 映射 | fit |
|---|---|---|---|---|---|---|---|---|
| 1 | `l1_steamaudio_fft` | L1 | audio | **真实** steam-audio | 109 | `ippsFFTGetSize_R_32f`, `ippsFFTInit_R_32f`, `ippsFFTFwd_RToCCS_32f`, `ippsFFTInv_CCSToR_32f` | `vsip_rcfftop_create_f` / `vsip_crfftop_create_f` | A |
| 2 | `l1_juce_fft` | L1 | audio | **真实** JUCE | 1007 | `ippsFFTInit_R_32f/_C_32fc`, `ippsFFTFwd_CToC_32fc`, `ippsFFTInv_CToC_32fc`, `ippsFFTFwd_RToCCS_32f_I` | `vsip_ccfftop_create_f`, `vsip_crfftop_create_f` | A |
| 3 | `l1_aubio_dct` | L1 | audio | **真实** aubio 0.4.9 | 150 | `ippsDCTFwdInit_32f/_64f`, `ippsDCTFwd`, `ippsDCTInv` | 无 DCT → 重排 + 复数 FFT | B |
| 4 | `l1_vec_db_mag` | L1 | radar | 合成（HPEC DB 内核） | ~120 | `ippsMagnitude_32f`, `ippsLog10_32f_A21`, `ippsMulC_32f` | `vsip_cvmag_f`, `vsip_vlog10_f`, `vsip_vmul_f` | A |
| 5 | `l1_window_gen` | L1 | generic | 合成 | ~150 | `ippsWinHann_32f`, `ippsWinHamming_32f`, `ippsWinBlackman_32f`, `ippsWinKaiser_32f` | `vsip_vcreate_hanning/blackman/kaiser/cheby_f`（**无 Hamming**） | A/B |
| 6 | `l1_conv_corr` | L1 | generic | 合成 | ~180 | `ippsConvolve_32f`, `ippsCrossCorrNorm_32f` | `vsip_convolve1d_f`, `vsip_correlate1d_f` | **B**（原定 A） |
| 7 | `l2_aubio_fft` | L2 | audio | **真实** aubio 0.4.9 | ~400 | `ippsFFTInit_R_32f`, `ippsFFTFwd_RToCCS_32f`, `ippsFFTInv_CCSToR_32f`, `ippsAtan2_32f_A21` | `vsip_rcfftop_create_f`, `vsip_vatan2_f` | A |
| 8 | `l2_rubberband_fft` | L2 | audio | **真实** rubberband | 3193(整体) | `ippsFFTInit_R_32f/_C_32fc`, `ippsFFTFwd/Inv_*`, `ippsMalloc_8u` | `vsip_fft` + 自管 plan | A |
| 9 | `l2_saf_stft` | L2 | audio | **真实** SAF | 982 | `ippsFFTInit_R_32f/_C_32fc`, `ippsFFTFwd/Inv`, `ippsCopy_32f` | `vsip_rcfftop` + 窗 + `vsip_vsma_f` 重叠相加 | B |
| 10 | `l2_cil_fbp` | L2 | imaging | **真实** CIL | 178 | `ippsFFTInit_C_32fc`, `ippsFFTFwd/Inv_CToC_32fc`, `ippsMul_32f_I`, `ippsRealToCplx_32f`, `ippsCplxToReal_32fc` | `vsip_ccfftop`, `vsip_rcvmul_f`, 实复打包 | **B**（原定 A/B） |
| 11 | `l2_r8brain_fft` | L2 | audio | **真实** r8brain | 1099 | `ippsFFTInit_R_64f`, `ippsFFTFwd_RToPerm_64f`, `ippsFFTInv_PermToR_64f` | `vsip_rcfftop_create_d` + 排列约定 | B |
| 12 | `l2_tdfir_bank` | L2 | radar | 合成（HPEC TDFIR） | ~350 | `ippsFIRSR_32f` | `vsip_vdot_f` + 扩展缓冲（或 `vsip_conv1d_f`） | **B** |
| 13 | `l2_fdfir_overlap_save` | L2 | radar | 合成（HPEC FDFIR） | ~400 | FFT 族 + 复数逐点乘 | `vsip_ccfftop` + `vsip_cvmul_f` | B |
| 14 | `l2_cfar_detector` | L2 | radar | 合成（HPEC CFAR） | ~380 | `ippsSqr_32f`, `ippsSum_32f`, `ippsThreshold_32f` | `vsip_vsq_f`, `vsip_vsumval_f`, 比较 `vsip_vlgt_f` | B |
| 15 | `l2_dot_norm_stats` | L2 | generic | 合成 | ~250 | `ippsDotProd_32f`, `ippsNorm_L2_32f`, `ippsMean_32f`, `ippsStdDev_32f`, `ippsMax_32f`, `ippsMin_32f` | `vsip_vdot_f`, `vsip_vsumsqval_f`, `vsip_vmeanval_f`, `vsip_vmaxval_f` + `vsip_vbind_f`（stride/offset 子视图）；stddev 用 `vsip_svsub_f` 组合 | A |
| 16 | `l3_radar_pulse_compression` | L3 | radar | 合成仓库 | ~600 | FFT / Mul / Mag / Threshold / FIR | 全链路 VSIPL 组合 | B |
| 17 | `l3_comms_demod_frontend` | L3 | comms | 合成（SDR 接收前端） | 336 | `ippsRealToCplx_32f`, `ippsCplxToReal_32fc`, `ippsMul_32fc`, `ippsDotProd_32f`, `ippsMagnitude_32fc`, `ippsSqr_32f`, `ippsSum_32f`, `ippsMaxIndx_32f` | 分离实虚部绑 cblock + `vsip_cvmul_f` / `vsip_vdot_f` / `vsip_cvmag_f` / `vsip_vsq_f` / `vsip_vsumval_f` / `vsip_vmaxval_f` | **A**（原定 B；`ippsResamplePolyphaseFixed_32f` 已移出，见 §7.10） |
| 18 | `l3_spectrum_sensing` | L3 | spectrum | 合成（认知无线电频谱感知） | 266 | `ippsFFTGetSize_R_32f`, `ippsFFTInit_R_32f`, `ippsFFTFwd_RToCCS_32f`, `ippsWinHann_32f`, `ippsSet_32f`, `ippsCopy_32f`, `ippsMul_32f`, `ippsMagnitude_32fc`, `ippsSqr_32f`, `ippsAdd_32f`, `ippsMulC_32f`, `ippsMean_32f`, `ippsMaxIndx_32f`, `ippsMalloc_8u` | 手工窗 + `vsip_rcfftop_f` + `vsip_cvmag_f` / `vsip_vsq_f` / `vsip_vadd_f` / `vsip_svmul_f` / `vsip_vmeanval_f` / `vsip_vmaxval_f` / `vsip_vlge_f` + `vsip_vsumval_bl`（全链路组合） | B |
| 19 | `l3_audio_resampler` | L3 | audio | 合成（流式采样率转换 + 输出周期图） | 434 | `ippsDotProd_32f`（每个输出一次）、FFT 族、`ippsMagnitude_32fc`, `ippsSqr_32f`, `ippsAdd_32f`, `ippsMulC_32f`, `ippsMaxIndx_32f`, `ippsSum_32f`, `ippsCopy_32f` | `vsip_vdot_f`（时反分支 + 历史窗口视图）、`vsip_rcfftop_f`、`vsip_cvmag_f`/`vsip_vsq_f`/`vsip_vadd_f`/`vsip_svmul_f`、`vsip_vmaxval_f`/`vsip_vsumval_f`/`vsip_vdot_f`（ramp 求质心）；原型滤波器按头文件定义手写 | B |
| 20 | `l3_iir_eq_negative` | L3 | audio | 合成仓库 | ~400 | `ippsIIRInit_32f`, `ippsIIR_32f` | **无 IIR** → 直接差分方程 | **C** |

统计：L1 6 / L2 9 / L3 5；真实仓库 8、合成 12；A 9、B 10、C 1。

---

## 4. 每个任务的判分要点

### 4.1 通用判定（所有任务）

1. **构建门**：在只装了 VSIPL（jvsip）+ 标准 C/C++ 工具链的环境里 `cmake -S . -B build && cmake --build build` 成功。
2. **API 移除门**：产物 `nm -u` 中 `ipps*` / `ippi*` 未定义符号数 = 0；同时评测环境**不提供 IPP 头文件与库**，残留调用会直接链接失败。
3. **数值门**：隐藏输入上跑迁移后的实现，与 IPP 版 golden 输出比对。
   - float32：`rtol=1e-5, atol=1e-6`；float64：`rtol=1e-12, atol=1e-14`
   - FFT 类统一先归一到 `1/N` 逆变换约定再比
4. **行为门**：公开函数签名、错误码、边界行为（空输入、非 2 的幂、负值取对数）不变。

### 4.2 各任务的隐藏测试设计

| 任务 | 公开测试 | 隐藏测试 |
|---|---|---|
| 1 steamaudio | 实数 FFT 往返 | 非 2 的幂长度、plan 复用、原地/非原地、缩放 |
| 2 juce | order→size 映射 | 正逆变换配对、实数 FFT 的 CCS 打包布局 |
| 3 aubio dct | DCT-II 单帧 | 与直接按定义算的 DCT 对照（含 N=2..17 非 2 的幂） |
| 4 db_mag | 幅度谱 | 含 0 与负实部、dB 下限裁剪 |
| 5 window | Hann | 4 种窗的端点/对称性/等价定义（Hamming 必须手写） |
| 6 conv_corr | 线性卷积 | `bias` 选项、长度 > 输入、stride/子视图 |
| 7 aubio fft | 帧化实 FFT | 相位谱跨帧展开、hop size 变化 |
| 8 rubberband | 正逆变换 | 缩放常量 `getInvMulConst` 语义、块长 2..16 |
| 9 saf stft | 单帧 STFT | STFT→iSTFT 往返（COLA 条件下重构误差）、多通道 |
| 10 cil fbp | ramp 滤波一次 | 与 IPP 版逐点比对 + 频域滤波器对称性 |
| 11 r8brain | 64 点 real FFT | 零相位（ZP）重排、`multiplyBlocksZP` 正确性 |
| 12 tdfir | 单滤波器 | M 个滤波器 × 流式分块状态（跨调用延续）、ntaps=1 退化、block=1 |
| 13 fdfir | 小规模 | 与直接卷积等价（随机长度 + 补零边界） |
| 14 cfar | 单窗口 | 前导/后随单元数变化、虚警率统计、边界单元 |
| 15 stats | 全部 | 带 stride/offset 的子视图、单元素、含 NaN 行为 |
| 16 pulse compression | 端到端 | 多个目标距离/幅度下的峰值位置与旁瓣 |
| 17 comms | 端到端 | 多种调制、定时相位、抽取率可变 |
| 18 spectrum | 端到端 | 多帧、门限、检测统计（P_d/P_fa） |
| 19 resampler | 端到端 | 有理比（如 160/147）、群时延、频谱镜像抑制 |
| 20 iir_eq（C） | 端到端 | 与 IPP 版逐样本比对；**不要求**使用 VSIPL 任何 API |

### 4.3 golden 怎么来

- 真实仓库任务：用**打开 IPP 后端**的原始实现生成 golden（构建方法见筛选报告），保存输入 + 输出二进制。
- 合成任务：先写 IPP 版（作为 source），同一份测试程序分别链接 IPP 版与迁移版。
- 所有 golden 用固定随机种子生成，`numpy`/`C` 双份校验。

---

## 5. 关键负面发现（会改变原计划）

1. **IPP 没有 QR / SVD。** 已逐个 grep 头文件确认：`ipps.h` 里只有 `ippiEigenValsVecs*`（图像角点用），
   没有 `ippsQRDecomp*`、`ippsSVDecomp*`。因此 HPEC 的 QR/SVD 内核**不能**做成 IPP→VSIPL 任务——
   源侧根本没有 IPP 调用。它们只能来自 LAPACK/自写矩阵库→VSIPL，属于另一个场景。
2. **jvsip 没有 IIR。** 所以 IIR 任务只能定级为 C（手写差分方程），并且不能指望"用 VSIPL 解决"。
3. **jvsip 没有 Hamming 窗。** Hann/Blackman/Kaiser/Cheby 有，Hamming 要手写 —— 正好构成 A/B 混合任务。
4. **jvsip 没有多相重采样。** 只能 FIR + 插值组合（B）。
5. **图像算子（Open3D/OpenCV 的 `ippi*`）在 VSIPL 里完全没有对应**，只适合做负样本，本轮 20 个里先放 1 个（任务 20），
   图像类后续可加 1–2 个 C 任务，但不应超过总数 15%。
6. **jvsip 的 `vsip_firflt_f()` 不可用。** 读源码确认（`c_VSIP_src/vsip_firflt_f.c`）：重叠保留那段把第二个
   视图建在**核**所在 block 上（`h2->offset = h1->length`），越界读 → 段错误。因此所有 FIR 类任务的参考解
   都不能走 `vsip_fir_create_f` + `vsip_firflt_f`，要改成 `vsip_vdot_f` / `vsip_conv1d_f` 组合 —— 任务 12 已因此从 A 降为 B。
7. **jvsip 的 `vsip_valldestroy_f()` 对子视图会连带释放父 block。** `vsip_vbind_f()` 从不增加
   `block->bindings`，而 `vsip_blockdestroy_f()` 只对 `kind == 2`（派生）块放行，于是销毁子视图就把父视图的
   数据一起 free 掉了。子视图必须用 `vsip_vdestroy_f()`（只释放视图结构）。这条是典型"迁移后能编译、跑起来才崩"
   的坑，正好是评测里值得区分的失败模式。
8. **jvsip 的 `vsip_rcfftop` 在 N=2 时 SIGFPE。** 直接调用 `vsip_rcfftop_create_f(2,...)` +
   `vsip_rcfftop_f` 就崩（N=4 及以上正常）。所以任务 1 的用例集从 4 点起，不能拿 IPP 能做的 2 点 FFT 当用例。
   这类"目标库比源库弱"的边界必须写进用例设计，否则任务不可解。
9. **jvsip 的 `vsip.h` 没有 `extern "C"` 保护。** 从 C++ 包含它时所有 VSIPL 符号都会被 mangle，链接期才报
   undefined reference。C++ 源里必须写成 `extern "C" { #include <vsip.h> }`。
10. **`vsip_blockadmit_f()` 的返回值约定是反的。** 其他 jvsip 函数返回 0 表示成功，这个函数成功时返回 0、
    失败时返回 1（`vsip_blockadmit_f.c` 里 `blockadmit = 1` 出现在失败分支），按常规 `if (!ok)` 写法会把
    正常情况当失败。

---

## 6. 与 A/B 实验的配合

- **A 条件**（直接迁移）：任务目录只给 source + spec + VSIPL 头文件。
- **B 条件**（组件抽取优先）：额外给一个组件库（FFT plan 封装、buffer/view、窗、FIR 状态、重采样），
  组件库本身由抽取方法从这 20 个任务的**训练折**里产出。
- 为了不让 B 条件变成"抄答案"，组件库只包含**跨任务重复模式**（见设计文档 §4.3），
  不含任何任务的完整实现；并且 holdout 任务不出现在抽取语料里。

重复模式在 slate 中的分布（用于验证组件抽取有东西可抽）：

| 模式 | 出现任务 |
|---|---|
| FFT plan/执行封装 | 1,2,7,8,9,10,11,13,16,18,19 |
| 实数↔复数打包/CCS 布局 | 1,2,7,10,11,13,16 |
| 窗函数生成与应用 | 5,9,14,16,18 |
| 流式滤波器状态 | 12,17,19 |
| 向量统计与阈值 | 4,15,14,16,18 |
| 重采样/插值 | 19 |

---

## 7. 下一步

1. 按本表建 12 个合成任务的 IPP 基线（每个：`CMakeLists.txt` + `src/` + `tests/` + `golden/`）。
2. 把 8 个真实仓库任务打成 `task.yaml`（源快照 + 构建脚本 + 公开测试子集）。
3. 先做 4 个任务跑通端到端评测（建议 1、3、12、14，覆盖 A/B/C 与两种难度），
   验证 golden 生成、API 移除门、容差设置，再批量铺开。

### 7.1 状态：20 个任务已端到端跑通

| 任务 | fit | 基线 build | 迁移 build | 数值 | API 移除门 | 参考解 worst rel |
|---|---|---|---|---|---|---|
| 1 `l1_steamaudio_fft` | A | ok | ok | 7/7 | PASS（IPP 版 FAIL，8 个符号） | 1.0e-5 |
| 2 `l1_juce_fft` | A | ok | ok | 63/63 | PASS（IPP 版 FAIL，10 个符号） | 1.24e-5 |
| 3 `l1_aubio_dct` | B | ok | ok | 44/44 | PASS（IPP 版 FAIL，8 个符号） | 8.35e-7 |
| 4 `l1_vec_db_mag` | A | ok | ok | 5/5 | PASS（IPP 版 FAIL，7 个符号） | 1.03e-6 |
| 5 `l1_window_gen` | B（原定 A/B） | ok | ok | 9/9 | PASS（IPP 版 FAIL，4 个符号） | 1.37e-6 |
| 6 `l1_conv_corr` | B（原定 A） | ok | ok | 15/15 | PASS（IPP 版 FAIL，6 个符号） | 7.15e-7 |
| 7 `l2_aubio_fft` | A | ok | ok | 41/41 | PASS（IPP 版 FAIL，9 个符号） | 6.62e-6 |
| 8 `l2_rubberband_fft` | A | ok | ok | 162/162 | PASS（IPP 版 FAIL，24 个符号） | 3.82e-6 |
| 9 `l2_saf_stft` | B | ok | ok | 66/66 | PASS（IPP 版 FAIL，18 个符号） | 6.557e-7 |
| 10 `l2_cil_fbp` | B（原定 A/B） | ok | ok | 10/10 | PASS（IPP 版 FAIL，13 个符号） | 2.124e-7 |
| 11 `l2_r8brain_fft` | B | ok | ok | 16/16 | PASS（IPP 版 FAIL，5 个符号） | 7.772e-16 |
| 12 `l2_tdfir_bank` | B（原定 A） | ok | ok | 5/5 | PASS（IPP 版 FAIL，7 个符号） | 2.8e-6 |
| 13 `l2_fdfir_overlap_save` | B | ok | ok | 11/11 | PASS（IPP 版 FAIL，6 个符号） | 4.77e-7 |
| 14 `l2_cfar_detector` | B | ok | ok | 5/5，0 mismatch | PASS（IPP 版 FAIL，10 个符号） | 判定精确一致 |
| 15 `l2_dot_norm_stats` | A | ok | ok | 6/6 | PASS（IPP 版 FAIL，8 个符号） | 4.2e-7 |
| 16 `l3_radar_pulse_compression` | B | ok | ok | 8/8 | PASS（IPP 版 FAIL，14 个符号） | 7.05e-7 |
| 17 `l3_comms_demod_frontend` | A（原定 B） | ok | ok | 8/8 | PASS（IPP 版 FAIL，9 个符号） | 3.576e-7 |
| 18 `l3_spectrum_sensing` | B | ok | ok | 8/8 | PASS（IPP 版 FAIL，14 个符号） | 2.514e-7 |
| 19 `l3_audio_resampler` | B | ok | ok | 8/8 | PASS（IPP 版 FAIL，12 个符号） | 6.0e-7（聚合量 1.436e-5） |
| 20 `l3_iir_eq_negative` | C | ok | ok（不链接 VSIPL） | 5/5 | PASS（IPP 版 FAIL，6 个符号） | 1.6e-6 |

二十个包结构一致（`task.yaml` + `CMakeLists.txt` + `include/` + `src/` + `gold/` + `test/` + `harness/`），
`harness/run_hidden.py` 走"配置→构建→跑隐藏用例→输出 JSON"的同一路径，`check_api_removal.sh` 用 `nm`
扫 `ipps*/ippi*`（从任务 9 起正则放宽为 `^ipp`，否则 `ippMalloc`/`ippFree` 会漏网）。
评测器侧已验证：把参考解拷进 `src/` 当提交，`run_hidden.py` 返回 `tests: pass`。

（任务 19 顺带修了 `run_hidden.py` 的一个解析缺陷：`worst_rel` 原来用
`re.search(r"worst_rel=...", out)` 在全量输出里取**第一个**匹配，实际拿到的是 case 0 的值，
而真正的最大值在 `SUMMARY` 行。20 个包的该行已统一改成先匹配 `SUMMARY[^\n]*worst_rel=`，
匹配不到再退回旧式；只影响上报数字，不影响构建与判定。）

（同时补了两处 `task.yaml` 的 YAML 语法缺陷：`l1_juce_fft` 与 `l2_r8brain_fft` 的 `hidden_tests.cases`
里有多行纯量条目带 `": "`，会被解析成映射键而报 `ScannerError`；已改成双引号字符串。现在 20 个
`task.yaml` 全部可被 `yaml.safe_load` 解析，且 `task_id` 与目录名一致。）

### 7.2 任务 12 `l2_tdfir_bank` 详情

任务包在 `ipp_vsipl_tasks/l2_tdfir_bank/`，三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（4.6e-8），隐藏用例 5/5 |
| golden 生成 | `golden_gen <hidden-dir>` | 5 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok |
| 数值 | `hidden_test <hidden-dir>` | 5/5 PASS，worst_rel 2.8e-6（101 taps） |
| API 移除 | `check_api_removal.sh libtdfir.a` | 迁移版 PASS；IPP 版 FAIL（7 个 `ipps*` 符号） |

参考解 `gold/tdfir_vsipl.c` 用 `vsip_vdot_f` + 扩展缓冲实现流式 FIR（jvsip 的 `vsip_firflt_f` 不可用），
子视图用 `vsip_vdestroy_f` 释放。容差定为 float32 rtol 1e-4 / atol 1e-6：结构性错误是 O(1)，
而 float32 累加顺序差异在 101 抽头用例上只有 2.8e-6，留约 35 倍余量。

### 7.3 任务 15 `l2_dot_norm_stats` 详情

这是唯一一个"VSIPL 比 IPP 更省事"的任务：IPP 没有带 stride 的向量原语（`ipps.h` 里只有连续
`*_32f` 形式），源实现必须先把抽取窗口 gather 到两块临时缓冲；VSIPL 用
`vsip_blockbind_f` + `vsip_blockadmit_f` 把调用者的内存挂上，再用
`vsip_vbind_f(block, offset, stride, n)` 直接切片，零拷贝。

| 门 | 结果 |
|---|---|
| 基线（IPP）构建 + `public_test` | PASS |
| golden 生成（6 例） | dot/norm/mean/stddev/vmax/vmin 全部落盘 |
| 迁移后构建 + 隐藏用例 | build ok，6/6 PASS，worst_rel 4.2e-7 |
| API 移除 | 迁移版 PASS；IPP 版 FAIL（8 个 `ipps*` 符号） |
| 默认（未迁移）构建 | 按预期失败：`ipp.h` 不可用 |

两个新的 IPP 语义发现（已写进 `task.yaml` 的 source note）：

1. `ippsStdDev_32f` 用样本分母 n−1；n=1 时返回 `ippStsSizeErr` 且**不写结果**
   （不是返回 0）——基线包装层显式定义单样本 stddev 为 0，参考解照此实现。
2. `ippsMax_32f` / `ippsMin_32f` 忽略 NaN 样本，而 norm/mean/dot 传播 NaN；
   jvsip 的 `vsip_vmaxval_f` / `vsip_vminval_f` 用 `if (r < *ap)` 比较，NaN 语义一致
   （但首元素是 NaN 时 `r` 会一直是 NaN，所以隐藏用例把 NaN 放在第 100 个样本）。

stddev 是唯一需要组合的字段：`vsip_svsub_f(mean, a, dev)`（得到 mean−a，平方和不在乎符号）
+ `vsip_vsumsqval_f(dev)`，再 `sqrt(ss/(n-1))`——比直接用 `sumsq − n·mean²` 少一次灾难性抵消。

### 7.4 任务 2 / 3 / 4 / 5 / 6 / 13 详情

这六个包同样走完整的三条门（基线 IPP 构建 → golden 落盘 → 迁移构建 → 隐藏用例 → `nm` 扫描），
评测器侧都验过"把 `gold/` 拷进 `src/` 后 `run_hidden.py` 返回 `tests: pass`"。

**任务 2 `l1_juce_fft`（fit A，63/63，worst_rel 1.24e-5）**

JUCE 9.0.5 的 `juce::dsp::FFT` 是引擎注册表 + 标量 fallback，包只保留 IPP 引擎（原文件 priority 9 的那段），
公开头 `juce_FFT.h` 原样保留 order→size、复数正逆变换、实序列正逆变换与幅度谱四个入口。三个约定不在头文件里：

1. **逆变换缩放**来自 plan 上的 `IPP_FFT_DIV_INV_BY_N`——迁移到 jvsip 时放进
   `vsip_ccfftop_create_f`/`vsip_crfftop_create_f` 的 scale 参数（正变换 1.0、逆变换 1/N），漏掉就整体放大 N 倍。
2. **实序列负频率半区是引擎手填的**：`out[i] = conj(out[n-i])`，`i ≥ n/2`；幅度谱再把前 `size`（或 `size/2+1`）个
   float 位置换成模值、其余清零。这层后处理必须一并迁移，隐藏用例对整段 2N 浮点逐点比对。
3. **IPP 2021 的 CCS 其实是自然交错布局**：`ippsFFTFwd_RToCCS_32f_I` 实际写出 `n/2+1` 个自然复数
   （`n+2` 个 float，实测 `f0..f8 = R0,I0,R1,I1,...,R4`），不是函数名暗示的 `R0,R1,I1,...` 打包。照文档假设搬移会错位。

**实现层的坑**：jvsip 的 FFT plan 在长度 < 4 时直接崩溃——长度 1 在 plan 创建阶段挂死，长度 2/3 在 twiddle 初始化里
SIGSEGV——而 JUCE 的契约从 order 0（1 点）开始。参考解对 1..3 点用 double 直接 DFT，4 点起才建 VSIPL plan。
公开测试覆盖 order 0..5，所以这个崩溃在公开测试里就能看见，不会拖到隐藏评测。

隐藏用例按 order × 操作铺开（0/1/2/3/4/5/6/8/10 × 7 种操作），其中 order 0/1/2 专门压 1/2/4 点的退化路径。

**任务 3 `l1_aubio_dct`（fit B，44/44，worst_rel 8.35e-7）**

aubio 0.4.9 的 IPP 后端（`src/spectral/dct_ipp.c`）只做 spec 生命周期，难点全在归一化：
IPP 的 DCT 本身就是正交归一（等于 MATLAB `dct()`/`idct()`），而 VSIPL 没有 DCT，
必须用长度为 `M = 2N` 的复数 FFT 重组，且必须保持同一套系数。参考解：

1. **DCT-II**：偶延拓 `v = [x[0..N−1], x[N−1..0]]` → `FFT_M(v)` →
   `X[k] = (c_k/2)·Re{Y[k]·e^{−iπk/(2N)}}`，`c_0 = sqrt(1/N)`、`c_k = sqrt(2/N)`。单次 FFT，无额外缩放（正变换 plan 取 1.0）。
2. **DCT-III**：先按 `c_k` 加权、乘 `e^{+iπk/(2N)}`，手工镜像成 Hermitian 谱
   （`B[k]` 与 `B[M−k] = conj(B[k])`，`k ≥ 1`；`B[N] = 0`），用 `1/M` 的逆变换 plan，
   最后 `x[n] = (M·Re{idft[n]} + a_0)/2`——镜像把 `a_0` 算了两遍，DC 项又多算一遍，必须减回来。
3. **任意长度**：jvsip 的 `vsip_ccfftop` 对非 2 的幂（100、257）同样可用，用例覆盖 1..17 全长度
   （含 N=1 的恒等退化）、32/64/100/257/1024。

把三处归一化弄错任一处的表现：漏 `c_k` 是 O(1) 相对误差，漏 `1/M` 或那个 `/2` 是 O(N)，
旋转符号翻转则镜像频谱——1e-4 的相对容差对 8.3e-7 的实测值留了两个数量级余量。

**任务 4 `l1_vec_db_mag`（fit A，5/5，worst_rel 1.03e-6）**

`20*log10(max(|x|,floor)) + offset`。迁移面上是教科书式的一对一：
`ippsMagnitude_32f → vsip_cvmag_f`、`ippsThreshold_LTVal_32f(floor) → vsip_vclip_f(mag,floor,FLT_MAX,floor,FLT_MAX,mag)`、
`ippsLog10_32f_A21 → vsip_vlog10_f`、`ippsMulC_32f(20)/ippsAddC_32f(offset) → vsip_svmul_f/vsip_svadd_f`。
两个链接层面的发现写进了 `task.yaml`：`ippsLog10_32f_A21` 在 **libippvm.so** 里（不在 libipps），
基线必须同时链接 `libipps/libippvm/libippcore`；VSIPL 侧没有"先取实部再算幅度"的捷径，必须
`vsip_vcmplx_f` 把 re/im 两个视图拼成复向量。隐藏用例特意注入零样本、1e-12 小样本和 3+4i 定点样本，
把 floor 分支和幅度分支都覆盖到。

**任务 5 `l1_window_gen`（fit B，9/9，worst_rel 1.37e-6）**

9 个隐藏用例加上公开自检，把 IPP 的窗口约定钉死在实测上，而不是照文档假设：

1. Blackman 是 `(0.5+a/2) − 0.5cos(t) − (a/2)cos(2t)`——教科书中 `+a/2` 的那一项在 IPP 里是**反号**的
   （a=0 时退化成 Hann，所以只在 a≠0 的用例上暴露）；
2. Kaiser 的 alpha 以**采样点**为单位，beta = a·(n−1)/2；
3. Kaiser 在 beta > 38 时返回 `ippStsHugeWinErr`（"Kaiser window is too big"），
   Hann/Hamming/Blackman 在 n < 3 时返回 `ippStsSizeErr`。

jvsip 自带的窗口生成器一个都用不了：`vcreate_hanning_f` 是 `0.5(1−cos(2π(n+1)/(N+1)))`（相位整体平移）、
`vcreate_blackman_f` 是教科书 0.42/0.5/0.08（只在 alpha=0 时等于 IPP）、`vcreate_kaiser_f` 收的是原始 beta
且单精度 Bessel 级数在 beta≳20 时溢出成 NaN。参考解因此自己按 double 写窗，只用 `vsip_vmul_f` 做窗×信号的
逐点乘。用例覆盖了 beta=37.5、beta=38.0（恰好在上限上）和 n=1 的退化情形。

**任务 6 `l1_conv_corr`（fit B，原定 A；15/15，worst_rel 7.15e-7）**

契约把约定写死：`full[i]=Σ h[j]x[i−j]`、`SAME` 取 `full[i+nh/2]`、
`corr y[i]=Σ h[j]x[j+i−(nh−1)]`，bias 选 raw 与"除以重叠样本数"两种。三个坑：

1. **lag 方向**：`ippsCrossCorrNorm_32f` 的输出按 `sum(k) src1[k]·src2[k+lag]` 计算，即**第一个操作数不动**，
   与"核相对数据滑动"的天然相关是镜像关系。源码把 `h` 当 src1、`x` 当 src2，`lowLag=−(nh−1)` 时
   `y[0]` 恰好是 lag −(nh−1)；照抄参数顺序会整体反序，而隐藏用例的核都是非对称的，反序直接 O(1) 误差。
2. **SAME 偏移**：jvsip 的 `vsip_convolve1d_f` 从 `full[nh/2]` 起取（整数除法），偶数核是 `nh/2` 而不是
   教科书的 `(nh−1)/2`，实测 nh=2/4 都是 nh/2。
3. **jvsip 的 UNBIASED 缺陷**：`VI_vunbiasfull_f` 在核比数据长时按**核**的升/降重叠数走，
   把平台段除以 nh 而不是 nx（实测 nh=8、nx=6 在 lag −1/0 用了 7 和 8，正确值是 6），
   误差 2.9e-2。参考解在 `nh > nx` 时退回 `VSIP_BIASED` 再按精确重叠数除，这条分支正是把 fit 从 A 降到 B 的原因。
   另外 VSIPL 的视图直接挂调用者内存，strided 入口不需要 gather 缓冲（IPP 需要）。

**任务 13 `l2_fdfir_overlap_save`（fit B，11/11，worst_rel 4.77e-7）**

重叠保留法频域 FIR，create/apply/destroy 生命周期，`nfft` 为 2 的幂且 `nfft >= ntaps`，
块长 `nfft-ntaps+1`。VSIPL 没有 overlap-save 对象，参考解用 `vsip_ccfftop` + 复数逐点乘重组：

1. **缩放位置**：IPP 把除法写进 spec（`IPP_FFT_DIV_INV_BY_N`），jvsip 把缩放做
   `vsip_ccfftop_create_f` 的参数——逆变换 plan 取 `1/nfft`、正变换取 `1.0`。
   漏掉这一步输出会整体放大 nfft 倍。
2. **逐点乘不是 `vsip_vmmul_f`**：`vmmul` 是向量×矩阵（签名收 `vsip_mview_f`），
   对复向量视图根本编译不过；复向量逐点乘是 `vsip_cvmul_f`（`cvmmul` 又是矩阵版）。
3. **窗口对齐**：循环卷积的有效输出是每个块最后 `block` 个样本，
   `y[pos+k] = time[ntaps-1+k]`；错开 `ntaps-1` 仍然像个滤波器，只能靠与直接卷积比对抓出来。

隐藏用例覆盖块长 1、块长 2、`nx < block`、单样本（只有补零边界）、exact multiple、
`ntaps=1` 退化以及 1000 点长输入。注意这条数值门**无法**区分"真的用 FFT"和"直接卷积重写"，
算法保真度不在本基准的判分范围内。

### 7.5 任务 7 `l2_aubio_fft` 详情

aubio 0.4.9 的 IPP 后端不是单个内核，而是整个 `fft` 对象：create/destroy 生命周期、一对不缩放的实数 FFT、
`compspec` 打包布局，以及 `do/do_complex/rdo/rdo_complex/get_spectrum/get_realimag/get_phas/get_norm/get_imag/get_real`
十个入口。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（1.5e-6），隐藏用例 41/41 |
| golden 生成 | `golden_gen <hidden-dir>` | 41 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 41/41 PASS，worst_rel 6.62e-6（n=1024） |
| API 移除 | `check_api_removal.sh libaubiofft.a` | 迁移版 PASS；IPP 版 FAIL（9 个 `ipps*` 符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |

数值本身好对（`rcfft`/`crfft` 直接映射），难点全在约定上：

1. **缩放分两处**：IPP 用 `IPP_FFT_NODIV_BY_ANY`，逆变换后自己 `ippsMulC_32f(1/winsize)`。
   迁移后正变换 plan 取 scale 1.0、逆变换之后 `vsip_svmul_f(1/n)`；两个 plan 都写 1.0 会让逆变换放大 n 倍。
2. **打包布局**：`vsip_rcfftop_f` 给出 k=0..n/2 的自然 (re, im)，而 `compspec` 是
   `[r0, r1..r_{n/2}, i_{n/2-1}..i1]`，必须用 `vsip_cvget_f`/`vsip_cvput_f` 逐点重排；直接 `memcpy` 会把实部虚部搅在一起。
3. **DC 与 Nyquist 的相位不是 atan2**：aubio 在 `phas[0]` 和 `phas[m-1]` 只写 0 或 π（看符号），
   中间才用 `atan2(Im, Re)`。照 atan2 写，负数 DC 会得到 ±π 之外的 0，逆变换符号就错。
4. **IPP 的 `sizeInit`/`sizeBuffer` 可能为 0**：本机上 order 3/4/5（n=8/16/32）时两者都是 0，
   `ippsMalloc_8u(0)` 返回 NULL，原样照搬会让构造函数对小尺寸返回 NULL。基线改为按 `>0` 才分配，
   与 IPP 文档"传 NULL 表示不需要"一致；这个修复已写进 `task.yaml` 的 source note。
5. **`ippsAtan2_32f_A21` 的参数序**是 (y, x)，且 aubio 先把虚部搬到连续缓冲再还原；
   `vsip_vatan2_f(y, x, out)` 的语义相同，那个搬移只是为了让 IPP 拿到连续向量，迁移后可以不要。

隐藏用例：winsize 8/16/32/64/128/256/1024 × 5 种操作（复数谱、极坐标谱、经 norm/phas 的往返、
经 compspec 的往返、`get_realimag`），其中 winsize 64 用同一个对象连做三帧；另加 6 个非法尺寸
（2/4/5/6/12/1000）要求返回 NULL。相位槽按 mod 2π 比较，其他按相对误差。
`get_realimag` 的用例对正确实现恒为 0 误差（norm/phas 来自同一份落盘数据），保留它只是为了卡住访问器布局。

### 7.6 任务 8 `l2_rubberband_fft` 详情

rubberband 4.0.0 的 `src/common/FFT.cpp` 是 3193 行的多后端文件（IPP / FFTW / KissFFT / vDSP / Sleef / 内置 DFT），
包只抽出一个完整后端：`D_IPP`（float + double 共 16 个入口，懒初始化两套 plan）、`D_DFT`（任意长度的直接 DFT 兜底）
和 `FFT` 包装层（实现选择、异常检查）。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（6.6e-7），隐藏用例 162/162 |
| golden 生成 | `golden_gen <hidden-dir>` | 162 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 162/162 PASS，worst_rel 3.82e-6（按用例峰值归一） |
| API 移除 | `check_api_removal.sh librubberbandfft.a` | 迁移版 PASS；IPP 版 FAIL（24 个 `ipps*` 符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipps.h` 不可用 |

这个包的价值在于"组件"而不只是"内核"：

1. **注册表 + 兜底**：只有"偶数、2 的幂、且 ≥4"的尺寸走 FFT 后端，其余（2/3/5/6/100 …）走同文件里的直接 DFT。
   隐藏用例两类尺寸都覆盖；直接 DFT 那 80 个用例在基线/参考解之间逐位相同——迁移时误改这条路径会立刻暴露。
2. **布局是自然交错，不是文档里的 CCS**：本机 IPP 的 `ippsFFTFwd_RToCCS_32f/64f` 实测写出
   `[R0,I0,R1,I1,...]`（`n+2` 个 float），正好和 `packFloat/unpackFloat` 假设一致。公开头里"CCS"的说法与
   实现不符，包内头文件已按可观察行为改写；隐藏用例对 `n+2` 个位置逐点比对。
3. **不缩放的正逆对**：IPP 用 `IPP_FFT_NODIV_BY_ANY`，所以"正变换 + 逆变换 = n·x"。jvsip 两个 plan 都取 scale 1.0，
   并在 `vsip_vcopyfrom_user_*` 的 const 源指针上做一次 `const_cast`（jvsip 签名收可变指针）。
4. **float 的逆变换误差尺度**：n=1024 的不缩放逆变换输出量级 ~1000，float32 舍入绝对误差 ~1e-4。
   早期按逐点相对误差判分会把正确解判错（1.46e-4 > 1e-4）；改成"相对该用例峰值"（float 1e-4、double 1e-9），
   相位槽仍用绝对 1e-4 rad。结构性错误（少 1/n、re/im 交错错位、atan2 参数反）是 O(1)·峰值，余量仍然充足。
5. **异常契约**：`FFT(size<2)` 抛 `InvalidSize`，空指针抛 `NullArgument`；包装层在基线里显式实现，
   参考解保留同一行为（这两条是包内对原文件的唯一增补，已写进 task.yaml 的 source note）。

### 7.7 任务 9 `l2_saf_stft` 详情

SAF v1.3.5 的 `framework/modules/saf_utilities/saf_utility_fft.c`（982 行）是一整个 FFT/STFT 工具模块：
实数与复数两对变换（按尺寸自动在 `ippsFFT*` 和 `ippsDFT*` 之间切换）、Hann 窗加历史 hop 的 STFT、
`flushBuffers`/`channelChange`，以及 `fftconv`/`fftfilt`/`hilbert`/`getUniformFreqVector`。
包内保留了全部引擎无关的上层代码，只把两个变换引擎换成 VSIPL —— 这是"抽组件再换引擎"的干净样本。
三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（13/13），隐藏用例 66/66 |
| golden 生成 | `golden_gen <hidden-dir>` | 66 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 66/66 PASS，worst_rel 6.557e-07（n=1000 实变换往返） |
| API 移除 | `check_api_removal.sh libsafft.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（18 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipps.h` 不可用 |

隐藏用例分 16 类操作共 66 个：实变换 n=8/64/1024（`ippsFFT` 路径）与 6/100/1000（`ippsDFT` 路径）
各做前向/逆向/往返；复变换 n=4/8/32/100/1000/1024 同样三种；5 组 STFT 配置
（`win/hop` = 256/256、128/64、64/16、32/32、100/50，含 2 进 1 出与两种 FD 布局）各做前向/逆向/往返；
再加有状态重叠相加、`flushBuffers`、`channelChange` 三个多块序列；`fftconv` 3 例、`fftfilt` 2 例、
`hilbert` 3 例、`getUniformFreqVector` 2 例。每例按自身峰值归一（下限 1.0）比较，rtol 1e-4。

打包时踩到的四个坑都写进了 `task.yaml` 的 `gold_notes`：

1. **IPP 2021 的 `RToCCS` 不是文档里的 CCS**：`ippsFFTFwd_RToCCS_32f` 和 `ippsDFTFwd_RToCCS_32f`
   实测都写自然交错半谱 `[R0,I0,R1,I1,...]`（`n+2` 个 float），`ippsFFTInv_CCSToR_32f` 也按这个布局读回。
   基线和参考解因此都按 "自然交错 + 逆向 1/N" 实现，`saf_utility_fft.h` 的注释按可观察行为写。
2. **jvsip 的实数 plan 不吃 scale**：`vsip_rcfftop_create_f`/`vsip_crfftop_create_f` 在
   `VI_rcfftop_f_def.h`/`VI_crfftop_f_def.h` 里根本没读 `->scale`，所以逆变换的 1/N 必须自己乘；
   `vsip_ccfftop_create_f` 才真正使用 scale。参考解对两者都显式乘 1/N，行为统一。
3. **只有 Hermitian 半谱在实数逆变换里有定义**：第一版隐藏用例给逆向喂任意随机复谱，op=7（STFT_BWD）
   直接 11 例失败、worst_rel 1.37e-1。单独探针确认：I0 或 I(Nyquist) 非零时 IPP 直接丢弃虚部，
   jvsip 则给出另一种（可说是坏掉的）结果。改成只给 Hermitian 谱（bin 0 与 Nyquist 虚部置零）后，
   op=7 修好，同时暴露 op=1（RFFT_BWD）同样有 6 例失败，一起修掉。这条属于"契约边界"，已写进 `task.yaml`。
4. **两个越界/尺寸陷阱**：过采样 STFT 前向会从最后一个 hop 起读满一个窗，所以调用方缓冲要
   `framesize + win` 长（包内 `saf_inlen` 就是这么定的）；2 进 1 出的配置前向写 `nchin` 个通道，
   频域数组必须按 `max(nchin, nchout)` 申请，否则写穿。

另外，`check_api_removal.sh` 在原模板里扫 `^(ipps|ippi|ippvm|ippcore)`，匹配不到 `ippMalloc`/`ippFree`；
本包起放宽为 `^ipp`（已确认参考解产物 0 命中）。

### 7.8 任务 10 `l2_cil_fbp` 详情

CIL 的 `src/Core/FBP_filtering.cpp`（178 行）是 FBP 重建前的投影滤波：每行探测器数据做一次"正变换 → 乘实数滤波器 → 逆变换"。
为了省一半变换，两行数据被打包进一个复向量的实部/虚部，零填充到 `2^order` 并居中偏移。
源码是 C++（Python 经 ctypes 调用），包内以 C99 复现，只做了三处不可观察的改动：`(Ipp32fc){...}` 显式聚合字面量、
去掉 OpenMP pragma（并行体每次迭代处理一对独立行，`single` 块处理奇数尾行，顺序执行结果不变）、
以及保留原文件里那个声明了却没用上的 `int flag = IPP_FFT_NODIV_BY_ANY;`。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（8/8），隐藏用例 10/10 |
| golden 生成 | `golden_gen <hidden-dir>` | 10 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 10/10 PASS，worst_rel 2.124e-07（avh，奇行数） |
| API 移除 | `check_api_removal.sh libfbp.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（13 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |

10 个隐藏用例覆盖 avh / vah 两种数据布局各 5 个：常规尺寸、奇数行数（走尾行路径）、单投影、
`2^5` 的小变换、以及 `pix_y=1` 只剩尾行的情况。滤波器不是白噪声，而是"DC 在前、正频率在后、负频率最后"的低通响应——
随机谱的动态范围会把打包顺序错误掩盖掉，低通不会。权重为正且逐行（avh）或逐块（vah）变化。

值得记下的约定：

1. **缩放是前向 1/N、逆向不缩放**：原文件声明了 `IPP_FFT_NODIV_BY_ANY` 却没用，GetSize/Init 都传 `IPP_FFT_DIV_FWD_BY_N`。
   参考解两个 plan 都用 scale 1.0，把 1/N 折进滤波器 `filter[k]/N`，与 IPP 的算术顺序一致，也不依赖 plan scale。
2. **jvsip 的 `vsip_ccfftop_f` 确实使用 plan scale**（单独验证过：前向 0.5、逆向 1.0 得到 `0.5·N·x`），
   这和实数 plan 忽略 scale 的行为不同；但参考解仍选择不依赖它。
3. **实部/虚部打包不是 memcpy**：两行数据在 `offset` 处交错写入复向量，再交错读出；
   `ippsRealToCplx_32f` 接受 NULL 虚部源，这就是奇数尾行"虚部为零"的实现方式，VSIPL 侧对应 `vsip_cmplx_f(re,0)`。
4. **两个入口的维度顺序不同**：`avh` 是 `(num_proj, pix_y, pix_x)`，`vah` 是 `(pix_y, num_proj, pix_x)`；
   写隐藏用例和调用侧时最易错的一处，公开测试的两个布局用例就是用来卡这个的。
5. **权重乘的是实数数据**：`vsip_vmul_f` 作用在 `vsip_blockbind_f` + `vsip_blockadmit_f(block,0)` 绑定的调用方缓冲上；
   jvsip 的 bound block 是 `VSIP_USER_BLOCK`，`vsip_blockdestroy_f` 不会释放用户内存。

### 7.9 任务 11 `l2_r8brain_fft` 详情

r8brain 的 `CDSPRealFFT.h`（1099 行）是幂次重采样器的变换底座：`CDSPRealFFTSetup` 存一个块长的变换规格，
`CDSPRealFFT` 是每次使用的变换对象（经 `CDSPRealFFTKeeper` 从全局池取），`calcMinPhaseTransform()`
在它上面做倒谱域最小相位滤波器设计。包内保留 IPP 分支（`R8B_IPP=1`），去掉 PFFFT / Ooura 分支，
并把后端状态（`IppsFFTSpec_R_64f`、规格缓冲、工作缓冲）藏到不透明指针后面，使头文件不含任何 IPP 类型；
上游那条静态链表池换成 `std::map` + `std::mutex`。两处都只是打包方式，类 API、算法和算术全部不变。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（17/17），隐藏用例 16/16（与自身 golden 逐位一致） |
| golden 生成 | `golden_gen <hidden-dir>` | 16 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 16/16 PASS，worst_rel 7.772e-16，DC 群延迟绝对误差 2.98e-13 |
| API 移除 | `check_api_removal.sh libr8bfft.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（5 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |

16 个隐藏用例覆盖 forward（bits 4/10）、inverse（bits 4/8/12）、正逆往返乘 `InvMulConst`（bits 6/12）、
`multiplyBlocks` 出-of-place（bits 8/3）与原地（bits 5）、`multiplyBlocksZP`（bits 8）、`convertToZP`、
`setBinNyquist`、`calcMinPhaseTransform`（kernel 24 / LenMult 2 / DoFinalMul true 与 kernel 40 / LenMult 4 / false，
含它输出的 DC 群延迟）、以及 keeper 复用（同长度连着取两次，两次变换都要对）。
inverse 和块乘法用例的输入不是随机数，而是基线自己的 forward 输出并原样存进容器，候选拿到的就是基线消费的那个 Perm 块。

值得记下的约定：

1. **Perm 布局是这道题的全部难点**：`p[0]=Re X[0]`、`p[1]=Re X[N/2]`、`p[2k]=Re X[k]`、`p[2k+1]=Im X[k]`。
   jvsip 的 `vsip_rcfftop_d` / `vsip_crfftop_d` 是自然半谱（N/2+1 个复值，元素 k 就是 X[k]），
   所以正向要 scatter、逆向要 gather；变换本身只有一次调用。
2. **两侧都不缩放**：IPP 用 `IPP_FFT_NODIV_BY_ANY` 初始化，正向是裸 DFT、逆向是 N 倍裸 IDFT；
   jvsip 的实数 plan 本来就忽略 plan scale（单独验证过：scale 0.5 的 rcfft 仍输出不缩放的 DFT），
   两个 plan 都建 scale 1.0 即与 IPP 一致。调用方自己乘 `getInvMulConst()=1/N`，中间任何一步补 1/N 都会破坏缩放。
3. **`setBinNyquist` 写的是 `p[1]`**（Perm 序下的 Nyquist 实部），不是自然布局里第 N/2 个元素的位置；
   写错只影响一个 bin，所以单列了一个用例。
4. **块乘法和 `convertToZP` 不需要 VSIPL**：它们是 Perm 序上的标量算术（成对复数乘、`p[2k+1]=p[2k]`），
   迁移时要原样保留；`multiplyBlocksZP` 更是逐元素实数乘。
5. **DC 群延迟是数值上最松的量**：`calcFIRFilterGroupDelay` 用间隔 2e-9 的两点相位差做有限差分，
   会把变换的最后几位放大 ~1e9 倍。隐藏测试因此把 kernel 系数按 peak-relative 1e-9 卡，群延迟单独按绝对 1e-2 卡。
6. **keeper 池必须按长度归还**：用例连着取两次同长度的 keeper 并比较两次 forward 的结果。
   `vsip_blockbind_d` + `vsip_blockadmit_d(b,0)` 绑定调用方缓冲实现原地变换，`vsip_blockdestroy_d` 不释放用户内存，
   所有权仍归调用方。

### 7.10 任务 17 `l3_comms_demod_frontend` 详情

合成仓库，形状照真实 SDR 接收前端：复数 NCO 混频 → 抽取复 FIR → 每块幅度/功率统计，全部流式，
输入怎么分块不能改变输出。组件本身只有 336 行（头文件 59 + 源 277），因为每一级都是一次向量调用；
L3 指的是"整链端到端"的形态（隐藏用例跑完整 session），不是体量。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（15/15），隐藏用例 8/8（与自身 golden 逐位一致） |
| golden 生成 | `golden_gen <hidden-dir>` | 8 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 8/8 PASS，worst_rel 3.576e-7 |
| API 移除 | `check_api_removal.sh libdemfront.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（9 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |

8 个隐藏用例是 5 个不同配置，其中前三个是**同一段流**分别按整块、逐样本（block 1）、37 样本分块喂进去：
分块敏感的实现在这里必挂。另外覆盖 M=1（不抽取）、奇数长度（nco 5 / decim 3 / taps 5 / 301 样本）、
长 session（1024 样本）、NCO 表比 M*ntaps 还短（nco 3 / decim 2 / taps 32）、以及输出很少的粗尾块（100 样本 / block 13）。
容器里带 NCO 表、抽头、输入平面、基线完整输出，以及该输出的 mean_power / peak / peak_index。

**范围决策**：原计划把 `ippsResamplePolyphaseFixed_32f` 放进这道题，实际做的时候去掉了。
它的滤波器系数和输出时序由 IPP 内部 `ippsResamplePolyphaseFixedInit` 决定，公开头文件里没有规定，
所以候选没有任何办法复现那组数字——这样的用例测的不是迁移，而是猜。这里换成显式抽头的抽取 FIR，
多相/重采样的活留给任务 19。`task.yaml` 的 `source.scope_note` 记了这条。

值得记下的约定：

1. **fit 从 B 改判为 A**：9 个 IPP 符号里，`ippsRealToCplx_32f` / `ippsCplxToReal_32fc` 在 VSIPL 侧不是"另一个调用"，
   而是根本不需要——VSIPL 本来就是分离实虚部，`vsip_cblockbind_f` 往调用方的两个平面上绑一个 cblock 就完事；
   其余 `ippsMul_32fc` / `ippsDotProd_32f` / `ippsMagnitude_32fc` / `ippsSqr_32f` / `ippsSum_32f` / `ippsMaxIndx_32f`
   一一对应 `vsip_cvmul_f` / `vsip_vdot_f` / `vsip_cvmag_f` / `vsip_vsq_f` / `vsip_vsumval_f` / `vsip_vmaxval_f`。
   流式历史、抽取相位这些是纯 C 记账，不属于 VSIPL 的能力缺口，所以这道题测的是 API 识别而不是分解组合。
2. **抽头必须倒序存**：`vsip_vdot_f` 走的是升序窗口，把 h 倒序存才能让
   `sum_i rev[i]*x[center-T+1+i]` 等于契约里的 `sum_t h[t]*x[center-t]`。写反了不报错、不崩溃，
   仍然输出一个"看起来像滤波过"的信号——这是本包唯一一个安静的错。公开测试就是把它抓出来的。
3. **`ippsDotProd_32f` 的累加器是 `Ipp32f*`**：四个点积结果声明成 `Ipp64f` 时 IPP 只写 4 个字节，
   结果是垃圾数据，症状极像索引错误。这是基线先踩的坑，agent 若照抄声明也会踩。
4. **jvsip 的 `vsip_vmaxval_f` 会写索引**：签名第二个参数是可选 `vsip_index*`，实现里"严格大于"的扫描
   与 `ippsMaxIndx_32f` 的"首个最大值"语义一致，所以峰值索引可以精确比对（两个最大值相差不到 0.01% 时
   golden 侧存 -1，测试跳过该检查）。
5. **历史缓冲重分配后必须重绑 block**：bound block 包的是 admit 时的那个指针，历史扩容搬家以后旧 block 指向已释放内存。
6. **容差 1e-5 而不是 1e-7**：`vsip_cvmag_f` 用 `sqrt((r²+i²)/s²)*s`（s=|r|+|i|），精度够但与 IPP 的 hypot 不逐位相同；
   加上 float32 点积的求和顺序差异，参考解落在 3.576e-7。

### 7.11 任务 18 `l3_spectrum_sensing` 详情

合成仓库，形状照认知无线电的频谱感知前端：加窗分帧 → 每帧一次实数 FFT → 帧间功率累积 →
在均值功率的若干倍上做能量判决，输出噪声底、峰值、占用 bin 数与占用率。组件 266 行
（头文件 64 + 源 202），每个 stage 都是一次 IPP 调用。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（25/25），隐藏用例 8/8（worst 5.9e-10） |
| golden 生成 | `golden_gen <hidden-dir>` | 8 个 `case_*.bin` |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 8/8 PASS，worst_rel 2.514e-7 |
| API 移除 | `check_api_removal.sh libspectrumsense.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（14 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |

8 个隐藏用例覆盖 N = 32/64/64/128/256/512/1024/128，帧步长覆盖重叠（step 16/32/100/256/127）、
不重叠（step 64/512）与非整除（3000 样本 / step 100）；门限 3.0–12.0 的均值倍数各不相同。
`golden_gen` 拒绝生成"某个 bin 落在门限 1e-3（峰值相对）以内"或"峰值与次高未分开"的用例，
因此 `peak_bin` 与 `occ_bins` 可以精确比对。

值得记下的约定：

1. **fit 判为 B**：VSIPL 侧没有现成的"Welch 周期图 + 能量检测"，候选必须自己把
   `vsip_rcfftop_f`、`vsip_cvmag_f`/`vsip_vsq_f`、`vsip_vadd_f`、`vsip_svmul_f`、`vsip_vmeanval_f`、
   `vsip_vmaxval_f`、`vsip_vlge_f`+`vsip_vsumval_bl` 串起来——这正是与任务 17（API 一一对应，判 A）的区别。
2. **本 IPP 的 `ippsFFTFwd_RToCCS_32f` 输出 N+2 个 float**：`p[0]=Re X[0]`，`p[1]=Im X[0]`，
   `p[2k]/p[2k+1]=Re/Im X[k]`（k=1..N/2-1），**奈奎斯特项在 `p[N]`**。这与同库
   `ippsFFTFwd_RToPerm_64f` 的紧凑 N 长布局（Nyquist 在 `p[1]`）不是一回事：按 N 分配目标缓冲会越界写两个 float，
   且 bin N/2 读到错误槽位；症状是**只在奈奎斯特 bin 上约 6e-5 峰值相对误差**，不崩溃也不报错。
   基线版就是踩了这个坑，靠公开测试里"逐 bin 与双精度 DFT 对比"的那条检查定位。
3. **jvsip 的 `vsip_valldestroy_bl` 连 block 一起销毁**：它等价于 `vsip_vdestroy_bl` + `vsip_blockdestroy_bl`，
   后面再调一次 block 析构就是 double free（在 teardown 段崩，不在分析段）。
4. **不能用 `vsip_svmul_f(0.0f, v, v)` 清零**：它会读刚 malloc 的平面，若残留位型是 inf/NaN，
   `0*inf` 得到 NaN，污染后面每一个 bin。要用 `vsip_vfill_f(0.0f, v)`。这个坑在 N=1024 的用例上才暴露
   （堆复用恰好留下 inf/NaN），而隐藏测试原来的 `r > RTOL` 写法让 NaN 直接"通过"了比较——
   现已统一改成 `!(r <= RTOL)`，NaN 计为失败。
5. **窗函数约定是本题最容易"看着对"的地方**：契约与 `ippsWinHann_32f` 都是 `0.5(1-cos(2πi/(N-1)))`，
   而 jvsip 的 `vsip_vcreate_hanning_f` 是周期形式 `2π(i+1)/(N+1)`。两者都叫 Hann 窗、都能通过
   "纯音落在正确 bin"的检查，只有与双精度 DFT 的逐 bin 比较能抓出来。参考解按定义用
   `vramp → vsmul → vcos → vsmsa` 手工搭窗。
6. **`vsip_vmaxval_f` 的索引语义可用**：它通过可选 `vsip_index*` 出参报告索引，"严格大于"扫描给出与
   `ippsMaxIndx_32f` 相同的首个最大值，所以 peak_bin 精确比对。
7. **容差 1e-5（峰值相对）**：被比的是最长 1024 点 FFT 的平方幅度，误差预算由变换实现决定而不是迁移本身；
   参考解落在 2.514e-7。基线自检的 5.9e-10 残差来自 `ippsMean_32f` 按缓冲区对齐走不同 SIMD 尾处理，
   不是语义差异。

### 7.12 任务 19 `l3_audio_resampler` 详情

合成仓库，形状照音频前端的"采样率转换 + 转换后频谱体检"：有理比多相插值/抽取 →
对**转换后**的流做非重叠分帧周期图，输出峰值、峰值 bin、总功率与质心。组件 434 行
（头文件 85 + 源 349）。与 18 的关键区别是**有状态**：转换按"输出下标 m 对齐到输入时刻
m·down/up"定义，所以输出必须只取决于累计输入量，与调用方如何分块无关。三条门全部验证：

| 门 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（34/34），隐藏用例 8/8（worst 8.9e-8） |
| golden 生成 | `golden_gen <hidden-dir>` | 8 个 `case_*.bin`（nout 1186/296/1588/442/481/497/1613/216） |
| 迁移后构建 | `run_hidden.py --vsip-root <jvsip>` | build ok，返回 `tests: pass` |
| 数值 | `hidden_test <hidden-dir>` | 8/8 PASS，逐元素 worst_rel 6.0e-7，聚合量 1.436e-5 |
| API 移除 | `check_api_removal.sh libresampler.a` | 迁移版 PASS（0 个 `^ipp`）；IPP 版 FAIL（12 个符号） |
| 默认（未迁移）构建 | 无 IPP include 路径 | 按预期失败：`ipp.h` 不可用 |
| 内存 | ASan + UBSan 跑公开 + 隐藏测试 | 干净（含 realloc 后重绑 block 的路径） |

8 个隐藏用例覆盖：2/1（升采样、单块）、1/2（降采样、37 一块）、160/147（大比值、147 一块）、
3/2（**一次一个样本**）、5/4（16 taps）、1/1（恒等比）、7/3（非整数比、单块）、2/3（333 样本
被 50 分块，留下不完整尾巴）。第 3 个用例专门抓"跨调用丢相位/丢历史"，第 2 个用例的 257 个 bin
则决定了聚合量的容差预算（见下）。

值得记下的约定：

1. **fit 判为 B，且原型滤波器写进头文件**：任务 17 的 scope note 已说明
   `ippsResamplePolyphaseFixed_32f` 无法从其文档复现，不能做可复现的 golden。这里把窗化 sinc
   的**闭式定义**放进 `include/resampler.h`（含每支路归一化），IPP 只负责可复现的部分：
   每个输出的点积和每帧的实数 FFT。于是"契约即头文件"，任何候选都能得到同一组系数。
2. **分支抽头要时间反转**：契约的窗口随 k 增大向过去走，`ippsDotProd_32f` / `vsip_vdot_f`
   都是升序点积，所以 `hpr[p][k] = hp[p][ntaps-1-k]` 一次点积即得。不反转也能得到"看起来正常"
   的波形（滤波器近似对称），只有与双精度直和比较的公开测试和隐藏流的逐样本比较能抓出来。
3. **CCS 仍是 N+2（与任务 18 同一个坑）**：这次它出现在分析器里，迁移后自动消失——
   `vsip_rcfftop_f` 给的是 k=0..N/2 的自然复数序列，`vsip_cvmag_f` 直接覆盖全部
   `fft_len/2+1` 个 bin，不需要任何特例。
4. **历史平面会 realloc，绑在它上面的 block 必须重绑**：两条规则随之而来——
   `ippMalloc` 出来的指针不能交给 `realloc`（历史平面用普通 `malloc`/`free`，
   IPP 的固定缓冲仍用 `ippMalloc`）；以及 `vsip_blockbind_f` 绑的 block 是
   `VSIP_USER_BLOCK`，`vsip_blockdestroy_f` **不会**释放用户数组，所以"销毁 → 重新绑定"是安全
   的，而忘记重绑则会读到已释放的缓冲区——只有 ASan 看得见，因为那块内存里的旧样本还是对的。
5. **`total` 是唯一不能按逐元素容差比的量**：最多 257 个 float 的求和，两个库的累加顺序不同，
   固有误差 O(nbin·eps)≈3e-5。隐藏测试最初在 1e-5 下就只挂在这一项（case 2，1.436e-5）。同一个
   摆动在**基线自己**身上也出现过：`ippsSum_32f(..., ippAlgHintFast)` 按缓冲区对齐切 SIMD 尾段，
   跨进程结果不稳定。两侧都改了：基线改用 `ippAlgHintNone`（源码有注释说明），
   隐藏测试把 `total`/`centroid` 放到 1e-4，逐元素量与 `power` 仍留在 1e-5——
   1e-4 仍远低于归一化写错时出现的 2 倍或 N 倍偏差。
6. **不能用 `vsip_svmul_f(0.0f, acc, acc)` 清零**（与任务 18 同）：会读刚分配平面的残留位型，
   `0*inf → NaN` 污染后续所有统计量；用 `vsip_vfill_f`。隐藏测试同样统一写成 `!(r <= tol)`，
   NaN 计为失败。
7. **jvsip 的 `vsip_cvmag_f` 不是直白的 sqrt(re²+im²)**：它按 `s=|re|+|im|` 缩放再乘回，
   数学上等价、只差舍入，这是逐元素误差落在 1e-7 量级而不是 1e-8 的原因。
8. **分析器是第二份独立契约**：矩形窗（不要用 `vsip_vcreate_hanning_f`）、非重叠分帧、
   不缩放变换、且吃的是**转换后**的流；`nframes = 1+(n-N)/N`，不完整的尾帧**丢弃而不补零**
   （最后一个用例 216 样本 / N=64 得 3 帧而非 4，补零会把整张密度缩到 3/4）。

### 7.13 剩余任务

合成任务 12/12 全部完成（任务 16 于 2026-11-16 补齐）；真实仓库任务 8 个（1、2、3、7、8、9、10、11）
全部完成。20 个任务全部有包并端到端跑通，`gold_sanity` 在宿主机 20/20 pass。
每个包必须同时验证三条门并记录参考解的 worst rel，否则不算完成。

任务包结构（其余任务照此复制）：

```
l2_tdfir_bank/
├── task.yaml                 # 对齐 migration_benchmark_design.md §2.1
├── CMakeLists.txt            # USE_IPP（基线/golden）/ USE_GOLD / 默认迁移态
├── include/tdfir.h           # 不变的公开 API
├── src/tdfir_ipp.c           # 迁移源
├── gold/tdfir_vsipl.c        # 参考解（评测器可见）
├── test/public_test.c        # agent 可见的自检
└── harness/
    ├── cases.h               # 隐藏用例参数表
    ├── golden_gen.c          # 仅 IPP 模式构建
    ├── hidden_test.c         # 读 case_*.bin 比对
    ├── run_hidden.py         # 评测入口，输出 JSON
    └── check_api_removal.sh  # nm 扫 ipps*/ippi*
```
### 7.14 任务 16 `l3_radar_pulse_compression` 详情

端到端雷达距离压缩前端（合成，`domain: radar`，fit B）：

| 环节 | IPP | VSIPL |
|---|---|---|
| 复制品合成 | 头文件定义的 double 循环 | 同一份 double 循环（契约固定） |
| 正变换 | `ippsFFTFwd_RToCCS_32f`（NODIV） | `vsip_rcfftop_f`（scale 1.0） |
| 匹配滤波 | 手动 CCS↔`Ipp32fc` 重排 + `ippsMul_32fc` | `vsip_cvconj_f` 一次 + 每脉冲 `vsip_cvmul_f` |
| 逆变换 | `ippsFFTInv_CCSToR_32f` | `vsip_crfftop_f`（scale 1.0） |
| 取模/积累 | `ippsAbs_32f` + `ippsAdd_32f` + `ippsMulC_32f` | `vsip_vmag_f` + `vsip_vadd_f` + `vsip_svmul_f` |
| 因果滑动平均（FIR） | `ippsConvolve_32f`（direct，taps 全 1/L） | 逐 lag `vsip_vsumval_f` 截断窗口 × 1/L |
| 判决 | `ippsMean_32f` + `ippsMaxIndx_32f` + C 循环 | `vsip_vmeanval_f` + `vsip_vmaxval_f` + C 循环 |

验证记录（2026-11-16，宿主机 GCC 13.3.0 + IPP 2021 + jvsip `libvsip.a`）：

| 项 | 命令 | 结果 |
|---|---|---|
| 基线（IPP）构建 + 自检 | `-DUSE_IPP=ON -DIPP_ROOT=<ipp2021>` | build ok，`public_test` PASS（42/42） |
| golden 生成 | `golden_gen harness/golden` | 8 个 `case_*.bin`，margin 8.4e-3 .. 4.5e-2 |
| 数值 | `hidden_test harness/golden` | 8/8 PASS，worst_rel 7.050e-7 |
| 基线自洽 | IPP 版 `hidden_test` 对同一批 golden | 8/8，worst_rel 0.0 |
| API 移除门 | `check_api_removal.sh build_gold/libpulsecomp.a` | PASS（IPP 版 FAIL，14 个符号） |

隐藏用例 N = 64/128/256/512/1024/2048/4096/256，脉冲数 32/16/16/8/4/8/4/3，
FIR 长度 1/3/3/5/7/5/9/15，目标数 3（最后一例 1 个，专测因果 FIR 的
`(L-1)/2` 峰值右移：延迟 40 → profile 峰在 47）。

三个与其它题不同的坑：

1. **1/N 不在逆变换里**。契约的 `g[l]` 除的是 `npulses*N`，而 `|·|` 里是
   **未缩放**的逆变换（等于 N × 归一化互相关）。第一版公开测试的直接求和
   忘了这个 N，误差正好是 N−1（N=128 时为 127），三种用例同时失败。
2. **`ippsFFTGetSize_R_32f` 在本机这组参数下 `sizeInit = 0`**：照抄
   "size>0 才分配"的写法会让 `pc_create` 的必非空检查永远失败，所有合法配置
   都返回 NULL。统一用 `pc_alloc` 以最小 1 字节分配。
3. **LFM 自相关的旁瓣很高**：chirp_rate c 的主瓣宽约 1/c 个 lag，旁瓣 −13 dB；
   三个目标时 profile 的 mean 被旁瓣抬高，peak/mean 只有 2–9，阈值倍数超过
   ~10 就一个都检不出。用例阈值是扫 profile 定的（3–10），不是拍的。
