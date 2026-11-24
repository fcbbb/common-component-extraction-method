# Windows → Kylin：组件优先的案例扩展待办

- 建立：2026-11-23
- 目标：在本场景内把流程固定为「先建组件库，再围绕组件能力构造任务」，并产出多个可配对的案例。
- 现状：`library_generated/demo_new_flow_v4` 只有 1 个组件（仅来自 `l2_libuv_fs`），只验证了 `v3_poco_fs_stack` 1 个任务、每条件 1 次运行。

## 完成标准

1. 全量 5 个 `library_source` 建库任务参与抽取，发布一个冻结的完整组件库。
2. 产出「组件 × held-out 任务」能力矩阵，能直接看出：一个组件服务哪些任务、一个任务用到哪些组件。
3. 至少新增 3 个任务包（补 slate 缺口），全部通过静态校验与 gold 正控。
4. 至少 3 个新案例完成 default / method / gold 三臂配对，method 通过而 default 失败。
5. 每个案例有可复现记录：命令、库版本、`attempt.json`、判分结果、成本、判别规则。

## A. 建库底座（先做）

- [x] A1 冻结语料校验：5 个 example 的 `index.json`/`lock.json` 完整性通过（177 文件，digest `10f18c2a…ffee3`）。
- [x] A2 全量抽取：5/5 example 通过 extract → curate → review → revise → publish → verify，发布 5 个组件到 `library_generated/full_20261123/library/`。
  - 首轮 `l2_libarchive_read_disk` 因 `boundary` 返回 list 被 curate 拒绝；原响应归档 `history/runs/rejected/`，重跑后通过。
- [x] A3 组件质量门槛：5/5 `review_verdict=publish`；`verify_library` 通过（无 held-out project、无缺文件、component_count 一致）；能力分布：file-system/io ×1、file-system/metadata ×2、process ×1、threading ×1。
- [x] A4 冻结与记录：`library_lock.json` 已写入；组件清单、digest、复现命令与边界记录在 [LIBRARY_full_20261123.md](LIBRARY_full_20261123.md)。
  - 结论：库与 `history/runs/` 继续按既有约定不提交，按文档命令重建。

## B. 能力 → 任务矩阵

- [x] B1 组件结构化索引：`tools/component_task_matrix.py` 读取 manifest + component.json，导出 capability、provenance、API token、operation family。
- [x] B2 任务侧扫描：读取每个任务包的 `task.yaml` 与 `work/`，统计源侧 API token 与 operation term。
- [x] B3 产出 [capability_matrix/matrix.md](capability_matrix/matrix.md) 与 `matrix.json`：5 组件 × 25 任务（19 已打包 + 6 计划）；primary/secondary 分层。
  - 每个组件都服务 ≥2 个任务；8 个任务有 ≥2 个 primary 组件。
  - 计划任务命中：process 组件 → `v2_poco_process`、`v2_nginx_process`；threading 组件 → `v2_nginx_thread`、`v2_curl_thread`；file 组件 → `v2_curl_file`。
- [x] B4 审计：仓库隔离（library_source 不进 held_out）、无 gold 泄漏、候选任务可构建。
  - 机械检查：库 provenance 仅含 libuv/libarchive，`verify_library` 无 held-out 命中。
  - 人工复核：process/thread/file 三类组件到 held-out 任务的 primary 映射均成立；计划任务 `v2_curl_thread`、`v2_curl_file` 的命中由标题与操作词支撑，待打包时再复核可构建性。
  - `v2_poco_process`、`v2_nginx_process`、`v2_nginx_thread` 均已在生成库存在后建包，静态校验通过，gold 正控见 C4。

## C. 按矩阵构造任务

- [x] C1 用矩阵选定新增任务，优先补 slate 缺口：`v2_poco_process`、`v2_nginx_process`、`v2_nginx_thread`、`v2_curl_thread`、`v2_curl_file`、`synthetic_multi_call_site`。
  - 已建包：`v2_poco_process`（process 组件）、`v2_nginx_process`（process 组件）、`v2_nginx_thread`（threading 组件）。
  - 暂缓：`v2_curl_thread` / `v2_curl_file`——curl 的 threaded resolver 与 file:// 处理没有独立的 Windows→Unix 平台实现文件，强行切分会把通用实现当成迁移面；需先找到真实平台层（或换仓库）再建包。`synthetic_multi_call_site` 无 primary 组件，继续暂缓。
