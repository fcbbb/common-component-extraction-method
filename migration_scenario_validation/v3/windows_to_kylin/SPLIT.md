# Windows → Kylin 任务切分：仓库级独立（方案 B）

- 日期：2026-11-21
- 状态：pre-registered，任务包已收敛到 `v3/windows_to_kylin/tasks/`
- 切分单位：**repository**，不是 task
- 原则：同一个仓库只能出现在 `library_source`、`pilot`、`held_out` 三者之一

## 1. 仓库分区

| 角色 | 仓库 | 任务数 | 用途 |
|---|---|---:|---|
| `library_source` | libuv | 3 | 建库语料，不参与评测 |
| `library_source` | libarchive | 2 | 建库语料，不参与评测 |
| `pilot` | libgit2 | 1 | 试跑与调提示词，不进统计 |
| `held_out` | POCO | 8 | 主测试 |
| `held_out` | nginx | 4 | 主测试 |
| `held_out` | curl | 4 | 主测试 |
| `held_out` | opencv | 1 | 边界测试 |
| `separate` | synthetic | 1 | 单独报告，不与真实上游项目混算 |

建库仓库（libuv、libarchive）与全部测试仓库（POCO、nginx、curl、opencv）不重叠。libgit2 只作 pilot，不进入任何一侧的统计。

## 2. 任务清单

### 2.1 建库来源（5 道，不评测）

| 任务 | 仓库 | 级别 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|
| `l2_libuv_fs` | libuv | L2 | T1/T2/T5 | ready | 文件系统语义 |
| `l2_libuv_process` | libuv | L2 | T1/T3/T5 | ready | T3 的唯一来源 |
| `l2_libuv_thread` | libuv | L2 | T1/T4/T5 | ready | T4 的唯一来源 |
| `l2_libarchive_read_disk` | libarchive | L2 | T1/T2/T5 | ready | 目录遍历与元数据 |
| `l2_libarchive_write_disk` | libarchive | L2 | T1/T2/T5 | ready | 恢复、权限、链接 |

### 2.2 Pilot（1 道，不进统计）

| 任务 | 仓库 | 级别 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|
| `v2_libgit2_util_full` | libgit2 | L3 | T1–T5 | run once | 已跑过一次；不再作为盲测题 |

### 2.3 Held-out 主测试（POCO，8 道）

| 任务 | 级别 | 角色 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|
| `v2_file` | L2 | test | T1/T2/T5 | ready | 文件层 |
| `v2_path` | L2 | test | T1/T2/T5 | ready | 路径与规范化 |
| `v2_thread` | L2 | test | T1/T4/T5 | ready | 线程契约 |
| `v2_rwlock_semaphore` | L2 | test | T1/T4/T5 | ready | 锁与信号量 |
| `v2_shared_library` | L2 | boundary | T1/T5 | ready | dlopen，组件库不覆盖 |
| `v2_foundation_full` | L3 | test | T1–T5 | ready | 整层重建，含 Process |
| `v2_poco_process` | L2 | test | T1/T3/T5 | new | 专用 process 题 |
| `negative_win32_eventlog` | L3 | negative | — | ready | 负对照，v3 gate 已对齐 |

### 2.4 Held-out 主测试（nginx，4 道）

| 任务 | 级别 | 角色 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|
| `v2_nginx_files` | L2 | test | T1/T2/T5 | ready | 由建库来源转为测试题 |
| `v2_nginx_full` | L3 | test | T1–T5 | ready | 整层重建，含 process/thread |
| `v2_nginx_process` | L2 | test | T1/T3/T5 | new | 专用 process 题 |
| `v2_nginx_thread` | L2 | test | T1/T4/T5 | new | 线程池 |

### 2.5 Held-out 主测试（curl，4 道）

| 任务 | 级别 | 角色 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|
| `v2_curl_build` | L3 | test | T1/T5 | ready | 构建系统 |
| `v2_curl_tls` | L2 | boundary | T1/T5 | ready | TLS，组件库不覆盖 |
| `v2_curl_thread` | L2 | test | T1/T4/T5 | new | threaded resolver |
| `v2_curl_file` | L2 | test | T1/T2/T5 | new | file:// 文件层 |

### 2.6 Held-out 边界与单独报告

