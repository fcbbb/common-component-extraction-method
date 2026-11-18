# RUNBOOK：迁移评测的 P0 / P1 / P2 执行清单

**版本**：2026-11-16  
**范围**：`ipp_vsipl_tasks/`（20 题）、`windows_to_kylin/`（20 题）与
`cuda_to_musa/`（20 题），共 60 个任务包。原 `cuda_to_ascend/` 已归档到
`archive/cuda_to_ascend/`，不计入统计。

---

## 0. 先读这一页

### 0.1 现在处于什么状态

| 项目 | 状态 |
|---|---|
| 60 个任务包的静态结构检查 | **通过**（`verify_task.py`，60/60） |
| 60 个任务包的 pin 检查 | **通过**（`check_pins.py --offline`，ok=60，judge_only=18） |
| IPP 侧 gold 正控（宿主机 GCC 13.3 + jvsip） | **20/20 通过**（`reports/gold_sanity_ipp20/`；2026-11-16 补齐任务 16） |
| 麒麟侧 gold 正控 | **19/19 通过**（Kylin 镜像内实测：L1 5/5、L2 10/10、L3 4/4）；P1 负控 2 题实测 `build=fail` |
| MUSA 侧正控 | **20/20 已验证**（2 份上游 gold + 18 份项目自写）；原 `b_l2_rms_norm`、`b_l3_group_norm` 因判卷器 `torch.allclose` OOM 已归档，2026-11-16 由 `b_l2_cosine_similarity_loss`、`b_l3_conv2d_batch_norm_scaling` 补位并实测通过 |
| 任意一次真实编译 / GPU 执行 | Kylin 19 题真实编译 + 隐藏测试已跑完；MUSA 20 题已在租用 MTT S4000 上跑通（18 题合并重跑 + 2 题替换后重跑） |
| 题目级负向题 `negative_win32_eventlog` | **通过**（Kylin 容器内双向：正确说明判 pass；假移植被 `expect_fail` API 门判 fail） |
| Agent 小样本试验（P2） | **麒麟两题 6/6 判分通过**（其中 4 次 `Submitted`、2 次 `LimitsExceeded` 截断；DSH 0.2.2-rc.1 + `deepseek-v4.1-flash-1017`）；MUSA 半场尚未开始，但 S4000 硬件已可用 |

> **报告纪律**：没有在目标环境实际跑过的 gate，一律写“未验证”，不能写成“通过”。
> `gold_sanity.py` 的 `skip` 不是通过；judge-only 题的 agent 通过率也不能当作“判分链路已验证”。

### 0.2 三个阶段

| 阶段 | 目的 | 通过标准 |
|---|---|---|
| **P0 正控** | 标准答案提交后，编译 + 隐藏测试 + 反作弊必须全过 | 每个可运行题 `status=pass` |
| **P1 负控/记录** | 空实现必须编译失败；每次运行留下可追溯记录 | 负控按预期失败，记录完整 |
| **P2 Agent 小样本** | 确认题目对 agent 可做、无歧义 | 4 题 × 3 次，先查歧义再扩量 |

**顺序不能颠倒。** P0 失败时先修题目或环境，不要改 agent 或模型参数。

---

## 1. Preflight：不需要编译器和 GPU

在仓库根目录 `migration_scenario_validation/` 执行：

```bash
# 1.1 结构检查：60/60
python3 tools/verify_task.py \
  --parent ipp_vsipl_tasks \
  --parent windows_to_kylin/tasks \
  --parent cuda_to_musa/tasks
# 期望：VERIFY=PASS tasks=60

# 1.2 pin 检查：联网（IPP 为 vendored，只做本地一致性检查）
python3 tools/check_pins.py
# 期望：SUMMARY ok=60 warn=0 fail=0 unknown=0 skip=0 ... judge_only=18
#       RESULT=PASS

# 1.3 pin 检查：离线（只有缓存时）
python3 tools/check_pins.py --offline
# 期望：已缓存的任务 ok；未缓存的任务 unknown，不应有 fail

# 1.4 确认没有 gold 泄漏到 agent 可见目录
find windows_to_kylin/tasks -path '*/work/*' \
  \( -name 'Thread_POSIX.cpp' -o -name 'process_posix.c' -o -name 'fs_posix.c' \) -print
# 期望：无输出
```

检查点：

- [ ] `verify_task.py` 60/60
- [ ] `check_pins.py` `RESULT=PASS`，`fail=0`
- [ ] `gold_sanity.py --dry-run` 能列出任务
- [ ] `work/` 中没有 gold 文件

`check_pins.py` 的 `judge_only=18` 是预期值，来自 MUSA 侧 18 道没有声明上游 gold 文件的题（含 `layer_norm`；它另有项目自写正控），不是错误。

---

## 2. 环境准备

### 2.1 麒麟（场景 A）

镜像定义在 [env/Dockerfile.kylin](env/Dockerfile.kylin)。已验证的基础镜像：

- `macrosan/kylin:v10-sp3-2403`
- digest `sha256:6ea227917f9df303813a2582f9f013e7287776cf7aa011adaa3ede6b2a70c3a6`
- `/etc/.productinfo` = `V10 SP3 2403/(Halberd)-x86_64-Build20/20240426`

该镜像自带 gcc 7.3.0 / cmake 3.16.5 / python 3.7.9 / glibc 2.28，**不满足**
GCC 13.3 要求。`Dockerfile.kylin` 会从 AlmaLinux 8 拉取
`gcc-toolset-13`（13.3.1）并补齐 Kylin 缺失的 `libmpfr.so.4`、
`libjansson.so.4`。

```bash
cd migration_scenario_validation

docker build -f env/Dockerfile.kylin -t migration/kylin:sp3 .
```

如果 Docker Desktop 已共享当前 WSL/Windows 路径，可以直接 bind mount：

```bash
docker run --rm -it \
  -v "$PWD":/work \
  -v /srv/migration-bench-cache:/cache/migration-bench \
  -e MIGRATION_BENCH_CACHE=/cache/migration-bench \
  -w /work migration/kylin:sp3
```

本机实测 Docker Desktop **没有**把 WSL 的 `/home` 路径共享进容器，
`-v "$PWD":/work` 会挂到空目录。可靠做法是用 named volume：