- [ ] C2 每个新任务写 `task.yaml`（`library_manifest` 指向冻结库）、`harness/` 隐藏测试、api/behavior/regression gates、`provenance.json`。
  - `v2_poco_process` 已建包：prepare.sh、task.yaml、provenance.json、README、harness/config.json、harness/check_api_removal.sh；`library_manifest` 指向 `full_20261123`。
  - `v2_nginx_process` 已建包：移除 `src/os/unix/ngx_process.c`、`ngx_process_cycle.c`、`ngx_channel.c`、`ngx_daemon.c`；隐藏测试为静态 smoke + master/worker 生命周期探针 + `worker_channel.t`、`worker_shutdown_timeout.t`；组件映射到 process 组件。
  - `v2_nginx_thread` 已建包：移除 `src/os/unix/ngx_thread_mutex.c`、`ngx_thread_cond.c`、`ngx_thread_id.c`；隐藏测试为原语 sensitivity 程序 + smoke + `aio threads` 线程池探针；组件映射到 threading 组件。
- [ ] C3 `tools/verify_task.py` + `tools/check_pins.py --offline` 通过。
  - `v2_poco_process`：verify_task 通过（无 error/warning）。
  - `v2_nginx_process`：verify_task 通过（无 error/warning）；已用 gold 手工跑通全部隐藏测试（smoke、probe、prove 2/2）。
  - `v2_nginx_thread`：verify_task 通过（无 error/warning）；已用 gold 手工跑通全部隐藏测试（sensitivity、smoke、thread probe）。
- [ ] C4 每个新任务跑 gold 正控。
  - `v2_poco_process`：首轮失败原因已定位——`ProcessTest` 用相对名 `TestApp` 启动子进程，`execvp` 按 PATH 查找，而测试从 `{build}/bin` 运行且当时 PATH 不含该目录。已在 `task.yaml`/`harness/config.json` 的测试命令前加 `PATH="$PWD:$PATH"`；用同一次 gold 构建直接复跑 `ProcessTest ProcessRunnerTest` 得到 `OK (10 tests)`。
  - 第二轮 gold 在构建中途遇到 `work/` 被外部重写（`StringTest.cpp` 等源文件短暂消失，`.source_commit` 与 `gold/` 时间戳落在运行末尾），不是代码问题。改为在 `library_generated/gold_snapshots/v2_poco_process/` 的独立快照上跑，避免与其它任务/会话共用 `work/`。
  - 快照 gold 正控 PASS（2126.7 s，label `new_poco_process_snapshot`；build/tests/regression/api_removal/target_api 全 pass；`ProcessTest ProcessRunnerTest` 通过）。证据 `reports/gold_sanity/summary.json`；运行后已用 `tools/clean_gold_from_work.py` 清掉快照与原任务 `work/` 中的 `Process_UNIX.cpp`。
  - `v2_nginx_process`：gold 正控 PASS（276.9 s；build/tests/api_removal/target_api 全 pass）。
  - `v2_nginx_thread`：gold 正控 PASS（302.1 s；build/tests/api_removal/target_api 全 pass）。
- [x] C5 明确多对多覆盖：至少 1 个组件被 ≥2 个任务引用，至少 1 个任务引用 ≥2 个组件。
  - process 组件 → `l2_libuv_process`、`v2_nginx_process`、`v2_poco_process`；threading 组件 → `v2_thread`、`v2_rwlock_semaphore`、`l2_libuv_thread`、`v2_nginx_thread`、`v2_curl_thread`、`v2_curl_tls`。
  - `v3_poco_fs_stack`、`v2_file`、`v2_path`、`v2_nginx_files`、`v2_curl_file` 等 8 个任务有 ≥2 个 primary 组件（见 `capability_matrix/matrix.md`）。

## D. 配对验证

