# 组件方法 vs 直接迁移：20 题证据报告

- 场景：`windows_to_kylin_v3`
- 模型：`DeepSeek-V4.1-Flash-1017`（262144 context / 32768 output）
- 目标镜像：`migration/kylin:sp3-p2`
- 数据生成时间：2026-11-24（UTC）
- 数据来源：`reports/bench/`（只读引用，未修改任何既有结果）

---

## 0. 结论摘要

| 指标 | default（直接迁移） | method（组件检索） |
|---|---|---|
| 20 题 PASS 数 | 8 | **11** |
| 区分题胜负（一边 PASS、一边不 PASS） | 1 胜 | **4 胜** |
| 严格“method PASS / default 不 PASS” | — | **4** |
| 平均耗时（20 题） | 1935s | 2160s |
| 平均耗时（仅 PASS 题） | 1520s | 2244s |

要点：

1. 3 个合成题（`synthetic_posix_fs_requests`、`synthetic_spawn_event_loop`、`synthetic_thread_runtime`）是**干净证据**：method 全部 PASS，default 全部在组件 README 派生的深层检查上 FAIL。
2. 第 4 个 method 胜出题 `l2_opencv_highgui` 的 default 失败**含环境因素**（IPPICV/ADE 下载失败、numpy 缺失、2400s 超时），只能算弱证据。
3. 第 20 个任务 `negative_win32_eventlog` 是负向对照：method 的检索判断“无组件适用”本身正确，但编排层把空选择当 ERROR 中止，**不能计 PASS**。
4. 20 题是**筛选后的子集**：排除了 3 个 method 明显错误的 ERROR（`v2_path`、`v2_shared_library`、`v2_curl_build`）。把 23 对全部计入时，method/default 的 PASS 数是 11:10、区分题胜负 4:3，优势明显收窄（见 §6）。
5. method 的 PASS 题平均更慢（2244s vs 1520s），组件检索带来了额外开销。

---

## 1. 实验设置

### 1.1 两条臂

| | default（直接迁移） | method（组件检索） |
|---|---|---|
| profile | `component-method`（baseline_direct） | `component-method-migration` |
| 组件 bundle | 无 | `v3/windows_to_kylin/library_generated/full_20261123/library`（5 个组件） |
| 检索 | 无 | 有；写 `component_bundle/INDEX.md` + `selection.json` |
| method prompt | 无 | `config/prompts/method_retrieval_only_system.txt`（sha256 `3615c29e…`） |
| 输入 | `task.yaml` 的 spec + 环境/构建/提交说明 | 同上，外加检索到的组件 README |
| 判分 | 同一套 build / tests / API-removal / hidden probe | 同左 |

### 1.2 方法流程

method 臂每次运行都走同一套流程：

1. retrieval 阶段根据任务选择组件，写入 `component_bundle/`；
2. agent 读取组件的 `when_to_use`、`mapping rules`、`verification strategy`；
3. 按组件 README 的规则实现目标平台后端；
4. 再由同一判分器执行 build、公开测试、API-removal 和 hidden probe。

default 臂完全不接触组件，也没有检索阶段。

### 1.3 隐藏探针

三个合成题各有一组深层检查，输出 `*_DEEP=PASS/FAIL count=N`：

- `synthetic_posix_fs_requests`：`AFS_DEEP`
- `synthetic_spawn_event_loop`：`SPL_DEEP`
- `synthetic_thread_runtime`：`THR_DEEP`

这些检查覆盖组件 README 中“公开头文件看不出来”的语义规则，是区分两臂的主要手段。

---

## 2. 20 题的口径

### 2.1 任务池

本次统计范围内，两臂都跑过、且有最终结果的任务共 23 个。按用户口径：

- 排除 method 为 ERROR 的 3 个任务：
  - `v2_path`：default PASS，method 空 bundle；
  - `v2_shared_library`：default PASS，method 空 bundle；
  - `v2_curl_build`：两边都未通过，method 检索空选择。
- 剩余 19 个；
- 加上“最不错误”的负向对照 `negative_win32_eventlog`，凑成 **20 个**。

### 2.2 负向对照为什么算“最不错误”

`negative_win32_eventlog` 的任务定义明确要求：Windows Event Log 在 Kylin 上没有等价物，正确交付物是一份 `PORTING_NOTES.md`，**不要新增后端**。

- method 的检索结论是“no component applies”，这与负向任务的正确判断一致；
- 但编排层把“空选择”当作致命错误，流程在写报告前中止；
- default 则尝试迁移，最终 hidden test（`PORTING_NOTES.md` 存在且提到 event log / not portable）失败。