```bash
docker volume create kylin-work
docker volume create kylin-bench-cache

# 把当前目录装进 volume（容器默认用户是 bench，先以 root 解包）
tar -C . -cf - . | docker run --rm -i -v kylin-work:/work \
  migration/kylin:sp3 bash -lc 'mkdir -p /work && tar -C /work -xf -'
docker run --rm --user root -v kylin-work:/work \
  migration/kylin:sp3 chown -R bench:bench /work
docker run --rm --user root -v kylin-bench-cache:/cache/migration-bench \
  migration/kylin:sp3 chown -R bench:bench /cache/migration-bench

docker run --rm -it \
  -v kylin-work:/work \
  -v kylin-bench-cache:/cache/migration-bench \
  -e MIGRATION_BENCH_CACHE=/cache/migration-bench \
  -w /work migration/kylin:sp3

# 跑完后把报告取回宿主机
docker run --rm -v kylin-work:/work migration/kylin:sp3 \
  tar -C /work -cf - reports | tar -C . -xf -
```

容器内自检：

```bash
gcc --version          # 实测 13.3.1（gcc-toolset-13）
cmake --version        # 实测 3.16.5（Kylin 仓库版本）
python3 --version      # 实测 3.7.9
pkg-config --exists gtk+-3.0 && echo gtk-ok
which Xvfb xauth git curl
```

注意：

- `prepare.sh` 需要访问 GitHub；如果容器不通外网，先在宿主机把仓库 clone 到 `$MIGRATION_BENCH_CACHE/repos`（脚本会复用）。
- Kylin 仓库没有 `gcc-13`/`gcc-toolset` 包，因此 GCC 13.3.1 来自 AlmaLinux 8 的
  `gcc-toolset-13`，安装在 `/opt/rh/gcc-toolset-13`，并在镜像里设置 `PATH` /
  `LD_LIBRARY_PATH`。
- Kylin 仓库的 `cmake` 是 3.16.5。当前任务包未使用 3.17+ 特性；若后续题目需要
  CMake 3.28，再在镜像里用官方二进制或 pip wheel 覆盖。
- OpenCV 题需要 GTK/Xvfb；nginx 题需要 `nginx` 和 `pcre2`；curl 题需要 OpenSSL 头文件。

### 2.2 摩尔线程 MUSA（场景 B）

一个镜像、一套 Python 环境：

```bash
docker build -f env/Dockerfile.musa \
  --build-arg BASE_IMAGE=<musa-sdk-5.2.0-image> \
  --build-arg TORCH_VERSION=2.11.0 \
  --build-arg TORCH_MUSA_WHEEL=<torch_musa-2.11.0.post1-...whl or URL> \
  -t migration/musa:s4000 .
```

`torch` 与 `torch_musa` 必须版本配套。若厂商基础镜像已经带 `torch_musa`，
Dockerfile 会保留它并忽略 wheel 参数，此时以镜像内实际版本为准并记录。

运行参数：

```bash
docker run --rm -it \
  --device /dev/musa0 \
  -v "$PWD":/work \
  -v /srv/migration-bench-cache:/cache/migration-bench \
  -e MIGRATION_BENCH_CACHE=/cache/migration-bench \
  -e MIGRATION_BENCH_IMAGE="$(docker image inspect migration/musa:s4000 --format '{{.Id}}')" \
  -w /work migration/musa:s4000
```

容器内自检：

```bash
musaInfo                    # 必须能看到 MTT S4000 与 MUSA SDK 5.2.0
which mcc                   # MUSA 编译器
python3 -c "import torch, torch_musa; print(torch.__version__, torch_musa.__version__); print(torch.musa.is_available())"
# 期望：torch 2.11.0 / torch_musa 2.11.0.post1 / True
```

检查点：

- [ ] `musaInfo` 正常，型号是 MTT S4000
- [ ] `mcc` 可执行，`MUSA_HOME` 已设置
- [ ] `torch.musa.is_available()` 为 True
- [ ] `torch` / `torch_musa` 版本与任务声明一致
- [ ] 宿主机驱动版本已记录（见 §6）

---

## 3. P0-A：麒麟 gold 正控

### 3.1 为什么先跑 L1

L1 是 5 道 POCO 平台题，编译时间短，能最早暴露工具链、依赖、路径问题。  
不要让 libgit2 / OpenCV / nginx 的长构建掩盖一个坏掉的 GCC 或 CMake。

### 3.2 逐级执行

在 Kylin 容器内、仓库根目录：

```bash
# L1：5 道，先跑
python3 tools/gold_sanity.py \
  --parent windows_to_kylin/tasks --level L1 \
  --label kylin_L1 \
  --report-dir reports/gold_sanity/kylin_L1

# L1 全过再跑 L2：10 道
python3 tools/gold_sanity.py \
  --parent windows_to_kylin/tasks --level L2 \
  --label kylin_L2 \
  --report-dir reports/gold_sanity/kylin_L2

# L2 全过再跑 L3 正向题：4 道
python3 tools/gold_sanity.py \
  --parent windows_to_kylin/tasks --level L3 \
  --exclude negative_win32_eventlog \
  --label kylin_L3 \
  --report-dir reports/gold_sanity/kylin_L3
```

`gold_sanity.py` 会自动：

1. 若 `work/` 未物化，先执行该题的 `prepare.sh`；
2. 把 `gold/` 覆盖到 `work/`；
3. 调用 `shared/harness/runner.py` 跑 build → hidden tests → API gate；
4. 把每题结果和 `summary.json` 写到 `--report-dir`。

**注意**：跑完后 `work/` 里留着标准答案。下一次给 agent 用之前，必须重新执行 `prepare.sh`。

**已验证（2026-11-15，`migration/kylin:sp3`，GCC 13.3.1）**：

| 题 | 结果 | 耗时 |
|---|---|---|
| `l1_poco_thread` | pass（build ok / 15 tests / api ok） | 898.9s |
| `l1_poco_file` | pass | 736.7s |
| `l1_poco_path` | pass | 635.8s |
| `l1_poco_rwlock_semaphore` | pass | 550.2s |
| `l1_poco_shared_library` | pass（修复后重跑） | 558.2s |

L1 实测修掉两个题目包缺陷，均已写回 `task.yaml`：

1. 静态库产物名是 `libPocoFoundation.a`，不是 POCO 的
   `lib/libFoundation.a`；6 道 POCO 题的 `artifact` 与 `harness/config.json` 已统一。
