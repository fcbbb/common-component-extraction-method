# CUDA -> MUSA V2

V2 是 V1 的任务族收敛版本。它保留 V1 的 20 个 MultiKernelBench 算子任务，
但把任务包、gold 和 agent 可见数据重新整理，修复 V1 `work/` 中目标后端和
替代目标 prompt 的泄露问题。

## 结构

```text
v2/cuda_to_musa/
├── tasks/                 # 20 个 v2_b_* 任务包
├── slate.yaml             # 任务清单
├── provenance.csv         # 来源与许可证
└── library/               # 预留的冻结组件库路径
```

每个任务：

- `work/` 由 `prepare.sh` 从固定 MultiKernelBench commit 物化；
- `gold/submission/<op>_submission.py` 是 evaluator-only 目标实现；
- `gold_authored/` 保留项目自写正控来源；
- `harness/` 是判分侧代码，不进入 agent view。

## 泄露修复

`shared/harness/agent_view.py` 对 MUSA 场景过滤：

- `backends/`、`prompt_generators/`、`ascend_op_projects/`、`scripts/`
- `reference/npukernelbench_*`
- MUSA/Ascend/triton/catlass/pallas/sycl 目标 prompt
- evaluator/config/README 等基础设施文件

`prompts/` 只保留源侧 CUDA 示例。`gold/`、`gold_authored/`、`harness/`
本来就不在 `work/` 内，不会进入 agent view。

## 验证

```text
verify_task --parent v2/cuda_to_musa/tasks
LINT=PASS
```

先执行各任务的 `prepare.sh` 才有 `work/`；`work/` 被 `.gitignore` 忽略，
不属于提交内容。
