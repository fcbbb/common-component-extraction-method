# 20 题组件优先批量评测集

- 建立：2026-11-23
- 来源：`slate.yaml` 去掉 5 个 `library_source` 建库任务后，剩余的 held-out / 边界 / pilot / 合成题共 20 个。
- 库：[full_20261123](../LIBRARY_full_20261123.md)（5 个组件，digest `20612e42…57808`）
- 矩阵：[capability_matrix/matrix.md](../capability_matrix/matrix.md)

## 1. 题目与角色

| # | 任务 | 角色 | 主组件 | 可运行 |
|---:|---|---|---|---|
| 1 | `v2_file` | held-out POCO | file ×3 | 是 |
| 2 | `v2_path` | held-out POCO | file ×3 | 是 |
| 3 | `v2_thread` | held-out POCO | thread | 是 |
| 4 | `v2_rwlock_semaphore` | held-out POCO | thread | 是 |
| 5 | `v2_shared_library` | 边界 | — | 是 |
| 6 | `v2_foundation_full` | held-out POCO | —（整层） | 是 |
| 7 | `v2_poco_process` | held-out POCO | process | 是（三题库） |
| 8 | `negative_win32_eventlog` | 负对照 | — | 是 |
| 9 | `v2_nginx_files` | held-out nginx | file ×3 | 是 |
| 10 | `v2_nginx_full` | held-out nginx | —（整层） | 是 |
| 11 | `v2_nginx_process` | held-out nginx | process | 是（三题库） |
| 12 | `v2_nginx_thread` | held-out nginx | thread | 是（三题库） |
| 13 | `v2_curl_build` | held-out curl | — | 是 |
| 14 | `v2_curl_tls` | 边界 | thread | 是 |
| 15 | `l2_opencv_highgui` | 边界 | — | 是 |
| 16 | `v2_libgit2_util_full` | pilot（不计统计） | — | 是 |
| 17 | `v3_poco_fs_stack` | held-out POCO L3 | file ×3 | 是 |
| 18 | `v2_curl_thread` | held-out curl | thread | 是（run2） |
| 19 | `v2_curl_file` | held-out curl | file ×2 | 是（run2） |
| 20 | `synthetic_multi_call_site` | separate | — | 是（run2） |

20 题全部已建包。`suite20/tasks_run1.txt` 覆盖 14 题（排除 7/11/12 由三题库覆盖、18–20 由 run2 覆盖）；
`suite20/tasks_run2.txt` 覆盖剩余 3 题。gold 正控：`synthetic_multi_call_site` PASS（16.1 s）、
`v2_curl_file` PASS（350.6 s）、`v2_curl_thread` PASS（459.6 s，`gold_curl_thread_r4`，修掉 Win32 分支剥离脚本的嵌套 `#endif` bug 后）。

## 2. 运行方式

`tools/bench_batch.py` 做三件事：

1. 串行执行每个任务的 `prepare.sh`。这一步必须串行：`prepare.sh` 改写任务自己的 `work/`，且同仓库任务共用 cache 仓，并发会互相 `git checkout`/`git archive`。
2. 清掉 `work/` 中可能由 gold 运行留下的答案。
3. 以固定并发跑独立 `bench.py` 进程，每个 job 使用 `--no-prepare`；同一任务同一时刻只跑一个臂，避免固定测试端口冲突。

```bash
../.venv/bin/python tools/bench_batch.py \
  --tasks-file v3/windows_to_kylin/suite20/tasks_run1.txt \
  --arms default,method --workers 3 --prefix s1

# method 臂固定参数
# --method-prompt config/prompts/method_retrieval_only_system.txt
# --bundle v3/windows_to_kylin/library_generated/full_20261123/library
# --method-stage-image migration/kylin:sp3-p2
```

断点续跑：已有 `attempt.json` 的 label 会自动跳过；中断后重跑同一命令即可。状态写在
`library_generated/batch_state_s1.json`，单 job 日志在 `library_generated/batch_logs/`。

run2（新补的 3 题）在各自 `prepare.sh` 与 gold 正控通过后启动，避免与 run1 的 prepare 抢共享 cache：

```bash
# 已启动：curl_file + synthetic（tasks_run2_now.txt）
../.venv/bin/python tools/bench_batch.py \
  --tasks-file v3/windows_to_kylin/suite20/tasks_run2_now.txt \
  --arms default,method --workers 2 --prefix s1b --skip-prepare

# curl_thread 单任务：s1c 因 prompt 与 api 门禁不一致作废（归档 _infra_errors/*_prompt_gate_misaligned），
# 修正 spec 后用 prefix s1d 重跑
../.venv/bin/python tools/bench_batch.py \
  --task v2_curl_thread --arms default,method --workers 1 --prefix s1d --skip-prepare
```