2. `SharedLibraryTest` 需要 `LD_LIBRARY_PATH={build}/bin` 才能
   `dlopen("TestLibrary.so")`（上游 CTest 用
   `set_tests_properties(... ENVIRONMENT LD_LIBRARY_PATH=...)` 达到同样效果）；
   `l3_poco_foundation_full` 还要 `PATH={build}/bin` 给 `ProcessTest` 找 `TestApp`。

**L2 实测（10/10，2026-11-15，`migration/kylin:sp3`，GCC 13.3.1）**：

| 题 | 结果 | 耗时 |
|---|---|---|
| `l2_curl_tls` | pass | 47.8s |
| `l2_libarchive_read_disk` | pass | 73.3s |
| `l2_libarchive_write_disk` | pass | 70.1s |
| `l2_libgit2_file` | pass | 54.4s |
| `l2_libgit2_process` | pass | 53.3s |
| `l2_libuv_fs` | pass（修复后重跑） | 27.9s |
| `l2_libuv_process` | pass（修复后重跑） | 26.7s |
| `l2_libuv_thread` | pass（修复后重跑） | 25.5s |
| `l2_nginx_files` | pass | 15.8s |
| `l2_opencv_highgui` | pass（修复后，`-j4`） | 1229.6s |

**L3 实测（4/4，2026-11-15，`migration/kylin:sp3`，GCC 13.3.1）**：

| 题 | 结果 | 耗时 |
|---|---|---|
| `l3_curl_build` | pass（API 门修复后重跑） | 57.0s |
| `l3_libgit2_full` | pass | 57.1s |
| `l3_nginx_full` | pass | 17.2s |
| `l3_poco_foundation_full` | pass（API 门修复后重跑） | 943.8s |

L2/L3 实测修掉的题目包缺陷（均已写回包内文件）：

1. `l2_libarchive_*`：静态库在 `{build}/libarchive/libarchive.a`，不是
   `{build}/lib/libarchive.a`（API 门会报 `missing artifact`）。
2. `l2_libuv_*`：
   - 静态库产物是 `{build}/libuv.a`（CMake `OUTPUT_NAME "uv"`），不是 `libuv_a.a`；
   - 隐藏测试必须在**源码目录**运行：`fs_copyfile` 用相对路径
     `test/fixtures/load_error.node`，上游 CTest 的
     `WORKING_DIRECTORY` 就是源码根目录，在 `{build}` 里跑会 `ENOENT`；
   - `LIBUV_BUILD_SHARED=OFF` 会把 `LIBUV_BUILD_TESTS` 偷偷关掉（CMake 的
     `cmake_dependent_option`），必须 `ON` 才能生成 `uv_run_tests_a`。
3. `l2_libgit2_*`：util 测试是独立二进制 `util_tests`，套件名不带 `util::`
   前缀；默认构建的是共享库，需 `-DBUILD_SHARED_LIBS=OFF` 才有 `libgit2.a`。
4. `l2_nginx_files` / `l3_nginx_full`：这份 nginx-tests 快照里没有
   `http_static.t`，改用 `autoindex.t` + `range.t`。
5. `l2_opencv_highgui`：`BUILD_LIST` 必须包含 `ts` 才会生成测试可执行文件；
   `BUILD_SHARED_LIBS=OFF` 才产出 `.a`；构建并发改为 `-j4`（见下方环境问题）。
6. `l3_curl_build`：API 门的 `source_regex` 去掉 `windows\.h`——上游 CMake 的
   `if(WIN32) check_include_file_concat("windows.h" ...)` 是合法跨平台探测，
   gold 答案本身就包含它，原规则会误杀。
7. `l3_poco_foundation_full`：`source_regex` 的 `CreateFile` 收紧为
   `\bCreateFile\b`，否则会命中 POCO 自己的 `CreateFileException` 类名。

**环境问题（WSL 主机内存超卖）**：宿主机 15.36GB，`.wslconfig` 给 WSL 12GB，
Docker Desktop VM 12.5GB，两者上限之和接近物理内存 1.6 倍。OpenCV 用 `-j16`
构建时把 Windows 拖到换页、WSL 失去响应（日志见 `page allocation failure:
order:7`，无 `oom-kill`），只能手工 `wsl --shutdown`。已把 OpenCV 构建改为
`-j4` 并加内存监控；如仍不稳定，把 `.wslconfig` 的 `memory` 降到 8GB、
Docker Desktop 内存降到 8GB。

**报告写入方式**：`tools/gold_sanity.py` 现在每跑完一题就立刻写
`{report-dir}/{task}.json`，不再等全部结束；`summary.json` 在最后一次覆盖。

### 3.3 验收标准

单题 JSON（`reports/gold_sanity/kylin_L1/<task>.json`）中：

```json
{
  "status": "pass",
  "runner": {
    "status": "pass",
    "build": "ok",
    "tests": "pass",
    "api_removal": "pass"
  }
}
```

汇总命令：

```bash
python3 - <<'PY'
import json, pathlib
for summary in pathlib.Path("reports/gold_sanity").rglob("summary.json"):
    data = json.loads(summary.read_text())
    bad = [r["task"] for r in data["results"] if r["status"] != "pass"]
    print(summary, data["counts"], "BAD:", bad)
PY
```

检查点：

- [ ] L1 `pass=5 fail=0 error=0 skip=0`
- [ ] L2 `pass=10 fail=0 error=0 skip=0`
- [ ] L3 `pass=4 fail=0 error=0 skip=0`
- [ ] 每题 `build=ok`、`tests=pass`、`api_removal=pass`

### 3.4 失败时怎么处理

| 现象 | 先查什么 | 不要做什么 |
|---|---|---|
| `prepare.sh` 失败 | 网络、`MIGRATION_BENCH_CACHE` 权限、上游 pin 是否还在 | 不要改任务里的 commit 来“让它过” |
| 编译失败 | 缺哪个包（`apt-file`/`dnf provides`）、GCC/CMake 版本 | 不要给任务加 `-w` 或跳过编译 |
| 测试失败 | 测试命令路径、`{build}` 占位符、测试依赖 | 不要改 hidden test 的断言 |
| API gate 失败 | gold 里是否本来就含 Win32 路径、`exclude_globs` 是否漏了目录 | 不要全局关闭 API gate |
| 超时 | 是否首次全量构建；调大 `--timeout` | 不要为了省时间删测试 |