- [ ] D1 对每个新案例跑 default / method / gold，每条件 ≥3 次。
  - gold：`v2_poco_process` 快照 PASS（2126.7 s）、`v2_nginx_process` PASS（276.9 s）、`v2_nginx_thread` PASS（302.1 s），各 1 次正控。
  - default r1：`v2_nginx_process` **FAIL**（1779.9 s，`default_nginx_proc_r1`）。构建成功、静态 smoke 通过，master/worker 探针在 `SIGQUIT` 处失败：`NGINX_PROCESS_PROBE=FAIL master 2565 did not exit on SIGQUIT`。即直接迁移能编过、能起 worker、能 reload，但没恢复“退出信号必须让 master 结束并回收 worker/pid 文件”的生命周期契约。
  - method r1 首次尝试作废（基础设施错误，不计入结果）：retrieval-only 条件必须用 `--bundle` 把冻结库挂到 `outputs/full_library`，否则 retrieval block 的前置 artifact 缺失，stage 返回 `STAGE_INPUT_MISSING`，外层 agent 拿不到组件包。记录归档在 `reports/bench/_infra_errors/method_nginx_proc_r1_no_bundle/`。
  - 已修正队列命令：method 臂增加 `--bundle v3/windows_to_kylin/library_generated/full_20261123/library`；`v2_nginx_thread` default 的首次启动与队列一起中止，归档为 `_infra_errors/default_nginx_thread_r1_aborted/`。
  - 队列（`library_generated/run_queue_arm1.sh`）已重启，按序跑：`v2_nginx_process` method r1 → `v2_nginx_thread` default/method r1 → `v2_poco_process` default/method r1。
- [ ] D2 记录 `attempt.json`、`selection.json`、调用次数、耗时、失败模式。
  - 已新增 `tools/collect_case_results.py`：从 `reports/bench/<label>/<task>/run*/attempt.json` 汇总臂别、各 gate、耗时、调用次数、token、组件 bundle 与失败提示；method 臂会读 `method/tasks/<task>/outputs/full_library/` 里的组件清单。
  - 用法：`../.venv/bin/python tools/collect_case_results.py --label default_<case> --label method_<case>`（或 `--format json`）。
- [ ] D3 产出案例登记表：`任务 × 组件 × 三臂结果 × 证据路径`。
- [ ] D4 更新结论边界，区分「方法有效」与「单个案例偶然通过」。

## F. 20 题批量评测（2026-11-23 追加）