## 3. 结果登记

用 `tools/collect_case_results.py --prefix s1 --prefix s1b` 汇总；三题库的三题用各自 label
（`default_nginx_proc_r1` / `method_nginx_proc_r1` 等）；正式结果回填到
[CASES_component_first.md](../CASES_component_first.md) 的案例表。

## 4. 注意事项

- 14 个任务里只有 8 个有 primary 组件；`v2_shared_library`、`v2_foundation_full`、
  `v2_nginx_full`、`v2_curl_build`、`l2_opencv_highgui`、`negative_win32_eventlog`、
  `v2_libgit2_util_full` 是边界/整层/负对照/pilot，检索可能选不到组件，结果按角色分开报告。
- `v2_libgit2_util_full` 是 pilot，不计入主统计。

## 5. 本轮运行与作废记录（2026-11-23）

启动门禁与并发：

- `bench_batch.py` 启动前先跑 `tools/preflight_tasks.py`，检查命令用到的程序在镜像里存在、
  gold 不触发自己的 api 门禁、`SharedLibraryTest` 带 `LD_LIBRARY_PATH`、固定端口不冲突；
  任一失败拒绝启动。
- 所有 `prepare.sh` 调用点用 `flock ~/.cache/migration-bench/prepare.lock` 串行化（`bench_batch`
  与 `agent_trial._prepare`）。

已确认的 harness/环境缺陷（不计入方法结果，作废后重跑）：

| label | 现象 | 原因 | 处置 |
|---|---|---|---|
| `s1_default_v2_path`、`s1_default_v2_file`、`s1_default_v3_poco_fs_stack`、`s1_method_v2_path`、`s1_method_v3_poco_fs_stack` | 并发 prepare 竞争 | 两个批次同时跑 prepare | 已归档 `_infra_errors/*_concurrent_prepare`；prepare 加 flock 后以 `s1f`/`s1` 重跑 |
| `s1b_*_synthetic_multi_call_site` | `cmp: command not found` | Kylin 镜像无 diffutils | 探针改用 `md5sum`；归档 `_probe_cmp_missing`；`s1e` 重跑 |
| `s1c_*_v2_curl_thread` | api 门禁命中 Win32 分支 | prompt 与门禁不一致 | 对齐 prompt 后归档 `_prompt_gate_misaligned`；`s1d` 重跑 |
| `s1_method_v2_file`、`s1_method_v3_poco_fs_stack`、`s1_method_v2_nginx_files`、`s1b_method_v2_curl_file`、`s1e_method_synthetic_multi_call_site` | `FileExistsError: retrieval output already exists`，bundle 未生成 | 中断的第一轮留下 `attempts/retrieval_v1`，重跑时 retrieval 拒绝复用输出目录 | `migration_trial.py` 每次 method attempt 开始时清掉上次遗留的 `method/` stage 面；归档 `_stale_stage_state`；`s1g` 重跑 |
| `s1g_method_synthetic_multi_call_site` | api_removal 只命中注释 | `src/posix/mc_platform_posix.c:152` 注释写着 “matching … GetFileSize behaviour”，实现本身是 `fstat`；门禁把注释当代码 | `shared/harness/api_removal.py` 扫描前剥离 C/C++ 注释（保留行号，字符串不动）；归档 `_infra_errors/*_comment_gate_overreach`；`s1h` 重跑 method 臂 |
| `s1_method_v2_shared_library` | retrieval `NoValidatedSubmission`，bundle 未生成 | retrieval 子提示词仍留 mini-swe-agent 时代的要求「Each response must contain exactly one Bash code block」；DSH 下模型把命令写进最终文本而不是调用 `controlled_bash`，运行即结束，校验器拒绝。`docs/dsh_migration_plan.md` §8 本就要求删掉这一条 | 两个 retrieval 系统提示词改为显式「用 `controlled_bash`，不要把命令写进最终回答」；归档 `_infra_errors/*_prompt_text_answer`；`s1i` 重跑 method 臂 |
| `s1_default_v2_curl_build` | build/tests/TLS 探针全过，`api_removal` 返回 `error`：`missing source dir: .../work/CMake` | 门禁按大小写敏感解析 `source_dirs`；任务写的是参考树的 `CMake`，agent 合法地把模块放在小写 `cmake/`（内容无被移除 API），门禁就把“声明路径不存在”当成错误 | `shared/harness/api_removal.py` 对 `source_dirs` 做大小写不敏感解析；仅当**所有**声明路径都不存在才报错（其余记 `missing_source_dirs`）。归档 `_infra_errors/s1_default_v2_curl_build_api_gate_case_mismatch`；`rerun_default_curl_build.sh` 以 `s1k` 重跑 default 臂 |
| `s1_method_v2_nginx_full` | `AgentProcessError`（1009 s）：DSH 拒绝 `controlled_bash` 调用，arguments 不是合法 JSON（`"cwd": /workspace` 路径未加引号），会话在第 107 步终止，留下半成品构建（`ngx_resolver.c` 的 `-Werror=maybe-uninitialized`） | 模型输出的工具调用 JSON 格式错误，dsh 直接终止而不是把解析错误回传给模型（`dsh-llm-pi-ai` 在 `toolcall_end` 遇到 `argumentsError` 即抛 `MALFORMED_RESPONSE`）；57 次 attempt 中共两次，另一例 `s1_method_v2_curl_tls` 在 924 次调用后才出现、工作区已完整故仍判 PASS | 归档 `_infra_errors/s1_method_v2_nginx_full_malformed_tool_json`；`rerun_method_nginx_full.sh` 在当前批次结束后以 `s1j` 重跑 method 臂 |
| `goldq_v2_curl_build` | CMake configure 失败：`CMake/CurlTests.c` 不存在 | judge 从 pristine 树复制后再覆盖 agent 可见文件；`agent_view.is_hidden_path` 的「cmake 目录是构建支持」豁免只写小写 `cmake`，curl 的 `CMake/CurlTests.c`（`try_compile` 探针）被误判为测试材料丢弃。宿主 `gold_sanity` 不经过覆盖层，所以没暴露 | 目录判断改为大小写不敏感；`goldq2_v2_curl_build` 重跑 PASS（59.5 s）。该误判同样会影响写了 `CMake/CurlTests.c` 的 agent 运行 |

