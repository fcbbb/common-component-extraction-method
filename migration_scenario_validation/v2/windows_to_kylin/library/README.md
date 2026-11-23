# 冻结库：按数据集划分

本目录定义 V2 冻结库的**输入语料**和**发布记录**。组件库本身由方法流水线
在任务出现之前抽取、审核和发布；这里只固定“从哪棵树、哪些文件、以什么哈希”
构建，保证同一数据集的任务读到同一个版本。

V2 最初只有 POCO Foundation 一个数据集。2026-11 起扩展为四个数据集，各自
独立冻结：

| 数据集 | 语料定义 | 仓库 | 目标侧 gold（永不进入语料） |
|---|---|---|---|
| POCO Foundation | `freeze.yaml` / `lock.json` | `pocoproject/poco` @ `d6bd48a` | `Foundation/src/*_POSIX.cpp`、`*_UNIX.cpp` |
| libgit2 utility | `libgit2/freeze.yaml` / `libgit2/lock.json` | `libgit2/libgit2` @ `36f7e21` | `src/util/unix/**` |
| nginx OS layer | `nginx/freeze.yaml` / `nginx/lock.json` | `nginx/nginx` @ `1be0fb0` | `src/os/unix/**` |
| curl TLS/build | `curl/freeze.yaml` / `curl/lock.json` | `curl/curl` @ `7161cb1` | `lib/vtls/openssl.c`、`CMakeLists.txt`、`CMake/**` |

每个数据集的任务只读自己的 `library_manifest`；不存在跨数据集的共享组件库。

## 文件

| 文件 | 作用 |
|---|---|
| `freeze.yaml` | POCO 语料规则：仓库、commit、include/exclude、task-blind 约束、发布流程 |
| `lock.json` | POCO 语料锁；逐文件哈希、语料摘要、发布状态 |
| `libgit2/freeze.yaml`、`libgit2/lock.json` | libgit2 数据集的语料规则与锁 |
| `nginx/freeze.yaml`、`nginx/lock.json` | nginx 数据集的语料规则与锁 |
| `curl/freeze.yaml`、`curl/lock.json` | curl 数据集的语料规则与锁 |

## 语料规则

四个数据集遵循同一原则：

- 包含源侧生产代码、内部/公共头文件、调用方和构建入口；
- 包含 Windows 平台实现（它是迁移参考，不是答案）；
- 排除测试、样例、Windows 工程文件、一切任务材料；
- 排除目标平台实现。目标实现和源侧代码在同一个上游 commit 里，必须通过
  `snapshot.evaluator_side` 显式排除，否则抽取器会把答案带进组件库。

各数据集的具体 include/exclude 见各自的 `freeze.yaml`。`freeze_library.py`
会在读取语料前检查 include 模式，拒绝任何把任务材料拉进语料的配置；
`snapshot` 和 `verify` 只要在候选集或已有 lock 里发现 `evaluator_side`
路径就直接失败。

## 当前快照

```text
POCO    poco-foundation@d6bd48a94c5f  635 files / 6,477,368 bytes
        sha256:eff13f0cf703b37bd7307e5213ff5dfdc66f33858d3086f5725122aac92baa38
libgit2 libgit2-util@36f7e21ad757     512 files / 4,436,639 bytes
        sha256:39519e49dce92cc7bebb388eed1e9d63cd3829e520f5bef73fe829ee3c02a746
nginx   nginx-os@1be0fb0c9f9b         414 files / 6,142,781 bytes
        sha256:21095d4370a9fa4da740052ea080c547c95a734731bc31acbb94e865766f99d8
curl    curl-vtls@7161cb17c01d        462 files / 5,642,431 bytes
        sha256:38f1f8a85994af6568664e7b4f8ceebdf73395b59806c2db06e2268bc42d819e
algorithm: sha256 over sorted("path\0sha256(content)\n")
status:    pending_publication
```

逐文件清单（路径、内容 sha256、大小、Git blob id）在各 `lock.json` 的
`corpus.files`。

## 命令

以下命令以 libgit2 为例；把 `libgit2` 换成 `nginx` / `curl` 即可，POCO 省略
子目录：

```bash
# 生成 / 重算语料锁
python3 tools/freeze_library.py snapshot \
  --spec v2/windows_to_kylin/library/libgit2/freeze.yaml --offline

# 校验锁没有被漂移
python3 tools/freeze_library.py verify \
  --spec v2/windows_to_kylin/library/libgit2/freeze.yaml --offline

# 组件库审核发布后登记发布树
python3 tools/freeze_library.py publish \
  --spec v2/windows_to_kylin/library/libgit2/freeze.yaml \
  --library-root <published-library> --component-count <n>

# 同时校验发布树
python3 tools/freeze_library.py verify \
  --spec v2/windows_to_kylin/library/libgit2/freeze.yaml \
  --library-root <published-library>
```

默认从 `$MIGRATION_BENCH_CACHE/repos`（缺省 `~/.cache/migration-bench/repos`）
读取已缓存的 blobless clone；`--offline` 禁止 clone/fetch，`--repo` 可指向
任意本地 Git 仓库。

## 任务如何消费

每个任务包的 `task.yaml` 都有：

```yaml
task_family: v2
family: <dataset family>
library_manifest: v2/windows_to_kylin/library/<dataset>/lock.json
```

POCO 任务使用 `library/lock.json`，其余任务使用对应子目录的锁。判分只依赖
任务包自身，不依赖库；库是 B 条件的方法材料。发布后，B 臂读取
`lock.json.library.version` 和 `library_digest`，B0 臂按现有方法流程在 attempt
内现建库，A 臂不读库。

## 为什么用内容哈希而不是 Git blob id

Git blob id 随仓库镜像、re-pack 或哈希算法迁移而变化；内容哈希只随文件字节
变化。`lock.json` 同时保留 blob id 作为审计线索，但语料摘要只由内容计算。