正控失败一律视为**题目包或环境有问题**，修这两者，不改 agent。

---

## 4. P0-B：MUSA gold 正控

### 4.1 跑已验证正控（18 题）

在 MUSA 主机（Python 3.10.12、torch 2.11.0.post1、torch_musa
2.11.0.post1+b431668、MUSA SDK 5.2.0、driver 5.2.0-server）上执行。

最小冒烟（3 题，历史上用来打通链路）：

```bash
python3 tools/gold_sanity.py \
  --parent cuda_to_musa/tasks \
  --only b_l1_leaky_relu \
  --only b_l1_mse_loss \
  --only b_l2_layer_norm \
  --label musa_gold \
  --report-dir reports/gold_sanity/musa
```

3 道题的来源并不相同：

- `b_l1_leaky_relu`、`b_l1_mse_loss`：上游 `prompts/musa_new_model_*.py`，
  `prepare.sh` 复制到 `gold/`，`gold_sanity.py` 还原成
  `work/submission/<op>_submission.py`；
- `b_l2_layer_norm`：上游样例是二维契约，与 evaluator 的四维 reference
  不符（实测 `compiled=True, correct=False`），因此使用项目自写的
  `gold_authored/layer_norm_submission.py`；`gold_sanity.py` 在无上游
  gold 时自动还原，并在报告里标注 `(project-authored)`。

三条路径最终都会调用 `eval_single_runner.py --language musa`，再跑
`check_result.py --require-compiled --require-correct --forbid-cheating` 与
`check_musa_submission.py`。

**2026-11-16 实测**（租用 MTT S4000，报告在 `reports/gold_sanity/`）：

| 题目 | 来源 | 结果 |
|---|---|---|
| `b_l1_leaky_relu` | 上游 gold | PASS，166.8s（首跑） / 98.2s（最终题包） |
| `b_l1_mse_loss` | 上游 gold | PASS，185.8s（首跑） / 121.2s（最终题包） |
| `b_l2_layer_norm` | 项目自写 | PASS，90.9s（首跑） / 25.0s（最终题包） |

最终证据是 `reports/gold_sanity/musa_gold_final/`：在改完 `python3`
之后的最终题包上一条命令跑完三题，`SUMMARY pass=3 fail=0 skip=0 error=0`、
`GOLD_SANITY_RC=0`。该次 `prepare` 为 `skipped`（`work/` 已由最终题包
物化），gold 由 `gold_sanity.py` 还原；耗时低于首跑是因为
`torch_extensions` 编译缓存已热。

验收：`pass=3 fail=0 error=0`，且每题 JSON 里编译、数值、反作弊、API 门、
kernel 结构门都通过。

**全量 18 题（2026-11-16，同一台 S4000）**：在最终题包上按批执行
`gold_sanity.py`，报告目录 `reports/gold_sanity/musa_batch1`…`musa_batch5`
（`musa_gold_final` 为最初 3 题）。逐题结果、每批修掉的题目包缺陷见
[cuda_to_musa/positive_controls.md](cuda_to_musa/positive_controls.md) §3 与 §5。

一条命令重跑全部 18 题：

```bash
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks \
  --only b_l1_leaky_relu --only b_l1_mse_loss --only b_l2_layer_norm \
  --only b_l1_relu --only b_l1_sigmoid --only b_l1_swish --only b_l1_softmax \
  --only b_l2_cumsum --only b_l2_sum_reduce --only b_l2_argmax \
  --only b_l2_gather --only b_l2_cross_entropy_loss \
  --only b_l3_standard_matmul --only b_l3_conv2d --only b_l3_gqa \
  --only b_l3_sdpa --only b_l3_matmul_gelu_softmax --only b_l3_kv_cached_attention \
  --label musa_all18 --report-dir reports/gold_sanity/musa_all18
```

验收：`pass=18 fail=0`。**最终合并运行**（2026-11-16 21:09–21:30）已执行
这条命令：`musa_all18` 返回 `SUMMARY pass=18 fail=0 skip=0 error=0`、
`GOLD_SANITY_RC=0`（20.7 分钟），逐题 `tests=pass`、`api_removal=pass`、
`MUSA_SUBMISSION=PASS`。单题历史以 `musa_batch1`…`musa_batch5` 的记录为准：
batch1 3/3、batch2 2/7、batch3 0/7、batch4 9/10、batch5 1/1（conv2d 重跑）。
batch2/batch3 的失败全部是正控自身缺陷（文件名、`int64_t` 指针类型、
NT 分块行索引、muDNN TF32），已修复并重跑；不是环境问题。

**两题已换掉（2026-11-16）**：`b_l2_rms_norm`、`b_l3_group_norm` 的
2.1e9 元素 fp32 张量（8.59 GB）使判卷器的 `torch.allclose` 在 47.90 GB
卡上 OOM（42 GiB allocated 时仍要 8 GiB；原地别名提交也要 44 GiB）。
两题连同探针、日志和归档说明移到
[archive/cuda_to_musa_blocked_oom/](archive/cuda_to_musa_blocked_oom/README.md)，
**不计入通过数**。补位的 `b_l2_cosine_similarity_loss`、
`b_l3_conv2d_batch_norm_scaling` 已在该 S4000 上实测通过：
`musa_batch6` `SUMMARY pass=2 fail=0 skip=0 error=0`，证据在
[reports/gold_sanity/musa_batch6/](reports/gold_sanity/musa_batch6/)。

### 4.2 确认 gold 没有泄漏

```bash
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
find cuda_to_musa/tasks/b_l1_leaky_relu/work -name 'musa_new_model_*'
# 期望：无输出
find cuda_to_musa/tasks/b_l1_leaky_relu/gold -name 'musa_new_model_*'
# 期望：只有 musa_new_model_leaky_relu.py
```

20 个题包的 `prepare.sh` 都通过 `remove_globs: prompts/musa_new_model_*.py`
删除**全部 6 份**上游 MUSA 样例（含本题之外的 5 份）。MUSA 与 CUDA 源级兼容，
留下其他算子的样例等于把 `load_inline(musa_sources=...)` 的写法直接送给
agent。详见 [cuda_to_musa/design.md](cuda_to_musa/design.md) §5。

### 4.3 项目自写正控：存放与命名约定

MUSA 侧没有“自带 fixture 流水线”，evaluator 只有
`eval_single_runner.py`，所以上游没有可用样例的题都写了项目自写正控
（当前 20 题中的 18 题）。已经踩过的两个坑：

