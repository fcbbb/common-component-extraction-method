# Scenario A — Windows/MSVC C++ → 麒麟 V10 + GCC/CMake

## 1. 这个场景在测什么

给 agent 一个**真实上游仓库的固定快照**，删掉目标平台（Linux/POSIX）的实现文件，
只留下 Windows/MSVC 实现、公共头文件和上游测试。要求 agent 在麒麟 V10
（GCC + CMake）上重建目标平台层，使上游测试重新通过，且不把 Win32 API
重新引入。

和“自己写一个跨平台库再迁移”不同，这里的题目正文、调用方、构建系统、测试
全部来自上游仓库。agent 面对的是真实产品里那种“平台层被抽掉、上层业务代码
原封不动”的迁移任务。

- 源：仅 Windows 可编译的真实模块（`*_WIN32*.cpp`、`archive_*_windows.c`、
  `ngx_win32`、Schannel 等）。
- 目标：麒麟 V10 SP3，x86_64，GCC 13.3，CMake 3.28。
- gold：上游同一 commit 中已经存在的 POSIX/Unix 实现，`prepare.sh` 把它复制到
  evaluator-only 的 `gold/`，然后从 `work/` 删除。
- 判分：构建 + 指定的上游测试 + API 清除门 + 一个负向对照。

## 2. 任务包结构

每个任务是一个 **recipe**（不是把上游源码抄进仓库）：

```text
windows_to_kylin/tasks/<task_id>/
├── task.yaml          # 题目、构建命令、隐藏测试、门禁
├── provenance.json    # repo / commit / license / 删除的文件 / gold 文件
├── prepare.sh         # 克隆固定 commit → work/，复制 gold/，删除目标实现
├── gold/              # evaluator-only（prepare.sh 生成；用于人工核对）
├── harness/           # run_task.py / check_api_removal.sh / 共享脚本 shim
└── README.md
```

`prepare.sh` 使用 `MIGRATION_BENCH_CACHE`（默认
`~/.cache/migration-bench/repos`）缓存 blobless clone；同一仓库的多个任务
共享同一份缓存，不会重复下载。

## 3. 题目清单（20 题）

| 级别 | 任务 | 上游模块 | 被删的目标实现 | 判分测试 |
|---|---|---|---|---|
| L1 | `l1_poco_thread` | POCO Foundation | `Thread_POSIX.cpp` | `ThreadTest` |
| L1 | `l1_poco_shared_library` | POCO Foundation | `SharedLibrary_UNIX.cpp` | `SharedLibraryTest` |
| L1 | `l1_poco_file` | POCO Foundation | `File_UNIX.cpp` | `FileTest` |
| L1 | `l1_poco_path` | POCO Foundation | `Path_UNIX.cpp` | `PathTest` |
| L1 | `l1_poco_rwlock_semaphore` | POCO Foundation | `RWLock_POSIX.cpp`、`Semaphore_POSIX.cpp` | `RWLockTest`、`SemaphoreTest` |
| L2 | `l2_libgit2_file` | libgit2 | `src/util/unix/{map,realpath}.c` | clar `util::*` 子集 |
| L2 | `l2_libgit2_process` | libgit2 | `src/util/unix/{process.c,pthread.h,posix.h}` | `util::process::start`、`threads::*` |
| L2 | `l2_libarchive_read_disk` | libarchive | `archive_read_disk_posix.c` | `test_read_disk*` |
| L2 | `l2_libarchive_write_disk` | libarchive | `archive_write_disk_posix.c` | `test_write_disk*` |
| L2 | `l2_curl_tls` | curl | `lib/vtls/openssl.c` | 本地 `openssl s_server` TLS 探测 |
| L2 | `l2_opencv_highgui` | OpenCV | `window_gtk.cpp` | `opencv_test_highgui`（Xvfb） |
| L2 | `l2_nginx_files` | nginx | `src/os/unix/ngx_files.c` | nginx smoke + `autoindex.t` + `range.t` |
| L2 | `l2_libuv_fs` | libuv | `src/unix/fs.c` | `fs_*` 精确用例 |
| L2 | `l2_libuv_process` | libuv | `src/unix/process.c` | `spawn_*`、`process_title` |
| L2 | `l2_libuv_thread` | libuv | `src/unix/thread.c` | `thread_*`、`barrier_*`、`threadpool_*` |
| L3 | `l3_nginx_full` | nginx | 整个 `src/os/unix/` | 构建 + smoke + `autoindex.t` + `range.t` |
| L3 | `l3_libgit2_full` | libgit2 | 整个 `src/util/unix/` | clar 离线子集 |
| L3 | `l3_poco_foundation_full` | POCO Foundation | 17 个 `*_UNIX/_POSIX` 文件 | 7 个上游套件 |
| L3 | `l3_curl_build` | curl | 顶层 `CMakeLists.txt` + `CMake/` | 自建 CMake + TLS 探测 |
| L3 | `negative_win32_eventlog` | POCO Foundation | —（负向对照） | `PORTING_NOTES.md` + 预期 API 门失败 |

级别含义：

- **L1 校准**：单文件、接口一一对应，只用于确认工具链和判分链路，不作为主结论。
- **L2 真实子系统**：一个平台层文件被抽掉，但上层调用方、构建、测试都在。
- **L3 整仓库/构建**：删一个目录或整套构建系统，考跨文件耦合与构建迁移。
- **负向对照**：`Poco::EventLogChannel` 在麒麟上没有行为等价物。正确结果是
  写出不可移植性报告，而不是伪造一个静默丢弃日志的 stub。该题的 API 门
  `expect_fail: true`，只有确实检测到 Win32 调用才算“预期行为成立”。

## 4. 判分设计