因此它是一个**检索正确性**的正面案例，但不是端到端 PASS，本报告单独标注。

### 2.3 20 题分类

| 分类 | 数量 | 任务 |
|---|---|---|
| 两边都成功 | 7 | `v2_curl_tls`、`v2_rwlock_semaphore`、`v2_thread`、`v2_curl_file`、`v2_curl_thread`、`v2_nginx_thread`、`synthetic_multi_call_site` |
| 两边都失败 | 8 | `v2_file`、`v2_foundation_full`、`v2_libgit2_util_full`、`v2_nginx_files`、`v2_nginx_process`、`v2_poco_process`、`v3_poco_fs_stack`、`negative_win32_eventlog`（特殊） |
| method 胜出 | 4 | `l2_opencv_highgui`、`synthetic_posix_fs_requests`、`synthetic_spawn_event_loop`、`synthetic_thread_runtime` |
| default 胜出 | 1 | `v2_nginx_full` |

---

## 3. 20 题明细

| 任务 | 分类 | default | method | method 组件数 | 备注 |
|---|---|---|---|---|---|
| `synthetic_posix_fs_requests` | method 胜 | FAIL 373.9s | **PASS 531.3s** | 1 | `AFS_DEEP=FAIL count=9` |
| `synthetic_spawn_event_loop` | method 胜 | FAIL 517.7s | **PASS 565.0s** | 1 | `SPL_DEEP=FAIL count=1`；新探头 |
| `synthetic_thread_runtime` | method 胜 | FAIL 284.6s | **PASS 323.2s** | 1 | `THR_DEEP=FAIL count=1` |
| `l2_opencv_highgui` | method 胜 | FAIL 6508.7s | **PASS 6129.8s** | 2 | default 失败含环境因素 |
| `v2_nginx_full` | default 胜 | **PASS 1188.6s** | FAIL 1009.0s | 2 | method 无 attempt.json，仅 batch rc=1 |
| `negative_win32_eventlog` | 都失败（特殊） | FAIL 218.3s | ERROR 466.9s | 0 | 检索判断正确，流程中止 |
| `v2_file` | 都失败 | FAIL 3445.2s | FAIL 1804.1s | 2 | 两边同一公开测试失败 |
| `v2_foundation_full` | 都失败 | FAIL 2153.3s | FAIL 4214.1s | 2 | default 触发 step limit |
| `v2_libgit2_util_full` | 都失败 | FAIL 1494.9s | FAIL 2488.8s | 2 | api_removal：`_MSC_VER` 残留 |
| `v2_nginx_files` | 都失败 | FAIL 1887.9s | FAIL 641.0s | 1 | EINTR / 短写探针 |
| `v2_nginx_process` | 都失败 | FAIL 1779.9s | FAIL 3837.1s | 1 | SIGQUIT 后 master 未退出 |
| `v2_poco_process` | 都失败 | FAIL 2115.2s | FAIL 2292.3s | 1 | 公开测试 error |
| `v3_poco_fs_stack` | 都失败 | FAIL 5773.5s | FAIL 1758.4s | 2 | EINTR / 短写探针 |
| `v2_curl_tls` | 都成功 | PASS 2308.0s | PASS 9379.3s | 2 | method 明显更慢 |
| `v2_rwlock_semaphore` | 都成功 | PASS 1414.5s | PASS 1381.8s | 1 | |
| `v2_thread` | 都成功 | PASS 2225.1s | PASS 1737.0s | 1 | |
| `v2_curl_file` | 都成功 | PASS 2699.8s | PASS 2633.3s | 1 | |
| `v2_curl_thread` | 都成功 | PASS 1154.8s | PASS 815.6s | 1 | |
| `v2_nginx_thread` | 都成功 | PASS 724.6s | PASS 962.8s | 1 | |
| `synthetic_multi_call_site` | 都成功 | PASS 440.4s | PASS 229.0s | 1 | |

---

## 4. 典型案例分析

### 4.1 案例 A：`synthetic_posix_fs_requests` — 9 个深层失败

default 的结果：

```
deep: vector write transferred -22 of 6000 bytes (line 145)
deep: vector write size is 0 (line 153)
deep: vector file read-back failed (line 157)
deep: vector write content differs at 0 (line 161)
deep: long read vector transferred -22 bytes, expected 1024 (line 200)
deep: long read vector slot 0 not filled (line 204)
deep: temporary template without the suffix (line 382)
deep: interrupted write reported 65536 of 2097152 bytes (line 569)
deep: interrupted-write reader received 65536 bytes (line 575)
AFS_DEEP=FAIL count=9
```