1. **文件名必须等于 `op_name`**。`gold_sanity.py` 把 `gold_authored/*.py`
   按原文件名还原到 `work/submission/`，而 evaluator 找的是
   `<op_name>_submission.py`；短名会在 0.1–0.2s 内以 `FileNotFoundError`
   失败。改名后必须删掉主机上的旧文件名残留，因为 `gold_sanity.py` 会复制
   `gold_authored/` 里**所有** `*.py`。
2. **MUSA 的 `data_ptr<int64_t>()` 是 `long*`**，kernel 形参写
   `const long long*` 会编译失败；用 `const int64_t*`。

**上游样例**与**项目自写实现**必须分开存放，否则报告会把自写实现误算成
上游 gold：

| 来源 | 存放位置 | 是否写进 `source.gold_files` | 报告标注 |
|---|---|---|---|
| 上游样例（可直接提交） | `gold/prompts/musa_new_model_<op>.py` | 是 | upstream gold |
| 项目自写 | `gold_authored/<op>_submission.py` | **否** | project-authored |

`gold_sanity.py` 在 `source.gold_files` 为空时会自动查找 `gold_authored/*.py`；
两处都没有才会按 judge-only 跳过。写完后重新跑：

```bash
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks --only <task> --label musa_gold
```

每道题的验收条件（全部满足才算“正控已验证”）：

- [ ] 参考提交在 MUSA SDK 5.2.0 + MTT S4000 + 固定 driver 上编译通过
- [ ] 5 次数值试验全部通过（atol=rtol=1e-4）
- [ ] 反作弊检测通过
- [ ] CUDA API 门通过
- [ ] MUSA kernel 结构门通过
- [ ] 报告里记录镜像 digest、驱动版本、SDK 版本、日期、提交 hash
- [ ] 在 [cuda_to_musa/positive_controls.md](cuda_to_musa/positive_controls.md)
      的表格里从 `judge-only` 改成“正控已验证”

### 4.4 受阻题怎么标记

`b_l2_rms_norm`、`b_l3_group_norm` 受阻于判卷器在 48 GB 卡上无法完成
`torch.allclose`，与正控和实现无关。2026-11-16 起这两题已从 slate 中移出，
归档在 `archive/cuda_to_musa_blocked_oom/`，由两道同难度、内存可控的题补位；
它们不再出现在任何统计里。若将来恢复，报告里必须写：

```text
BLOCKED (evaluator allclose OOM on 48 GB)
```

不能写 `judge-only, unverified`（会让人以为缺参考实现），也不能写“通过”。
通过率同时给两个数：

- `resolve_rate_all`：包含受阻题，仅作参考；
- `resolve_rate_verified`：只含 18 题正控通过的题，作为主指标。

不允许把受阻题的 agent 通过写成“判分链路已验证”。解除受阻需要 >48 GB
可用显存的卡，或上游 evaluator 改成分块比较（超出本场景范围）。

---

## 5. P1：负控与记录

### 5.0 IPP：未迁移状态必须编译失败

```bash
bash ipp_vsipl_tasks/l1_vec_db_mag/prepare.sh   # 恢复成 Intel IPP 源状态
python3 shared/harness/runner.py \
  --task-root ipp_vsipl_tasks/l1_vec_db_mag --build-dir /tmp/neg_ipp_dbmag
```

验收（2026-11-15 在宿主机 GCC 13.3 实测）：

- [x] runner 退出码 `1`，`build=fail`
- [x] 失败原因是 `work/src/dbmag_ipp.c:11: fatal error: ipp.h: No such file or directory`
      （未迁移、也没有 IPP 头文件），不是环境缺少编译器/CMake
- [x] 隐藏测试与 API 门均为 `skipped`，没有被当成通过

### 5.1 麒麟：空实现必须编译失败

任选一题（建议 L1，构建快）：

```bash
# 1. 恢复成 agent 初始状态：gold 已从 work/ 删除
bash windows_to_kylin/tasks/l1_poco_thread/prepare.sh

# 2. 不提交任何实现，直接判分
python3 shared/harness/runner.py \
  --task-root windows_to_kylin/tasks/l1_poco_thread \
  --build-dir /tmp/neg_l1_poco_thread
```

验收：

- 退出码为 `1`；
- JSON 中 `build=fail`；
- 日志里能看到失败来自缺少 `Thread_POSIX.cpp` / pthread 实现，依赖与 CMake 配置均正常。

同样的负控至少再做一道 L2（例如 `l2_libuv_thread`），确认长构建题也不会“空实现也能过”。

检查点（2026-11-15 在 `migration/kylin:sp3` 内实测）：

- [x] L1 空实现：`build=fail`（`l1_poco_thread`，runner rc=1，
      失败于 `Thread.cpp:28: fatal error: Thread_POSIX.cpp: No such file or directory`）
- [x] L2 空实现：`build=fail`（`l2_libuv_thread`，runner rc=1，
      失败于 `CMake Error at CMakeLists.txt:448: Cannot find source file: src/unix/thread.c`）
- [x] 失败原因与缺失实现一致，不是缺依赖或环境问题

复现命令（容器内、`work/` 已 prepare）：

```bash
python3 shared/harness/runner.py \
  --task-root windows_to_kylin/tasks/l1_poco_thread --build-dir /tmp/neg_poco   # rc=1, build=fail
python3 shared/harness/runner.py \
  --task-root windows_to_kylin/tasks/l2_libuv_thread --build-dir /tmp/neg_libuv # rc=1, build=fail
```

### 5.2 MUSA：空提交必须编译失败

```bash
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
mkdir -p cuda_to_musa/tasks/b_l1_leaky_relu/work/submission
# 不放 submission/leaky_relu_submission.py

python3 shared/harness/runner.py \
  --task-root cuda_to_musa/tasks/b_l1_leaky_relu \
  --build-dir /tmp/neg_b_l1_leaky_relu
```

验收：`status=fail`，`build=fail`，日志表明是缺少提交文件或导入失败，与 MUSA 是否可用无关。

另外两条可以在无 GPU 的机器上预检：

