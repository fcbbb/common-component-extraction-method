# 源码阶段结构

本目录按方法流水线的数据流组织：

1. `source_scan/`：扫描和切分源码；
2. `signal_analysis/`：计算结构、重复代码和语义信号（工作区前置）；
3. `protocol_candidates/`：生成和冻结协议候选（工作区前置）；
4. `component_build/`：抽取、收敛、冻结、审核、修复和运行时验证组件；
5. `library_publish/`：发布组件库（支持 reviewed / unreviewed）；
6. `retrieval/`：针对任务检索组件；
7. `task_execution/`：运行直接基线和组件方案；
8. `reporting/`：汇总任务结果。

`workflow/blocks.py` 定义六个原子块，`workflow/run_stage.py` 执行单个块，
`workflow/run_batch.py` 按配置选择块序列。块的前置条件只由磁盘产物决定。