- [x] F1 定义 20 题集：`slate.yaml` 去掉 5 个 `library_source`，剩余 17 个已建包题 + 3 个待建包题（`v2_curl_thread`、`v2_curl_file`、`synthetic_multi_call_site`）。见 [suite20/SUITE20.md](suite20/SUITE20.md)。
- [x] F2 并行执行器 `tools/bench_batch.py`：固定并发、同一任务同时只跑一个臂、断点续跑；运行前串行执行 `prepare.sh`（并发 prepare 会在共享 cache 仓上互相打架），运行阶段统一 `--no-prepare`。
  - 2026-11-23 补：所有 `prepare.sh` 调用点（`bench_batch`、`agent_trial._prepare`）统一用 `flock ~/.cache/migration-bench/prepare.lock` 串行化，跨批次也不会再抢同一个 cache 仓。
  - 新增启动前静态预检 `tools/preflight_tasks.py`，`bench_batch` 默认先跑、任一任务失败就拒绝启动：检查 hidden/regression 命令与 harness 脚本用到的程序在 `migration/kylin:sp3-p2` 镜像里是否存在、gold 自身是否触发 api_removal、`SharedLibraryTest` 是否缺 `LD_LIBRARY_PATH`、固定端口是否跨任务冲突。目的就是不再等 30–60 分钟跑完才发现命令/镜像不一致。
  - 2026-11-23 补：预检再加一条「gold 正控」规则——凡是 `gold/` 非空的任务，`reports/gold_sanity/` 里必须有一份 `status=pass` 的报告，否则 `FAIL`；报告比 `gold/` 旧只给 `WARN`。起因是 `v3_poco_fs_stack` 此前没有任何 gold 正控，两臂在同一组 `copy` 敏感性断言上失败时无法区分「真实缺陷」和「门禁过严」。审计结果：`v3_poco_fs_stack`、`v2_curl_tls`、`v2_curl_build`、`v2_foundation_full` 四题缺 pass 报告（前两者只有旧 id 的 `l2_curl_tls`/`l3_curl_build`，后者旧报告是 fail）。已在独立快照上串行补跑（`gold_controls_queue.sh`）：`v3_poco_fs_stack` PASS（754.9 s，五项门禁全过，`reports/gold_sanity/v3_poco_fs_stack.json`）——因此该题两臂在 `copy` EINTR/短写上的失败判为真实缺陷；`v2_curl_tls`/`v2_curl_build`/`v2_foundation_full` 排队中，完成前结果标为「控制待定」。
  - 2026-11-23 18:40 记：`gold_sanity.py` 实际是在**宿主机**上执行 `shared/harness/runner.py`（report 里 `CMAKE_COMMAND` 指向 `~/.local/lib/python3.12/site-packages/cmake/data/bin/cmake`），不是 `migration/kylin:sp3-p2` 镜像。curl 两题因此 15 s 内就失败于宿主缺 OpenSSL（`Could NOT find OpenSSL ... OPENSSL_CRYPTO_LIBRARY/OPENSSL_INCLUDE_DIR`），而同一任务在镜像里正常构建——这是控制保真度问题，不是题目缺陷。统一补一份镜像内正控：`bench.py run --seed-gold --fake-model --no-prepare`（gold 拷进新工作区、假模型不动它，judge 仍在镜像里跑），脚本 `gold_judgecheck_queue.sh` 对 `v2_curl_tls`、`v2_curl_build`、`v2_nginx_files`（宿主已 PASS，作保真度抽查）、`v2_foundation_full` 依次执行。之后 `tools/preflight_tasks.py` 的 gold 正控规则同时接受 `reports/gold_sanity/*.json` 与 `reports/bench/gold*/**/attempt.json` 的 pass。已出结果：镜像内 `goldq_v2_curl_tls` PASS（64.1 s，build/tests/api_removal/target_api 全过，`gold_seeded=[lib/vtls/openssl.c]`）；`goldq_v2_foundation_full` PASS（684.4 s，build/tests/regression/api_removal/target_api 全过，17 个 gold 文件）；`goldq_v2_nginx_files` PASS（48 s，保真度抽查）；宿主快照上的 `v2_foundation_full` 复跑 PASS（660.0 s，此前 95 s 的 fail 是宿主侧瞬时环境问题）。
  - 2026-11-23 19:05 记：`goldq_v2_curl_build` 镜像内 build 失败（31.9 s）：`Cannot find source file .../work/CMake/CurlTests.c`。judge 的 `_make_judge_work` 先复制 pristine `work/`，再只覆盖 agent 可见文件；`agent_view.is_hidden_path` 里「cmake 目录是构建支持」的豁免写的是 `parts[0] != "cmake"`，curl 的目录是 `CMake/`，于是 `CMake/CurlTests.c`（CMake `try_compile` 探针，构建必需）被当成测试材料，既不进 agent 视图也不进覆盖层；而 `v2_curl_build` 的 `prepare.remove` 又整目录删掉了 `CMake/`，pristine 树里也没有，最终 configure 找不到它。宿主 `gold_sanity` 是在原地恢复 gold，不经过覆盖层，所以之前的宿主正控掩盖了这个缺陷。已把目录判断改为大小写不敏感（回扫确认只影响 curl 三题的这个文件；`tests/data/test3000` 等真实测试仍为 hidden），`goldq2_v2_curl_build` 重跑 PASS（59.5 s，build/tests/api_removal/target_api 全过），preflight 对 `v2_curl_build` 恢复 OK。普通 agent 若自己写 `CMake/CurlTests.c` 也会被同一规则丢弃，所以这是全局修复。至此 20 题里所有带 gold 的任务都有可用正控（宿主或镜像内）。