```bash
# kernel 结构门负例：直接复用 reference Model、不写 kernel
python3 shared/harness/check_musa_submission.py /path/to/reference_only.py
# 期望：MUSA_SUBMISSION=FAIL，rc=1

# API 清除门负例：提交里仍调用 torch.cuda
printf 'import torch\nx = torch.zeros(1, device="cuda")\n' > /tmp/leak.py
python3 shared/harness/api_removal.py --source-dir /tmp/leak.py \
  --source-regex 'torch\.cuda|device\s*=\s*['"'"'"]cuda'
# 期望：API_REMOVAL=FAIL，rc=1
```

> `negative_win32_eventlog` 是**题目级负向题**（正确回答是“这个 API 不可移植”），不是判分链路的负控。不要把它和本节混为一谈。
>
> 2026-11-16 已在 `migration/kylin:sp3` 内双向验证：`work/` 加上正确的
> `PORTING_NOTES.md` 时 `status=pass`（build skipped、hidden test pass、
> `expect_fail` API 门 pass）；把 `EventLogChannel.cpp` 换成删掉 Windows API
> 的存根后 `api_removal=fail`（"negative control did not hold"）、runner rc=1。
> 证据：`reports/negative_win32_eventlog/`。

---

## 6. 每次运行必须记录什么

`gold_sanity.py` 已经写入 `summary.json` 的字段：

- `label`、`started_at`、`finished_at`
- `host`、`platform`、`python`
- `MIGRATION_BENCH_IMAGE`（镜像 digest，需你手动导出并传入）
- 每题 `commit`、`prepare`、`runner_rc`、`runner`、`duration_s`、`log_tail`

还需要人工补的记录（建议直接追加到 `reports/run_log.md`）：

| 字段 | 示例 |
|---|---|
| 日期 | 2026-11-16 |
| 场景 / 级别 | Kylin / L1 |
| 主机 | MUSA 主机名或 Kylin 容器 ID |
| 镜像 | `sha256:...` |
| 驱动 | `musaInfo` 顶部版本 |
| MUSA SDK | 5.2.0 |
| torch / torch_musa | 2.11.0 / 2.11.0.post1 |
| 任务 | `l1_poco_thread` |
| 正控/负控 | gold / empty |
| build rc / 耗时 | 0 / 42s |
| tests rc / 耗时 | 0 / 8s |
| API gate | pass |
| 是否 flaky | 否 |
| 备注 | 首次构建，缓存为空 |

记录模板：

```markdown
## 2026-11-16 Kylin L1 gold

- host: kylin-bench-01
- image: sha256:...
- gcc/cmake: 13.3 / 3.28.3
- MIGRATION_BENCH_CACHE: /cache/migration-bench
- result: pass=5 fail=0 error=0 skip=0
- flaky: none
- notes:
```

---

## 7. P2：Agent 小样本试验（P0/P1 之后）

### 7.1 门槛

只有同时满足才进入 P2：

- [x] §3 麒麟正控全过（19/19：L1 5/5、L2 10/10、L3 4/4）
- [x] §4.1 MUSA 正控 20/20 通过（租用 MTT S4000；`musa_gold_final` 3/3，
      `musa_batch1`–`musa_batch5` 覆盖余下 15 题，`musa_batch6` 覆盖
      2026-11-16 补位的 2 题；原 `b_l2_rms_norm`、`b_l3_group_norm`
      因 evaluator OOM 归档，不计入）
- [x] §4.2 gold 隔离检查通过（WSL 静态检查 + S4000 主机实际物化后检查：
      20 个 `work/` 中零个 `musa_new_model_*`）
- [x] §5 负控按预期失败（Kylin `l1_poco_thread` / `l2_libuv_thread`、IPP `l1_vec_db_mag`）

麒麟两题可以跑 P2；MUSA 半场硬件门槛已满足，但尚未开始，本文档目前只记录麒麟侧结果。

### 7.2 样本与次数

先选 4 题：**2 道 L1 + 2 道 L2**，优先挑已经正控验证过的题：

- L1：`l1_poco_thread`（麒麟）、`b_l1_leaky_relu`（MUSA）
- L2：`l2_libuv_thread`（麒麟）、`b_l2_layer_norm`（MUSA）

每题跑 3 次，记录：

- 是否编译成功；
- 隐藏测试通过/失败；
- API gate 通过/失败；
- agent 是否卡在题目描述、提交路径、超时、环境问题上。

### 7.3 先查歧义，再扩量

如果 3 次里出现同一处失败，先判断是：

1. **题目歧义**：描述没说清提交路径、接口、dtype/shape → 修 `task.yaml` 的 `spec`；
2. **超时**：构建或评测时间不够 → 调 `timeout`，并在记录里注明；
3. **提交格式**：agent 不知道要交什么 → 补 `README.md` 和 `spec`；
4. **模型能力**：确实做不出来 → 这是有效信号，不要改题迁就；
5. **预算**：步数/时间上限先于完成触发 → 记录为 `LimitsExceeded`，
   与"做不出来"区分开。空实现负控证明题目本身可做，截断不等于能力不足。

已出现的实际案例：`l1_poco_thread` 在 150 步预算下 3 次里有 2 次
`LimitsExceeded`（`l2` 3 次全部 `Submitted`）。三次的工作区都判分通过，
但 agent 没有走完提交协议。扩量前必须先定口径——提高步数重跑，还是把
"截断但产物完整"单列一类——再统一执行；不能按题临时调预算。

只有 4 题 × 3 次都跑通且无系统性歧义，才扩到全量 40 题。

### 7.4 执行方式（已实现，2026-11-15）

驱动脚本：[tools/agent_trial.py](tools/agent_trial.py)。它复用
`repository/` 里的 DeepSeek Harness（DSH）生产后端：

1. `prepare.sh` 物化 `work/`（gold 留在 `gold/`，不进 agent 工作区）；
2. 把 `work/` 复制到 `reports/agent_trial/<label>/<task>/run<N>/workspace`，
   `chown` 到 10001，以 `--network none` 启动目标镜像容器；