method 选中 `posix-file-system-request-backend-behind-a-fixed-async-42929ace`，PASS。

分析：

- `-22`（EINVAL）出现在向量读写：从失败形态看，最可能是 default 没有按 `IOV_MAX` 分批，直接把整段 iovec 交给一次调用；组件 README 明确要求按上限切分并循环。
- 临时文件模板失败：README 要求模板必须以 `XXXXXX` 结尾并交给 `mkstemp`；default 保留了 Windows 风格的后缀。
- EINTR：default 在 65536/2097152 处直接返回，没有重启写循环；README 要求 EINTR 后重试并补齐剩余字节。
- 这正是“公开 spec 只给头文件契约，深层语义在组件 README 里”的设计：default 没有组件可读，只能靠猜测，9 个检查全部命中。

### 4.2 案例 B：`synthetic_spawn_event_loop` — 一个检查定胜负

default 的结果：

```
deep: invalid inherited descriptor error: -9 (errno 2) (line 451)
SPL_DEEP=FAIL count=1
SPL_PROBE=FAIL process-contract checks
```

method 与 gold 都返回 `-EINVAL`，default 返回 `-EBADF`（-9）。

分析：

- 组件 README 的 spawn 映射规则写明：继承槽位必须指向一个存活的描述符；关闭或非法描述符是**参数错误**，应在创建任何东西之前返回 `-EINVAL`。
- default 直接把 `fd=-1` 传给 `dup2`/`fork` 路径，让平台在子进程侧报 `EBADF`，语义层级错了。
- 这条检查是**后来补进探针的**：旧探针下 default 曾 PASS。补检查前先用 gold/method/default 三跑验证过行为，且该规则来自组件 README，不是为 default 定制的宽容度补丁。
- 因此 B 题的“method 胜”依赖补强后的探针；这一点必须在引用结论时说明。

### 4.3 案例 C：`synthetic_thread_runtime` — 栈大小向上取整

default 的结果：

```
THR_DEEP=FAIL count=1
deep: a 100001-byte request produced a 99968-byte stack (line 556)
THR_PROBE=FAIL threading-contract checks
```

分析：

- 请求 100001 字节，default 得到 99968 字节（向下截断），比请求还小；组件 README 要求栈大小按平台粒度**向上取整**，且不得小于请求值。
- 100001 与 99968 的差值只有 33 字节，但这是“是否满足契约”的分界：调用者请求 100001，得到的栈必须 ≥100001。
- method 选中 `portable-threading-and-synchronisation-backend-for-an-96ad6495`，PASS。
- 这个案例说明：一个字节级的语义偏差就足以让 default 失败，不需要大范围功能缺失。

### 4.4 案例 D：`l2_opencv_highgui` — 弱证据

- default：build fail，DSH 触发 step limit 150；日志中同时出现 `No module named 'numpy'`、`IPPICV: Download failed`、`ADE: Download failed`，以及 `[timeout after 2400s]`。
- method：PASS 6129.8s，选中 2 个组件（spawn + fs）。
- 判断：default 的失败**不能全部归因于组件方法**，其中包含网络下载、依赖缺失和超时。它可以作为旁证，但不能和三个合成题并列作为强证据。
- 建议：如果要把它纳入强证据，需要在有网络/预置依赖的环境里重跑 default，确认失败仍然发生在代码语义层。

### 4.5 案例 E：`negative_win32_eventlog` — 检索正确、流程错误

- 任务要求：写 `PORTING_NOTES.md`，说明 Windows Event Log 不可移植；不要新增后端。
- default：hidden test 失败（`tests=fail`）；从任务定义看，是 `PORTING_NOTES.md` 未满足“存在且提到 event log / not portable”的要求。
- method：`retrieval validated an empty component selection; no component applies to this task`，流程中止。
- 分析：对负向任务，“无组件适用”是**正确**的检索结论；错误在编排层把空选择当成致命错误，没有让 agent 继续完成报告。
- 这是 method 侧的一个真实缺陷（workflow 不支持负向任务），但同时也是检索正确性的证据。报告把它标为“特殊项”，不计 PASS。
- 修复建议：允许 `selected_bundle_ids=[]` 的任务继续执行，只跳过“读组件”阶段，不应中止整个任务。

### 4.6 案例 F：`v2_nginx_full` — default 胜，但 method 证据不完整

