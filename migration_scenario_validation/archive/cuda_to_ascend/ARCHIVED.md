# 已归档：cuda_to_ascend

**归档日期**：2026-11-16  
**原因**：当前没有昇腾（Ascend）环境，也没有 CANN 工具链和 NPU。该场景无法执行
任何正控，继续留在三场景入口会让人误以为它可运行。

## 归档时的状态

- 20 个任务包（6 个 MultiKernelBench + 14 个 CANN Bench）；
- 3 题有上游 AscendC gold（`leaky_relu`、`mse_loss`、`layer_norm`），
  17 题 judge-only；
- 只做过静态校验：`verify_task.py`、`check_pins.py --offline`、gold 隔离
  检查；**没有任何 msopgen 编译或 NPU 执行**。

## 被什么替代

[`../cuda_to_musa/`](../../cuda_to_musa/)：NVIDIA CUDA → 摩尔线程 MUSA
（MTT S4000，MUSA SDK 5.2.0，`torch_musa`）。同样是 20 题、3 题上游 gold、
17 题 judge-only，但目标平台可在现有硬件计划内获得。

## 恢复方式

如果以后拿到 Ascend 环境：

1. 把本目录移回 `cuda_to_ascend/`；
2. 在 `shared/harness/verify.py`、`tools/check_pins.py`、
   `tools/gold_sanity.py` 的 scenario 列表里重新加入 `cuda_to_ascend`；
3. 按本目录 `design.md` / `positive_controls.md` 重跑静态检查与 3 个 gold
   正控；
4. 不要直接把归档状态写成“已验证”。

原 `design.md`、`task_slate.md`、`provenance.csv`、`positive_controls.md`
和 `slate.yaml` 均保持归档时原样，未随 MUSA 场景更新。