已确认的真实结果（计入统计）：

| label | 结果 | 耗时 | 判据 |
|---|---|---:|---|
| `s1f_default_v2_path` | PASS | 1340 s | 修复 `LD_LIBRARY_PATH` 后的 default 臂 |
| `s1d_default_v2_curl_thread` | PASS | 1157 s | build/tests/regression/api/target 全过 |
| `s1d_method_v2_curl_thread` | PASS | 818 s | method 选中 1 个 threading 组件，bundle 6 files |
| `s1_default_v2_rwlock_semaphore` | PASS | 1416 s | 同一 `LD_LIBRARY_PATH` 修复后 |
| `default_poco_proc_r1` | FAIL | 2115 s | `ProcessTest.testLaunchInvalidCommand`：Unix 分支要求 launch 成功、`wait()` 返回 72，agent 直接抛 `SystemException` |
| `method_poco_proc_r1` | FAIL | 2292 s | 同一个 launch 语义：`testLaunchEnv`（`TestApp`）和 `testLaunchInvalidCommand` 都抛 `Cannot launch process` |
| `s1_default_v2_thread` | PASS | 2228 s | 全部门禁通过 |
| `s1_default_v2_curl_tls` | PASS | 2310 s | 全部门禁通过 |
| `s1_method_v2_rwlock_semaphore` | PASS | 1384 s | method 选中 threading 组件后通过 |
| `s1g_method_v2_file` | FAIL | 1804 s | 与 default 同一处：`FileTest.testFileAttributes1`，不存在的文件上属性查询应抛异常 |
| `s1g_method_v3_poco_fs_stack` | FAIL | 1758 s | `copy` 在 EINTR/短写时不重试（`poco_fs_sensitivity.cpp:113-131`），与 default 臂一致 |
| `s1g_method_v2_nginx_files` | FAIL | 641 s | `write` 在 EINTR/短写时不重试（`ngx_files_sensitivity.c:218-264`），与 default 臂一致；gold 正控 PASS |
| `s1h_method_synthetic_multi_call_site` | PASS | 229 s | 剥离注释后 api_removal 通过；build/tests/api_removal/target_api 全过，bundle 1 个组件、6 个文件 |
| `s1g_method_v2_curl_file` | PASS | 2633 s | method 选中 1 个组件（6 个文件）；build/tests/api_removal/target_api 全过（该题无 regression gate） |
| `s1_default_v2_libgit2_util_full` | FAIL（pilot） | 1495 s | build/tests 全过；`api_removal` 命中 `src/util/unix/pthread.h:15` 的 `#if defined(_MSC_VER)` 分支。该目录被 prepare 整体移除、gold 恢复了纯 POSIX 版本（无 `_MSC_VER`），agent 重建时把上游的 MSVC 分支带了回来——真实门禁失败 |
| `s1_method_v2_curl_tls` | PASS | 9384 s | method 选中 2 个组件（8 files）；build/tests/api_removal/target_api 全过。用时 2.6 h、924 次工具调用；结束时 DSH 又报一次 `MALFORMED_RESPONSE`（`"cwd": /workspace` 未加引号），但工作区已完整，judge 照常判 PASS |
| `s1_method_v2_foundation_full` | FAIL | 4214 s | method 选中 2 个组件；build ok，127 个测试中 6 failures + 2 errors：`FileTest.testFileAttributes1`（同 `v2_file`）、`PathTest.testStatics`（同 `v2_path`）、4 个 `DirectoryIteratorsTest`、`FileTest.testCopyDirectoryFailIfExists`（自复制递归直到路径超长）、`ProcessTest.testLaunchInvalidCommand`（同 POCO process 题）。与 default 臂的失败面一致，属真实迁移缺陷 |
| `s1_default_negative_win32_eventlog` | FAIL（负对照） | 218 s | 报告写到了嵌套 `work/PORTING_NOTES.md`；prompt 开头已明确「`work/...` 相对 `/workspace`，不要建嵌套 `work/`」，hidden test 查 `{work}/PORTING_NOTES.md` 因此失败。内容本身合格（24 KB，API/替代方案/重设计都说到了），是位置违规 |
| `s3_method_negative_win32_eventlog` | PASS（负对照） | 353 s | retrieval 校验通过、0 组件；编排层修复后继续判分，`PORTING_NOTES.md` 写到 `/workspace/PORTING_NOTES.md`（23,750 bytes），hidden test 与 `api_removal`（`expect_fail`）通过。`outcome=retrieval_no_match` 只标记检索结果，不再阻断 judge。修复前的 `s1_method_negative_win32_eventlog`（467 s）把校验通过的 0 组件 bundle 当成工作流失败（`status=error`，judge 未运行） |
| `s1_method_v2_curl_build` | retrieval_no_match（旧记录） | 880 s | 5 个组件都不覆盖构建系统移植；校验通过、0 组件。旧编排下 judge 跳过；按新逻辑重跑会进入正常判分 |
| `s1_default_v2_foundation_full` | FAIL | 2153 s | build ok；`testThreadTarget`、`testThreadFunctor` 失败后 `testSleep` 抛 `Poco::NullPointerException`。agent 在第 150 步到达上限（`LimitsExceeded`），但已构建完成并进入自查，delivered 状态是真实失败：`Thread_POSIX.cpp` 启动线程用了 `PTHREAD_CREATE_DETACHED`，`joinImpl` 只等内部 `done` 事件而不 `pthread_join`（gold 为 joinable + `pthread_join`）。镜像内 gold 正控 `goldq_v2_foundation_full` PASS（684.4 s），题目与门禁无问题 |