- default：PASS 1188.6s。
- method：batch rc=1，1009.0s，**没有 attempt.json**；workspace 里 `selection.json` 显示选中 2 个组件（fs + spawn）。
- 分析：method 在这个任务上既没有拿到 PASS，也没有留下判分报告，只能从 batch 日志确认失败。它说明检索可能**多选**（nginx full 涉及的面很广），但无法进一步定位是检索错、应用错还是构建错。
- 证据级别：B（仅 batch 日志）。这也是 20 题里唯一一个 method 结果没有 attempt.json 的任务。

### 4.7 案例 G：组件选中了，但规则没被应用

以下任务 method 都选中了相关组件，但仍在组件对应的深层检查上失败：

| 任务 | method 选中 | 失败检查 | 说明 |
|---|---|---|---|
| `v2_nginx_files` | fs | `write retries after an interrupted write`；`short write` | 组件选对了，EINTR/短写规则没有落实到代码 |
| `v2_nginx_process` | spawn | `master did not exit on SIGQUIT` | spawn 组件覆盖会话/信号，但实现没处理 SIGQUIT |
| `v2_poco_process` | spawn | 公开测试 2 个 error | spawn 选中，子进程错误路径仍未过 |
| `v2_file` | disk-reader + fs | `testFileAttributes1`：“file does not exist - must throw exception” | 公开测试语义问题，两臂同败 |
| `v3_poco_fs_stack` | disk-reader + archive-writer | `copy writes every byte after EINTR and a short write` | 失败点是 fs 写循环，但检索没选 fs 组件 |

结论：**检索正确是必要条件，不是充分条件**。method 的瓶颈已经从“找不到组件”转移到“选中后能否把 README 规则应用到代码”。

### 4.8 案例 H：检索漏选

- `v3_poco_fs_stack`：失败检查是 EINTR/短写写循环，属于 fs 组件；method 选的是 disk-reader + archive-writer，两个都不直接覆盖这个写循环。
- `v2_foundation_full`：method 选 thread + spawn，但失败集中在 `FileTest`、`PathTest`、`DirectoryIteratorsTest`（文件系统/路径/目录遍历），更像 fs/disk-reader 的覆盖范围。
- 这两例说明：检索的“相关性”判断还有提升空间；组件选择应该以失败面/头文件 API 为依据，而不是以项目名或领域关键词为依据。

### 4.9 案例 I：两臂同败的真实问题

- `v2_libgit2_util_full`：两臂 build 和 tests 都 PASS，但 `api_removal=fail`；命中 `src/util/unix/pthread.h:15` 的 `_MSC_VER`。这是**共享的 Windows 守卫残留**，与组件方法无关，两臂都该修。
- `v2_file`：两臂都失败在同一个公开测试 `testFileAttributes1`，说明该任务的核心语义没有被任何一臂解决。
- `v2_nginx_process`：两臂都失败在 `master did not exit on SIGQUIT`，属于进程/信号语义。
- 这些任务不应该被用来证明或否定组件方法；它们是任务本身的难度/缺陷，需要单独修。

---

## 5. 组件选择统计

20 个 method 运行中，19 个有非空选择（`negative_win32_eventlog` 为空），共 26 次组件选择：

| 组件 | 被选次数 |
|---|---|
| `process-spawn-backend-for-an-event-loop` | 8 |
| `portable-threading-and-synchronisation-backend` | 8 |
| `posix-file-system-request-backend` | 7 |
| `filesystem-disk-reader-backend` | 2 |
| `archive-extraction-writer` | 1 |

观察：

1. fs / spawn / thread 是高频组件，和任务池的构成一致；
2. disk-reader / archive-writer 只出现在 `v2_file`、`v3_poco_fs_stack` 等少数任务中，样本不足；
3. 7 个 method 运行选了 2 个组件（`l2_opencv`、`v2_nginx_full`、`v2_curl_tls`、`v2_libgit2`、`v2_foundation`、`v3_poco`、`v2_file`），其中只有 2 个 PASS；多选并不等于更稳。

---

## 6. 结论与边界

### 6.1 可以支持的结论

1. 在**按组件 README 规则设计隐藏探针**的合成任务上，method 臂可以稳定 PASS，而 default 臂在深层语义上 FAIL。三个合成题提供了 3 个干净样本。
2. 组件检索在这三个题上都选中了**唯一正确**的组件（A→fs、B→spawn、C→thread），说明检索的“按任务找组件”能力是可用的。
3. 在 20 题子集上，method 的 PASS 数（11）高于 default（8），区分题胜负为 4:1。
4. method 的代价是时间：PASS 题平均 2244s，default 为 1520s。

### 6.2 不能支持的结论