- [ ] F3 本轮批量：14 题 × default/method = 28 个 job（`suite20/tasks_run1.txt`），3 并发；另 3 题由三题库覆盖，3 题走 run2。
  - `bench_batch.py --tasks-file suite20/tasks_run1.txt --arms default,method --workers 3 --prefix s1` 已启动；串行 prepare 完成，3 个 default job 在跑。
  - 发现并修正 regression 环境缺陷：10:34 的整合提交给 `v2_file`/`v2_path`/`v2_thread`/`v2_rwlock_semaphore` 的 regression 加了 `SharedLibraryTest`，但没带库搜索路径；`dlopen("TestLibrary.so")` 不搜当前目录，导致 `v2_path` default（2920.1 s）build/tests 通过而 regression 5 个用例 ERROR。已把这 4 个任务的 hidden/regression 命令统一为 `LD_LIBRARY_PATH={build}/bin PATH={build}/bin:$PATH`（与 `v3_poco_fs_stack` 一致），`verify_task` 重新通过；在 `gold_snapshots/v2_path_ldpath` 独立快照上 gold 复核 PASS（853.5 s，build/tests/regression/api_removal/target_api 全 pass，`reports/gold_sanity/v2_path.json`）。
  - `v2_path` default 的这次结果按环境缺陷处理，已用 `--prefix s1f`（单臂 default、带 prepare）重跑；`v2_file` default 在修改前已启动，但其失败点在 hidden test 而非 regression，属真实结果，无需重跑。
  - `v2_file` default（3454 s）hidden test 真实失败：`FileTest.testFileAttributes1` 要求不存在的文件上 `canRead/canWrite/isFile` 抛异常，agent 实现返回 false；gold 用 `handleLastErrorImpl` 抛出。属迁移行为缺陷，计入结果。
  - `synthetic_multi_call_site` 两臂 tests 失败是 probe 缺陷：`mc_probe.sh` 用了 `cmp`，Kylin 镜像无 diffutils（`cmp`/`diff` 均缺）。改为 `md5sum` 内容比较后 gold 复跑 PASS（84.4 s，`gold_synthetic_r2`）；旧两次归档为 `_infra_errors/*_probe_cmp_missing`，用 `s1e` 重跑两臂。
  - `v2_path` method 是「检索无匹配」：retrieval 对 catalog 5 个组件选中 0 个，bench 按设计判为 invalid（不计入 method 结果），需在汇总里单列 `retrieval_no_match`，不能算方法失败。
  - `suite20/tasks_run2.txt` 覆盖新补的 3 题，`--skip-prepare --prefix s1b --workers 2` 启动；`v2_curl_file`、`synthetic_multi_call_site` 先跑（`tasks_run2_now.txt`），`v2_curl_thread` 待 gold 通过后补进 `s1c`。
  - 2026-11-23 18:00 记：中断恢复后第一批 method job 成批 rc=2（`s1_method_v2_file` / `s1_method_v3_poco_fs_stack` / `s1_method_v2_nginx_files` / `s1b_method_v2_curl_file` / `s1e_method_synthetic_multi_call_site`），根因是中断时被杀的那一轮留下了 `attempts/retrieval_v1`：retrieval 步骤 `FileExistsError: retrieval output already exists`，`component_bundle` 从未 materialize，agent 本身是 Submitted。已修 `tools/migration_trial.py`：每次 method attempt 开始前删掉同 label 上一次留下的 `method/` stage 面（stage 状态只属于一次 attempt，工作区本来就是每次重拷的）。5 个 label 归档为 `_infra_errors/*_stale_stage_state`，用 `--prefix s1g --workers 2` 重跑。
  - 2026-11-23 18:45 记：`s1g_method_synthetic_multi_call_site`（195 s）api_removal 误报——`src/posix/mc_platform_posix.c:152` 的注释「matching the reference implementation's GetFileSize behaviour」命中了 `source_regex`，实际实现是 `fstat`。api 门禁是代码门禁，注释不是对被移除 API 的使用。已在 `shared/harness/api_removal.py` 增加 `strip_c_comments`：扫描 C/C++ 源文件前把 `//` 与 `/* */` 注释体替换为空格（保留行号；字符串/字符字面量保持原样），该尝试归档为 `_infra_errors/*_comment_gate_overreach`，用 `--prefix s1h` 重跑 method 臂；`s1h_method_synthetic_multi_call_site` PASS（229 s，build/tests/api_removal/target_api 全过）——门禁修复验证通过。已回扫 `reports/bench` 全部 attempt，这是唯一一处 api_removal 只命中注释的情况。judge 容器把仓库只读挂到 `/bench` 并直接执行 `shared/harness/runner.py`，因此该修复不需要重建镜像。
  - 2026-11-23 19:00 记：`s1_method_v2_shared_library`（322 s）bundle 缺失。retrieval 子 agent 的 trajectory 只有一次模型调用：它把 `cat /retrieval-tools/component_catalog.json` 写成了**最终文本里的 Bash 代码块**，没有调用 `controlled_bash`，DSH 视为 turn 结束，`state.json` 为 `NoValidatedSubmission`。根因是 `src/component_method/retrieval/prompts/retrieve_methodology_system.txt`（以及 `retrieve_system.txt`）仍带着 mini-swe-agent 时代的「Each response must contain exactly one Bash code block」；`docs/dsh_migration_plan.md` §8 明确要求删掉这条。已改为「每个命令都调用 `controlled_bash`；不要把命令写进最终回答」。15 次 retrieval 里只出现这一次 `NoValidatedSubmission`，属于提示词与工具协议不一致（模型相关但系统性），归档为 `_infra_errors/*_prompt_text_answer`，用 `--prefix s1i` 重跑 method 臂。外层 agent 在 stage 失败后自行做了整个移植但没有 bundle，harness 正确判为 error，不会变成 pass。
  - `s1i_method_v2_shared_library` 重跑结果：retrieval 校验通过，但 `selected_bundle_ids` 为空（5 个组件都不覆盖动态加载），bundle 的 `component_count=0`。这是合法的「检索无匹配」，与 `v2_path` 同类，不计入方法结果。已让 `migration_trial.py` 对这种“校验通过但 0 组件”的 method attempt 写 `outcome=retrieval_no_match`，`bench.py compare` 单列 `RETRIEVAL_NO_MATCH`，不再与工作流失败混在一起。
  - `s1g_method_v2_curl_file` PASS（2633 s，method 选中 1 个组件 / 6 个文件，build/tests/api_removal/target_api 全过）。`s1g` 收尾：`v2_file`、`v3_poco_fs_stack`、`v2_nginx_files` 为真实 FAIL（与 default 臂同因），synthetic 的旧尝试作废后由 `s1h` PASS。
  - 2026-11-23 20:55 记：`s1_default_v2_curl_build`（1473 s）build/tests/TLS 探针都过，但 `api_removal` 报 `error`：`missing source dir: .../work/CMake`。任务 `source_dirs` 写的是参考树的 `CMake`，agent 把 CMake 模块放在小写 `cmake/`（`CURLConfig.cmake.in`，无被移除 API）——Linux 大小写敏感，门禁把“声明路径不存在”直接当错误。已在 `shared/harness/api_removal.py` 加大小写不敏感解析，并把缺失路径降级：只有**全部**声明路径都不存在时才 `error`，否则记 `missing_source_dirs` 继续扫描。用 agent 工作区验证：api gate pass、target_api pass、全缺失时仍 error。该 attempt 归档 `_infra_errors/s1_default_v2_curl_build_api_gate_case_mismatch`，`rerun_default_curl_build.sh` 等当前批次结束后以 `s1k` 重跑 default 臂。