空选择（`retrieval_no_match`）是合法的检索结果，但不再是流程终点：只要 bundle materialize 成功，attempt 就继续跑 hidden/regression/api 门禁，并按 pass/fail 计入结果。`s1` 中 `v2_path`、`v2_shared_library` 等旧 attempt 仍保留当时的记录（0 组件时 judge 被跳过）；用当前代码重跑会进入正常判分。`tools/bench.py compare` 仍把这类 attempt 单列为 `RETRIEVAL_NO_MATCH`，但与 `INVALID_METHOD`（工作流不可用/无 bundle）严格区分。负对照 `s3_method_negative_win32_eventlog` 是修正后的首个验证：0 组件、继续判分、PASS。

本轮补的 gold 正控（独立快照、`--no-prepare`）：

| 任务 | 结果 | 耗时 | 说明 |
|---|---|---:|---|
| `v3_poco_fs_stack` | PASS | 754.9 s | build/tests/regression/api_removal/target_api 全过（`reports/gold_sanity/v3_poco_fs_stack.json`）；此前没有任何正控，两臂的 `copy` EINTR 失败因此判定为真实缺陷 |
| `v2_curl_tls` / `v2_curl_build` / `v2_foundation_full` | 全部 PASS（镜像内） | — | 只有旧 id 的 `l2_curl_tls`/`l3_curl_build` 报告。`gold_sanity.py` 在宿主机跑 harness，curl 两题因宿主缺 OpenSSL 15 s 内失败；改用镜像内 `bench.py run --seed-gold --fake-model --no-prepare`（`gold_judgecheck_queue.sh`）重做控制：`goldq_v2_curl_tls` 64.1 s、`goldq2_v2_curl_build` 59.5 s（修复覆盖层缺陷后）、`goldq_v2_foundation_full` 684.4 s（五项门禁全过）。`v2_nginx_files` 保真度抽查 PASS（48 s）。`v2_foundation_full` 宿主快照复跑 PASS（660.0 s） |

注意：`gold_sanity.py` 与正式 judge 的环境不同（宿主 vs `migration/kylin:sp3-p2`）。凡是对编译器/库探测敏感的题，正控以镜像内 `--seed-gold --fake-model` 结果为准；`tools/preflight_tasks.py` 的 gold 正控规则同时接受这两类报告。
- 负对照的“正确”结果是不移植，不计入通过率。