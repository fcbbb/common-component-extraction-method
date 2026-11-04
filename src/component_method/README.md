# 源码阶段结构

本目录按方法流水线的数据流组织：

1. `source_scan/`：扫描和切分源码；
2. `signal_analysis/`：计算结构、重复代码和语义信号；
3. `protocol_candidates/`：生成和冻结协议候选；
4. `component_build/`：抽取、审核、修复和运行时验证组件；
5. `library_publish/`：发布组件库；
6. `retrieval/`：针对任务检索组件；
7. `task_execution/`：运行直接基线和组件方案；
8. `reporting/`：汇总 20 个任务结果。

`workflow/` 只负责按顺序编排上述阶段。