| 任务 | 仓库 | 级别 | 角色 | 组件 | 状态 | 说明 |
|---|---|---|---|---|---|---|
| `l2_opencv_highgui` | opencv | L2 | boundary | T1/T5 | ready | GUI，组件库不覆盖 |
| `synthetic_multi_call_site` | synthetic | L3 | separate | T1/T2/T4/T5 | new | 跨调用点一致性，单独报告 |

### 2.7 组件覆盖（只算 core held-out）

| 组件 | 覆盖仓库 | 题数 | 说明 |
|---|---|---:|---|
| T1 | POCO / nginx / curl | 13 | 所有整层与切片题都需要契约恢复 |
| T2 | POCO / nginx / curl | 6 | 文件、路径、archive 语义 |
| T3 | POCO / nginx | 4 | process 专用题落在两个项目 |
| T4 | POCO / nginx / curl | 6 | 线程、同步、resolver |
| T5 | POCO / nginx / curl | 13 | 构建/链接是共同症状 |

T3 是原来的单点，现在由 `v2_foundation_full`、`v2_nginx_full`、`v2_poco_process`、`v2_nginx_process` 覆盖两个 held-out 仓库。`v2_curl_tls`、`v2_shared_library`、`l2_opencv_highgui` 属于边界题，不计入上表。

## 3. 规则

1. **仓库级互斥**：`library_source` 的仓库不得出现在 `held_out`；`pilot` 仓库不得进入主统计。
2. **任务级互斥**：本次 pre-registration 生效后，任何进入 `source_migrations` 的任务永久退出测试集；调整建库来源必须显式记录并重新审计（见 §4）。
3. **同仓库聚类**：同一仓库的多道题共享代码与 gold，统计上按仓库聚类，不当作独立样本。例如 `v2_nginx_full` 的 gold 覆盖 `v2_nginx_files`，`v2_foundation_full` 覆盖 POCO 各切片；它们只增加覆盖点，不增加独立样本数。
4. **v1/v2 去重**：同一仓库、同一 commit、同一迁移面的 v1 与 v2 包只计一次。
5. **边界题不混算**：`v2_curl_tls`、`v2_shared_library`、`l2_opencv_highgui` 测“组件是否该被选中/是否该声明不适用”，与核心覆盖分开报告。
6. **负对照单列**：`negative_win32_eventlog` 的正确答案是显式不移植，不计入通过率。
7. **合成题单列**：`synthetic_multi_call_site` 不代表真实上游项目，结论单独报告。
8. **变更留痕**：增删 `library_source` 必须同时更新组件 `source_migrations`，并做一次仓库专有词泄漏审计。

## 4. 与当前组件库的差异

- `v2_nginx_files` 从 `source_migrations` 移出，转为 nginx held-out 测试题。
- `l2_libarchive_read_disk` / `l2_libarchive_write_disk` 加入建库来源，支撑 T1/T2/T5。
- `libgit2_file` / `libgit2_process` 是 pilot 的子集，不进主统计。
- T3/T4 仍只来自 libuv；新增的 POCO/nginx/curl process/thread 题专门检验跨项目迁移，而不是重复同族题。

本次调整是把手工草稿的 provenance 重新落到 B 方案的建库来源。组件正文没有 nginx 专有词（已审计），因此 `v2_nginx_files` 可以作为 held-out；如果后续复核发现组件含有它的实现细节，应把它退回 `library_source`。

## 5. 待办

- [ ] 用 libarchive 证据复核 T1/T2/T5 的 pitfalls 与 verification，确认没有 nginx 专有表述（当前组件正文已无仓库专有词）。
- [ ] 打包 6 道新题：`v2_poco_process`、`v2_nginx_process`、`v2_nginx_thread`、`v2_curl_thread`、`v2_curl_file`、`synthetic_multi_call_site`。
- [x] 将全部任务包收敛到 `v3/windows_to_kylin/tasks/`，`negative_win32_eventlog`、`l2_opencv_highgui` 已补齐 `target_api`、`regression`。
- [ ] 在 POCO、nginx、curl 各选一道做 retrieval-only 验证，确认组件选择与边界判断正确。
- [ ] 第一轮跑 10 道现成 held-out 题（8 core + 2 boundary）；新题打包后再扩到完整清单。