- 2026-11-23 21:05 记：`s1_method_v2_curl_tls` PASS（9384 s，2.6 h，924 次工具调用，method 选中 2 个组件 / 8 files，四项门禁全过）。结束时 DSH 再报一次 `MALFORMED_RESPONSE`（同样的 `"cwd": /workspace` 未加引号），但工作区已完整，judge 照常 PASS。至此该模式共两次/57 次 attempt，均是 method 长跑；来源是 `dsh-llm-pi-ai` 在 `toolcall_end` 见到参数解析错误就抛错终止会话，不会把错误回传给模型。
- 2026-11-23 20:55 记：`s1_method_v2_foundation_full` FAIL（4214 s，335 次工具调用，Submitted）。bundle 2 个组件，build ok；127 个测试 6 failures + 2 errors：`FileTest.testFileAttributes1`、`PathTest.testStatics`、4 个 `DirectoryIteratorsTest`、`FileTest.testCopyDirectoryFailIfExists`（复制到自身子目录时无限递归直到路径超长）、`ProcessTest.testLaunchInvalidCommand`。失败面与 default 臂及 `v2_file`/`v2_path` 一致，真实迁移缺陷。
- 2026-11-23 20:55 记：负对照 `negative_win32_eventlog`。default 臂 FAIL（218 s）：内容合格的 `PORTING_NOTES.md` 写到了嵌套 `work/` 子目录，prompt 已明确禁止且 hidden test 查 `{work}/PORTING_NOTES.md`；method 臂 `retrieval_no_match`（467 s）：校验通过、0 组件，方法臂对负对照的正确行为是不移植，但 0 组件时工作流不产出报告，judge 跳过——按设计单列“正确弃权”，不算方法失败。`s1_method_v2_curl_build` 同样是 `retrieval_no_match`（880 s）。
- 2026-11-24 修正：空选择不再中止方法臂。`migration_trial.py` 原先要求 `component_count > 0` 才算工作流成功，导致 retrieval 校验通过的 0 组件 bundle 被写成 `status=error` 且不跑 judge。现在只要 bundle materialize 成功就继续判分，`outcome=retrieval_no_match` 只作检索标记。重跑中发现 agent 仍把报告写到嵌套 `work/PORTING_NOTES.md`，根因是任务提示的 `work/...` 说明不够具体；已在 `shared/harness/agent_prompt.py` 增加示例（`work/foo` → `/workspace/foo`，不是 `/workspace/work/foo`）。`s3_method_negative_win32_eventlog` PASS（353.4 s）：0 组件、`tests=pass`、`api_removal=pass`（`expect_fail`），报告 23,750 bytes 位于 `/workspace/PORTING_NOTES.md`。`s1_method_v2_curl_build` 等旧记录保留原样，重跑会进入正常判分。
- 2026-11-23 19:25 记：`s1_method_v2_nginx_full`（1009 s，rc=1）`AgentProcessError`。dsh 报 `MALFORMED_RESPONSE: Tool call "controlled_bash": Unexpected token '/', ..."", "cwd": /workspace"... is not valid JSON`——模型把 `"cwd": /workspace` 写成了未加引号的路径，DSH 直接终止会话（第 107 步），留下半成品构建。bundle 本身没问题（8 files，ok）。56 次 attempt 里只出现这一次，属 agent 运行时/模型输出格式缺陷，不是方法结果；归档 `_infra_errors/s1_method_v2_nginx_full_malformed_tool_json`，`rerun_method_nginx_full.sh` 等当前批次结束后用 `s1j` 重跑 method 臂。
- `s1_default_v2_foundation_full` FAIL（2153 s，真实结果，非门禁缺陷）：build ok，hidden tests 在 `testThreadTarget`、`testThreadFunctor` 失败后 `testSleep` 抛 `Poco::NullPointerException`。agent 状态 `LimitsExceeded`（第 150 步），但已构建完成并在做自查（最后几步在审 `Process::times`/`SharedMemory`），delivered 代码本身就是坏的：新写的 `Thread_POSIX.cpp` 用 `PTHREAD_CREATE_DETACHED` 启动线程，`joinImpl` 只等内部 `done` 事件而不 `pthread_join`；gold 用 joinable 线程 + `pthread_join`，镜像内正控 `goldq_v2_foundation_full` PASS（684.4 s）。因此按真实 FAIL 记录，同时注明步数预算耗尽（该题是整层移植，150 步不足以完成自查）；若将来统一提高步数预算，需要两臂一起重跑。
  - `s1f_default_v2_path` PASS（1340 s），`s1d` 两臂 PASS（default 1157 s / method 818 s），`s1_default_v2_rwlock_semaphore` PASS（1416 s）——`LD_LIBRARY_PATH` 修复在真实 default 跑里也验证了。
  - `default_poco_proc_r1` FAIL（2115 s，真实结果）：`ProcessTest.testLaunchInvalidCommand`，Unix 语义要求 `Process::launch("InvalidCmd")` 成功返回 handle、`wait()` 返回 72，agent 实现直接抛 `SystemException: Cannot launch process`；gold 同环境 PASS，计入迁移缺陷。