3. `DshHeadlessBackend`（`@deepseek-ai/dsh` 0.2.2-rc.1 + 固定的
   `controlled-bash` 插件）在该容器内跑 agent，唯一工具是 `controlled_bash`，
   完成协议是输出 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`；
4. 销毁 agent 容器后，用同一镜像的新容器运行
   `shared/harness/runner.py` 判分（与 gold 正控完全相同的判分路径）。

Agent 镜像是在 `migration/kylin:sp3` 上加薄薄一层（[env/Dockerfile.kylin-agent](env/Dockerfile.kylin-agent)）：

- `controlled-bash` 固定以 `10001:10001` 执行，基础镜像只有 `bench(1000)`，
  没有该用户时每条命令前面都会多出 `id/whoami` 报错，完成标记永远不是首行；
- `/etc/profile.d/system-info.sh` 因缺 `/sbin/ip` 在每条 `bash -lc` 里往
  stderr 打一行错误，插件把 stdout/stderr 合并后同样会挡住完成标记。

该层只新增 uid 10001 用户并删掉这个装饰性 profile 脚本，编译器仍是
gcc-toolset-13 13.3.1，判分环境与 gold 正控一致。镜像 ID：
`sha256:e27fd0c017da837fbc0e10f396edcef11a6af29eb5f61ebc9eb994d038f4b0e4`。

```bash
# 真实模型（凭据来自环境变量或仓库根 .env）
python3 tools/agent_trial.py \
  --parent windows_to_kylin/tasks \
  --only l1_poco_thread --only l2_libuv_thread \
  --runs 3 --label p2_kylin

# 不花钱的全链路自测：本地 fixture 模型，只验证接线，不产生可用的能力信号
python3 tools/agent_trial.py --parent windows_to_kylin/tasks \
  --only l1_poco_thread --runs 1 --fake-model --label p2_selftest
```

每次尝试写完就落盘 `attempt.json`（agent 状态、工具调用数、token、
`workspace.diff`、判分 JSON、耗时），最后写 `summary.json`。

**当前状态（2026-11-16，label `p2_kylin`）：麒麟两题 6/6 判分通过。**

| 题 | 次数 | agent 状态 | 工具调用 | 输入 token | 耗时 | 判分 |
|---|---|---|---|---|---|---|
| `l1_poco_thread` | run1 | `LimitsExceeded`（150 步截断） | 150 | 1.06M | 66 分钟 | pass：build ok + ThreadTest 15 项 OK + API 门 pass |
| `l1_poco_thread` | run2 | `Submitted` | 162 | 0.87M | 71 分钟 | pass（同上） |
| `l1_poco_thread` | run3 | `LimitsExceeded`（150 步截断） | 162 | 1.09M | 62 分钟 | pass（同上） |
| `l2_libuv_thread` | run1 | `Submitted` | 71 | 0.33M | 14 分钟 | pass：build ok + 线程测试全 ok + API 门 pass |
| `l2_libuv_thread` | run2 | `Submitted` | 56 | 0.29M | 10 分钟 | pass（同上） |
| `l2_libuv_thread` | run3 | `Submitted` | 50 | 0.22M | 10 分钟 | pass（同上） |

（“工具调用”是 `controlled_bash` 次数；步数上限约束的是模型调用数，
一条消息里可以并行多个工具调用，所以 run3 的 162 次工具调用对应 150 步。）

每题改动范围已核验：`l1` 只新增 `Foundation/src/Thread_POSIX.cpp`（`run3`
另有 agent 自建的 `globtest/`、日志等临时文件）；`l2` 只新增
`src/unix/thread.c`。没有任何一次修改测试或构建文件，判分用的是上游测试。

**必须一起读的两条限制**：

1. `l1` 的 3 次里有 2 次是 `LimitsExceeded`——agent 在 150 步上限处被截断，
   没走完“构建成功后提交”的收尾协议；判分看到的工作区恰好已经完整。
   这类结果记为“**产物通过、agent 未正常收尾**”，扩量时必须单独统计，
   不能全部算成干净完成。
2. 按 §7.1，P2 的完整门槛还差 MUSA 侧两题（`b_l1_leaky_relu`、
   `b_l2_layer_norm`）。S4000 硬件已可用，但这两题的 agent 试验尚未开始，
   所以现在只能说“麒麟半场通过”，不能说“P2 通过”或“4 题 × 3 次通过”。

**扩量前要处理的问题**：`l1` 两次截断说明 150 步对这类“从零重写一个
~700 行平台层”的题偏紧，且 agent 会在构建成功后继续打磨、不立即提交。
扩到全量 40 题之前应先定一个明确口径：是提高步数预算并重跑，还是把
“截断但产物完整”单列一类。这个决定会影响所有后续比较，不能边走边改。

---

## 8. `ipp_vsipl_tasks/`（已统一格式）

20 道 IPP→VSIPL 题已迁到统一任务包格式：

- `scenario: ipp_to_vsipl`、`source_kind: vendored-ipp-snapshot`、
  `gold_kind: implementation`；
- `source.license`、`source.vendored: true`；
- 每题都有 `provenance.json` 和 `prepare.sh`（`prepare.sh` 只复制包内
  vendored 快照，不联网）；
- `build` / `public_tests` / `hidden_tests` / API gate 全部使用
  `{root}` / `{work}` / `{build}` / `{golden}` 占位符；
- `harness/run_hidden.py` 支持 `--harness-dir`，CMake 通过
  `BUILD_HIDDEN_TESTS=ON` 只在评测时编译隐藏测试。

### 8.1 检查与正控

```bash
python3 tools/verify_task.py --parent ipp_vsipl_tasks
# 期望：VERIFY=PASS tasks=20
# （合成源 repo 不是 URL，会有 11 条 warning，不是错误）

python3 tools/check_pins.py --parent ipp_vsipl_tasks --offline
# 期望：ok=20 warn=0 fail=0 materialized=20 gold_present=20

VSIPL_ROOT=/home/fcbbbb/work/ipp_screening_20261114/src/jvsip \
  python3 tools/gold_sanity.py --parent ipp_vsipl_tasks \
  --report-dir reports/gold_sanity_ipp20 --label ipp_all20
