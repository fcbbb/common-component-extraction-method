# 全量组件库：full_20261123

- 生成日期：2026-11-23
- 场景：`windows_to_kylin`
- 语料：`history/` 中 5 个 `library_source` example（libuv ×3，libarchive ×2）
- 库路径（本机，未提交）：`library_generated/full_20261123/library/`
- 历史摘要：`history_digest = 20612e420792915297063243ddf6646748776bc75b6f2755dd6d391889d57808`
- 审核：5/5 `review_verdict = publish`；`verify_library` 通过（无 held-out project 泄漏，无缺文件）
- 模型：`DeepSeek-V4.1-Flash-1017`（paratera 网关，凭据来自 `repository/.env`）

## 组件清单

| bundle_id | capability | 来源 example | 来源仓库 |
|---|---|---|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | `l2_libuv_fs` | libuv |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | `l2_libarchive_write_disk` | libarchive |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | `l2_libarchive_read_disk` | libarchive |
| `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` | process | `l2_libuv_process` | libuv |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | `l2_libuv_thread` | libuv |

一条 example 只产出一个组件；当前没有 build 能力的来源。

## 复现

```bash
cd repository/migration_scenario_validation

# 1) 语料完整性（离线）
../.venv/bin/python tools/build_history_corpus.py \
  --spec v3/windows_to_kylin/history/spec.yaml --verify

# 2) 抽取 → 审核 → 发布（需要模型凭据）
set -a; . ../.env; set +a
../.venv/bin/python tools/extract_transformation.py --stage all \
  --spec v3/windows_to_kylin/history/spec.yaml \
  --library v3/windows_to_kylin/library_generated/full_20261123/library \
  --resume --workers 2

# 3) 能力矩阵
../.venv/bin/python tools/component_task_matrix.py \
  --library-manifest v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json \
  --tasks-root v3/windows_to_kylin/tasks \
  --slate v3/windows_to_kylin/slate.yaml \
  --output-dir v3/windows_to_kylin/capability_matrix
```

## 已知边界

- **库不随仓库分发**：`library_generated/` 与 `history/runs/` 被 `.gitignore` 排除；新环境必须按上面的命令重建，或在同一台机器复制。
- **任务引用路径**：`task.yaml` 的 `library_manifest` 指向本库时，使用的是本机相对路径；在重建前任务包不可直接运行。
- **首轮 schema 偏差**：`l2_libarchive_read_disk` 首轮把 `boundary` 返回为 list，被 curate 拒绝；归档在 `history/runs/rejected/`，重跑后通过。抽取 prompt 目前只以示例说明 `boundary` 是字符串，后续若要稳定，应在 prompt 中显式约束类型，而不是放宽 validator。
- **能力缺口**：build 能力无来源；`v2_curl_build`、`v2_foundation_full` 等整层任务在矩阵中没有 primary 组件，需要人工指定多组件组合。
- 组件卡是抽象描述，不直接给出源码路径；矩阵的匹配基于 capability/operation family 与源侧 token，仍需人工复核后才会用于建题。