- [ ] F4 剩余 3 题建包并加入批量。
  - `v2_curl_thread`（移除 `lib/curl_threads.c`，gold 为 POSIX 分支；隐藏测试检查 `AsynchDNS` + 经解析线程的 localhost 请求）。
  - `v2_curl_file`（移除 `lib/file.c`，gold 恢复；隐藏测试检查 file:// 读取、range、HEAD、百分号路径）。
  - `synthetic_multi_call_site`（4 个调用点共享 handle/分隔符/返回值约定；gold 为 `src/posix/mc_platform_posix.c`）。gold 正控 PASS（16.1 s，`gold_synthetic_r1`）。
  - `v2_curl_file` gold 正控 PASS（350.6 s，`gold_curl_file_r1`）。
  - `v2_curl_thread` gold 正控 PASS（459.6 s，`gold_curl_thread_r4`）。前三轮失败原因：`prepare.sh` 剥离 Win32 分支时按列 0 的 `#endif` 截断，把 Win32 代码留在 gold 里，导致 `#endif without #if` / 未声明符号；改为按嵌套深度配对后重新生成 gold（99 行，纯 POSIX）。
  - 三题均通过 `verify_task.py`；gold 运行后已用 `tools/clean_gold_from_work.py` 清 `work/` 并复验。
  - run2 三题全部启动：`s1b`（curl_file + synthetic）、`s1c`（curl_thread）。
  - `s1c` 两臂均因 api_removal 失败（default 1643.2 s / method 1597.2 s）：build ok、隐藏测试 pass，但 `lib/curl_threads.c` 里保留了 `#elif defined(USE_THREADS_WIN32)` 分支（默认写出与上游一致的跨平台文件），而 api 门禁按 token 扫描整文件。原 prompt 里「header 保留 POSIX 与 Win32 两套映射」被理解为两套实现都要写，属 prompt 与 validator 不一致，不是方法效果。
  - 修正方式（对齐 prompt，而不是放宽门禁）：`task.yaml` spec 与 README 明确「本移植退役 Windows 目标，`lib/curl_threads.c` 只保留 POSIX 实现，不得出现 windows.h/HANDLE/CreateThread/_beginthreadex/WaitForSingleObject/CloseHandle」；`verify_task` 重新通过。s1c 两次归档为 `_infra_errors/*_prompt_gate_misaligned`，不计入统计；以 `s1d` 重跑两臂。