1. **不能**说“组件方法在 20 题上全面优于直接迁移”。20 题里有 8 个两边都失败，1 个 default 胜；method 仍有 9 个任务未 PASS（含负向特殊项）。
2. **不能**说“20 个 method 胜出”。严格的 method PASS / default 不 PASS 只有 4 个；其中 1 个（`l2_opencv`）还含环境因素。
3. **不能**把 20 题子集的 11:8 直接外推到全量。把被排除的 3 个 ERROR 计入后是 23 对：method 11 PASS vs default 10 PASS，区分题 4:3，优势明显变小。
4. **不能**忽略选择偏差：20 题子集是按“method 表现较好”的方向筛的；这不是随机抽样。

### 6.3 威胁与限制

| 限制 | 影响 |
|---|---|
| 20 题是筛选子集 | 11:8 的差距被放大；全量 23 对是 11:10 |
| B 题探针是后补的 | method 胜依赖补强后的检查；旧探针下 default 曾 PASS |
| `l2_opencv` 环境因素 | default 失败含网络/依赖/超时，不能算强证据 |
| `negative_win32_eventlog` 是 ERROR | 只能算“检索判断正确”，不能算 PASS |
| `v2_nginx_full` 缺 attempt.json | method 失败无法定位到具体 gate |
| 合成题围绕组件设计 | 存在“教考一致”的循环性；结论应表述为“在组件 README 覆盖的语义上” |
| 单模型、单次运行 | 没有重复实验和显著性检验；不能排除运行波动 |
| 任务池构成不均 | disk-reader / archive-writer 只有 2/1 次选择，样本不足 |

### 6.4 建议的下一步

1. **修 workflow**：允许负向任务的空选择继续执行，不要中止；空 bundle 应报可诊断的错误，而不是 rc=2。
2. **修检索**：以头文件 API 和失败面为依据选组件；`v3_poco_fs_stack` 应选 fs，`v2_foundation_full` 应覆盖 fs/path。
3. **修应用**：对“选中但未应用”的案例（nginx_files、nginx_process、poco_process）检查 agent 是否真的读了 README 的 `mapping rules`。
4. **补强证据**：在干净环境重跑 `l2_opencv` 的 default；为 `v2_nginx_full` 补一次有 attempt.json 的 method 运行。
5. **扩到 20 个 method-win**：现有 20 题里只有 4 个严格 method-win；若要 20 个，需要按 §2 的 5 组件 × 4 变体新建 17 个题，并按 gold/default/method 三跑验收。

---

## 7. 数据字典与复现

### 7.1 文件

| 路径 | 内容 |
|---|---|
| `data/results_long.csv` | 长表，40 行（20 题 × 2 臂），每行一个 attempt |
| `data/results_wide.csv` | 宽表，20 行，每题一行，便于阅读 |
| `data/results.json` | 汇总 + 宽表 + 长表的 JSON 版本 |
| `data/summary.json` | 计数、PASS 数、胜出列表、实验配置 |
| `data/sources/<label>/summary.json` | 原始 bench summary 副本 |
| `data/sources/<label>/attempts/<task>/attempt.json` | 原始 attempt 副本 |
| `data/sources/<label>/selections/<task>/selection.json` | method 组件选择副本 |
| `cases/<task>.txt` | 典型案例的判分日志尾部（default + method） |
| `build_dataset.py` | 生成本目录数据的脚本（只读源报告） |

### 7.2 字段

- `status`：`pass` / `fail` / `error` / `missing`
- `duration_s`：该臂 attempt 的墙钟时间（秒）
- `gate_status`：`build` / `tests` / `api_removal` / `target_api` 的判分状态
- `evidence`：`A` = 有 attempt.json；`B` = 仅 batch 日志
- `selected_components`：method 臂 `selection.json` 中的 `selected_bundle_ids`
- `failure_summary`：判分日志中与失败相关的行，已过滤构建噪声

### 7.3 重新生成

```bash
cd /home/fcbbbb/projects/demo_common_exreaction/common-component-extraction-method/repository/migration_scenario_validation
python3 -I v3/windows_to_kylin/component_method_evidence_20261124/build_dataset.py
```

脚本只读 `reports/bench/`，不会修改任何既有结果。

---

## 8. 一句话总结

**三个合成题干净地证明了“组件检索能覆盖直接迁移猜不到的深层语义”；20 题子集上 method 11:8 领先，但这不是 20 个 method-win，且优势在计入全部 23 对后收窄到 11:10。当前更值得修的是检索漏选、选中未应用、负向任务空选择这三类真实缺陷。**