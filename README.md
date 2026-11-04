# Common Component Extraction Method

本仓库包含共性组件抽取流水线的实现和实验证据，并在 20 个 SWE-rebench 任务上完成验证。

流水线先冻结生产 Python 源码，在不引入任务信息的条件下建立语义与结构关系、生成协议感知候选、组织核心代码与上下文分组、抽取并审核组件、发布只读组件库；组件库冻结后，才针对后续任务执行组件检索和交付。

## 最终结果

| 实验条件 | 通过数 | 总任务数 | 通过率 |
| --- | ---: | ---: | ---: |
| 直接基线 | 6 | 20 | 30% |
| 共性组件方法 | 10 | 20 | 50% |

20 个源码快照均形成了非空组件库，共发布 486 个组件，最终选择 63 个组件。完整实验说明见 `docs/final_report_20_tasks.md`，逐任务结果见 `results/per_task.csv`。

## 仓库内容

- `src/component_method/source_scan/`：扫描生产源码并切分代码单元。
- `src/component_method/signal_analysis/`：计算结构、重复代码和语义信号。
- `src/component_method/protocol_candidates/`：生成、压缩和冻结协议候选。
- `src/component_method/component_build/`：抽取、审核、修复和运行时验证组件。
- `src/component_method/library_publish/`：发布只读组件库和 Agent 交付包。
- `src/component_method/retrieval/`：针对后续任务检索和物化组件。
- `src/component_method/task_execution/`：运行直接基线、组件方案及正式评测。
- `src/component_method/reporting/`：汇总最终 20 个任务结果。
- `src/component_method/workflow/`：按上述顺序编排完整实验，不承载阶段实现。
- `config/`：公开配置模板、提示词、结构定义和最终 20 任务映射。
- `tests/`：组件抽取、验证和检索行为的重点测试。
- `results/`：精简汇总结果、逐任务结果与文件清单。
- `tools/`：独立工作区准备、环境预检、清单刷新和完整性校验工具。

## 环境安装

参考运行环境为 Python 3.12：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[embeddings,agents,test]'
```

模型服务通过环境变量配置，仓库内不保存访问凭证：

```bash
export OPENAI_API_KEY='...'
export OPENAI_API_BASE='https://你的兼容接口地址/v1'
```

冻结输入和完整任务证据位于本仓库同级的 `offline_artifacts/` 目录。

## 独立运行

先为一个任务生成可写工作区，并从对应任务镜像提取完整源码：

```bash
python tools/prepare_workspace.py \
  --task elastic__curator-1175 \
  --materialize-sources
python tools/preflight.py \
  --task elastic__curator-1175 \
  --require-model-env
```

随后可以按阶段运行：

```bash
export COMPONENT_METHOD_RUN_ROOT="$PWD/work"
python -m component_method.workflow.run_stage \
  --task-root work/tasks/elastic__curator-1175 \
  --stage prepare
python -m component_method.workflow.run_batch \
  --task elastic__curator-1175 \
  --stage pipeline \
  --task-workers 1 \
  --extraction-workers 1 \
  --review-workers 1
```

`prepare_workspace.py` 默认把运行输出写到 `repository/work/`。离线证据和冻结结果保持只读。

审核默认采用“修订后再次审核”的严格模式。若实验明确限制只能调用一次审核模型，
可在任务配置中设置 `apply_review_revisions_without_rereview=true`，随后运行
`finalize_review` 子阶段。该模式只应用审核器已经给出的完整字段替换并执行本地协议
校验，不会伪装成二次审核；发布审计状态会记录为
`revisions_applied_without_rereview`。

## 完整性校验

```bash
python tools/verify_release.py
pytest
```

校验器会检查以下内容：

- 最终任务集合严格为 20 个任务；
- 发布组件总数为 486，最终选择总数为 63；
- 直接基线和组件方法通过数分别为 6 和 10；
- 两个正式重跑任务使用正确的 `task_02` 结果；
- 文件清单和 SHA-256 哈希完整一致；
- 不包含原始模型轨迹、检查点、运行日志、符号链接、工作区绝对路径或凭证。

## 制品完整性

`config/` 中的流水线提示词和 `offline_artifacts/` 中的组件说明属于实验输入或冻结制品，其内容由文件清单和 SHA-256 哈希约束。