- [ ] F5 汇总 20 题三臂结果，按 held-out / 边界 / 负对照 / pilot 分开报告。

## E. 自动化与文档

- [ ] E1 一键脚本：建库 → 冻结 → 矩阵 → 校验（幂等、可 resume）。
  - 已新增 `tools/component_first_pipeline.py`：`--stage corpus|extract|freeze|matrix|validate|gold`（可重复、`all` 为默认）。
    corpus 先 `--verify`，只有缺失或校验失败才重建；`library_lock.json` 已存在时跳过抽取；矩阵每次重算；
    validate 先清 `work/` 里的 gold 答案，再跑 `verify_task` 与 `check_pins --offline`；gold 需显式选择。
  - 已实测 `--stage corpus --stage freeze`：corpus digest 一致（177 文件），读出 5 个组件与库 digest。
  - `matrix`/`validate` 待当前三臂运行结束后实测（避免在 agent 改写 `work/` 时扫描）。
- [ ] E2 更新 `docs/current_state.md`、`SPLIT.md`、验证报告。

## 执行日志

- 2026-11-23：A1 通过（177 文件，digest `10f18c2a…ffee3`）；开始 A2。
- 2026-11-23：新增 `tools/component_task_matrix.py`，已用 `demo_new_flow_v4` 单组件库验证：
  `v3_poco_fs_stack`、`v2_file`、`v2_path`、`v2_nginx_files`、`l2_libuv_fs` 命中文件组件；
  process/thread 任务正确落空。待全量库生成后正式运行并提交矩阵。