# 期望：SUMMARY pass=20 fail=0
```

2026-11-15 在宿主机（GCC 13.3.0 + jvsip `libvsip.a`）实测 19 题
`pass=19 fail=0 skip=0 error=0`（`reports/gold_sanity_ipp_host/`）；
2026-11-16 补齐任务 16 后重跑全量 20 题：
`pass=20 fail=0 skip=0 error=0`（`reports/gold_sanity_ipp20/`）。

注意：

- `gold_sanity.py` 会把 `gold/<reference>.c` 换进 `work/src/` 并保留原文件名；
  跑完后必须重新执行该题 `prepare.sh`，否则 `work/` 里会残留标准答案。
- IPP 题目需要 `VSIPL_ROOT` 指向一个可用的 VSIPL 实现（jvsip 已验证）。
  没有 VSIPL 时，`build` 会失败，不能把 `skip` 当作通过。

---

## 9. 本次已修复的 pin 问题

`check_pins.py` 联网检查发现并已修复 3 处上游路径漂移：

| 任务 | 原路径 | 修正后 |
|---|---|---|
| `l2_libgit2_process` | `tests/threads/basic.c` | `tests/libgit2/threads/basic.c` |
| `l2_libgit2_process` | `tests/threads/tlsdata.c` | `tests/libgit2/threads/tlsdata.c` |
| `l2_opencv_highgui` | `modules/highgui/src/window_w32.h` | 删除（该 commit 只有 `.cpp`） |
| `l3_curl_build` | `projects/Windows/VC15/lib/libcurl.sln` | `projects/Windows/VC14.30/lib/libcurl.sln` |

同步修改了 `task.yaml`、`provenance.json` 和 `windows_to_kylin/slate.yaml`，避免重新生成时又写回坏路径。

另外，`l1_poco_thread/work/Foundation/src/Thread_POSIX.cpp` 曾被上一次 gold 运行污染（gold 泄漏进 agent 可见目录），已通过重新执行 `prepare.sh` 清除。以后每次跑完 gold sanity，给 agent 用之前都要重跑 `prepare.sh`。

---

## 10. 命令速查

```bash
# 静态检查
python3 tools/verify_task.py --parent windows_to_kylin/tasks --parent cuda_to_musa/tasks
python3 tools/check_pins.py
python3 tools/check_pins.py --offline --json

# 正控（麒麟，容器内）
python3 tools/gold_sanity.py --parent windows_to_kylin/tasks --level L1 --label kylin_L1
python3 tools/gold_sanity.py --parent windows_to_kylin/tasks --level L2 --label kylin_L2
python3 tools/gold_sanity.py --parent windows_to_kylin/tasks --level L3 \
  --exclude negative_win32_eventlog --label kylin_L3

# 正控（MUSA 主机上，18 题；完整列表见 §4.1）
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks \
  --only b_l1_leaky_relu --only b_l1_mse_loss --only b_l2_layer_norm \
  --only b_l1_relu --only b_l1_sigmoid --only b_l1_swish --only b_l1_softmax \
  --only b_l2_cumsum --only b_l2_sum_reduce --only b_l2_argmax \
  --only b_l2_gather --only b_l2_cross_entropy_loss \
  --only b_l3_standard_matmul --only b_l3_conv2d --only b_l3_gqa \
  --only b_l3_sdpa --only b_l3_matmul_gelu_softmax --only b_l3_kv_cached_attention \
  --label musa_all18

# gold 隔离检查（无需 GPU）
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
find cuda_to_musa/tasks/b_l1_leaky_relu/work -name 'musa_new_model_*'

# kernel 结构门与 API 门（无需 GPU）
python3 shared/harness/check_musa_submission.py \
  cuda_to_musa/tasks/b_l1_leaky_relu/gold/prompts/musa_new_model_leaky_relu.py
python3 shared/harness/api_removal.py \
  --source-dir cuda_to_musa/tasks/b_l1_leaky_relu/gold/prompts/musa_new_model_leaky_relu.py \
  --source-regex 'torch\.cuda|\.cuda\(\)|cuda[A-Z]\w*\s*\(|#include\s*[<"]cuda|#include\s*[<"]cublas|#include\s*[<"]cudnn|#include\s*[<"]cufft|\bnvcc\b|\bcublas[A-Za-z0-9_]*\s*\(|\bcudnn[A-Za-z0-9_]*\s*\(|\bcufft[A-Za-z0-9_]*\s*\(|device\s*=\s*['\''"]cuda|\bCUDA_[A-Z0-9_]+|__CUDACC__'

# 负控（麒麟，空实现）
bash windows_to_kylin/tasks/l1_poco_thread/prepare.sh
python3 shared/harness/runner.py --task-root windows_to_kylin/tasks/l1_poco_thread \
  --build-dir /tmp/neg_l1_poco_thread

# 负控（MUSA，空提交）
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
mkdir -p cuda_to_musa/tasks/b_l1_leaky_relu/work/submission
python3 shared/harness/runner.py --task-root cuda_to_musa/tasks/b_l1_leaky_relu \
  --build-dir /tmp/neg_b_l1_leaky_relu
```

退出码约定：

| 工具 | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `verify_task.py` | 全部通过 | 有失败 | — | — |
| `check_pins.py` | 全部验证 | 有坏 pin | 有无法验证的 pin | — |
| `gold_sanity.py` | 已执行的都通过（允许 skip） | 有 gold 失败 | 有环境/准备错误 | 没找到任务 |
| `baseline_trial.py` | 无失败（允许 skip） | 有尝试失败 | 环境/准备错误 | 没找到任务 |
| `runner.py` | 全部 gate 通过 | 有 gate 失败 | 任务包有问题 | — |
---

## 11. 基线链路（condition A：直接迁移）

完整说明见 [docs/baseline_pipeline.md](docs/baseline_pipeline.md)。三个场景各一题：

```bash
# 自检（fixture 模型，无凭据；seed-gold 只验证判分器）
python3 tools/baseline_trial.py --only l2_rubberband_fft --runs 1 \
  --fake-model --seed-gold --label plumbing_ipp
python3 tools/baseline_trial.py --only l2_libuv_thread --runs 1 \
  --fake-model --seed-gold --label plumbing_kylin
python3 tools/baseline_trial.py --only b_l2_layer_norm --runs 1 \
  --fake-model --seed-gold --musa-transport local --label plumbing_musa

# 负控（不迁移必须 FAIL）
python3 tools/baseline_trial.py --only l2_rubberband_fft --runs 1 \
  --fake-model --label negative_ipp

# 正式基线（真实模型；MUSA 需要 env/remote.yaml）
python3 tools/baseline_trial.py \
  --only l2_rubberband_fft --only l2_libuv_thread --only b_l2_layer_norm \
  --runs 1 --label baseline_three_v1
```

镜像要求：`migration/ipp:cpu`（`docker build -f env/Dockerfile.ipp -t migration/ipp:cpu .`）
与 `migration/kylin:sp3-p2`。MUSA 连接信息放 `env/remote.yaml`（勿提交），
可选 `agent_user` 与 `isolate_network: true`。
