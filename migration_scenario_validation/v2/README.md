# V2：库优先的任务族

> 状态（2026-11-23）：V2 的 6 个任务包已删除，任务并入
> [`v3/windows_to_kylin/tasks/`](../v3/windows_to_kylin/tasks/)；本目录保留
> 设计文档、slate、provenance 与冻结库作为历史设计记录。下文表格描述的是
> V2 当时的构建状态，不再代表当前任务集。

V2 把验证单位从“单题”改成“库 + 任务族”。完整设计见
[docs/task_design_v2.md](../docs/task_design_v2.md)，本目录是其中
**Windows → 麒麟（POCO Foundation）**主场景的实现。

## 目录

```text
v2/
├── README.md                      # 本文件
└── windows_to_kylin/
    ├── design.md                  # 场景实现说明
    ├── slate.yaml                 # 任务族单一来源
    ├── task_slate.md              # 渲染后的清单
    ├── provenance.csv             # 仓库 / commit / license
    ├── library/                   # 冻结库定义与快照锁
    └── tasks/                     # 已删除：6 个任务包并入 v3
```

## 状态

| 项 | 状态 |
|---|---|
| 任务包（6 个） | 已构建，静态校验通过 |
| 宿主机 gold 正控 | **6/6 通过**（GCC 13.3；构建、隐藏测试、回归、双向 API 门禁；`reports/gold_sanity/v2/`） |
| 冻结语料 | 已锁定（635 files，目标平台实现不进语料；内容哈希见 `library/lock.json`） |
| 组件库发布 | 待方法流水线抽取 + 审核 + `publish` |
| 四条件实验 | A / B0 可跑；B 待发布；C 待实现 |

## 快速校验

```bash
python3 tools/verify_task.py --parent v2/windows_to_kylin/tasks
python3 tools/lint_dataset.py
python3 tools/check_pins.py --offline --parent v2/windows_to_kylin/tasks
python3 tools/freeze_library.py verify \
  --spec v2/windows_to_kylin/library/freeze.yaml
```

## 任务族

| # | 任务 | 族类型 | 判分重点 |
|---:|---|---|---|
| 1 | `v2_thread` | 模式族 | 线程契约 + 线程池/定时器/活动派发一致性 |
| 2 | `v2_file` | 隐含契约 | 文件语义 + 文件流/目录迭代/glob 一致性 |
| 3 | `v2_path` | 隐含契约 | 路径语义 + glob/目录遍历/监视一致性 |
| 4 | `v2_shared_library` | 模式族 | 加载/卸载 + 类加载/清单一致性 |
| 5 | `v2_rwlock_semaphore` | 隐含契约 | 锁与信号量超时/中断 + 线程池/定时器 |
| 6 | `v2_foundation_full` | 定位型 | 整层重建 + 全量核心套件 + 回归 |

任务说明只写外部契约；被删实现、目标 API、文件布局和调用序列均留在求解空间。