1. **构建门**：使用上游自己的构建系统（CMake / nginx `auto/configure`）。
   `task.yaml` 的 `build.command` 就是评测命令，不做额外包装。
2. **行为门**：运行上游测试二进制，且只选与本次迁移相关、可离线运行的用例。
   - POCO：`Foundation-testrunner -ignore cppignore.lnx <Suite>`
   - libgit2：`libgit2_tests -s<suite>`
   - libarchive：`libarchive_test -r <testdir> <name...>`
   - libuv：`uv_run_tests_a <exact-name>`（注意该 runner 不支持前缀匹配，
     所以命令逐个列出用例名）
   - OpenCV：`xvfb-run opencv_test_highgui --gtest_filter=Highgui_GUI.*`
   - nginx/curl：`shared/harness/nginx_smoke.sh`、`tls_probe.sh`
3. **API 清除门**：只扫描 agent 需要重建的文件（`source_dirs` 精确到文件/目录），
   不扫描整棵上游树。原因：真实上游代码里大量跨平台头文件本来就有
   `_MSC_VER`/`__declspec` 分支，整树扫描会误报。
   - `symbol_regex` 可对构建产物（`.a`/可执行文件）做 `nm` 检查；
   - `source_regex` 对重建文件做源级检查；
   - `exclude_globs` 用于排除仍然可见、但属于参考物的 Windows 文件。
4. **gold 隔离**：目标实现只存在于 `gold/`，`work/` 中不可见。静态验证器
   `tools/verify_task.py` 会检查 gold 文件没有泄漏到可见源码树。

## 5. 为什么选这些仓库

| 仓库 | 为什么适合 |
|---|---|
| POCO | 平台层边界清晰，上游自带 Foundation 测试；适合 L1 校准 |
| libgit2 | `src/util/unix` 是真实 VCS 库的系统层，pthread/process/mmap 全覆盖 |
| libarchive | 磁盘遍历/恢复是两个大文件，测试完全本地、无网络 |
| curl | TLS 后端是真实迁移难点（Schannel→OpenSSL），可用本地 TLS 探测判分 |
| OpenCV | GUI 后端迁移需要 GTK/Xvfb，考“非纯算法”的平台适配 |
| nginx | 单文件与整目录两种难度，且有 `nginx-tests` 上游套件 |
| libuv | 异步 I/O/进程/线程三块平台层，测试用例细粒度 |

所有仓库都固定到具体 commit/tag，license 记在 `provenance.json`。

## 6. 评估过但未入选的题目

| 候选 | 未入选原因 |
|---|---|
| LLVM `Support/Windows` → `Support/Unix` | 单体构建过重，单题构建时间不可控；上游测试依赖大量目标文件 |
| SQLite `os_win.c` → `os_unix.c` | 目标实现与 Windows 版并非一一对应，TCL 测试夹具重；易变成“重写整个 VFS” |
| FFmpeg `dshow` → `v4l2` | 需要真实摄像头/设备节点，CI 里不可重复 |
| curl `lib/system_win32.c` → `lib/system.c` | 没有严格的一对一 POSIX 文件，删除后构建失败点分散，判分不稳 |

## 7. 环境

见 [`../env/version_matrix.yaml`](../env/version_matrix.yaml) 和
[`../env/Dockerfile.kylin`](../env/Dockerfile.kylin)。要点：

- 麒麟 V10 SP3 基础镜像需要由使用方提供（`ARG BASE_IMAGE`），仓库不假设公网
  一定有可拉取的麒麟镜像；
- 需要 `gcc/g++ 13`、`cmake >= 3.28`、`ninja`、`perl`（nginx-tests）、
  `libssl-dev`、`zlib1g-dev`、`libgtk-3-dev`、`xvfb`、`curl`、`openssl`；
- libuv 测试不允许以 root 运行（上游限制），镜像里创建普通用户 `bench`。

## 8. 本地能验证到什么程度

当前开发机是 WSL，没有麒麟镜像、没有 `cmake`/`mingw`/`wine`，因此：

- 已做：40 个包的静态校验、`prepare.sh` 实际物化（POCO/cann-bench/MKBench
  试点）、gold 泄漏检查、API 门正反例、负向对照门、结果解析器单测。
- 未做：任何实际编译和上游测试运行。**没有跑过的构建不能写成通过。**

在目标环境中的推荐顺序：

```bash
# 1. 物化并静态检查
bash windows_to_kylin/tasks/l1_poco_thread/prepare.sh
python3 tools/verify_task.py --parent windows_to_kylin/tasks

# 2. 用统一 runner 跑一题（构建 + 隐藏测试 + API 门）
python3 shared/harness/runner.py \
  --task-root windows_to_kylin/tasks/l1_poco_thread \
  --build-dir windows_to_kylin/tasks/l1_poco_thread/build_hidden

# 3. 先跑 L1 校准，确认判分链路，再跑 L2/L3
```

## 9. 已知风险

- **`layout: repo` 的可视面很大**：agent 能看到同一仓库的其他平台实现（如
  libgit2 的 `src/util/win32`、POCO 的其他 `_WIN32` 文件）。这是故意的——它们
  是迁移参考；但需要确保被删的目标文件不会从测试数据、补丁或生成物里“复活”。
  静态验证器只做文件名/大小启发式检查，最终仍以 API 门和构建产物为准。
- **测试选择**：只选离线、确定性的上游用例；libuv/OpenCV 的个别用例对内核或
  显示环境敏感，已在任务里固定用例名/过滤器，后续应按目标镜像实测结果微调。
- **负向对照的判分是“预期失败”**：不要把 `API_REMOVAL=PASS` 误读成“实现成功”，
  该题的 PASS 表示“确实检测到了不可移植的 Win32 调用”。