# Windows → POSIX 迁移经验组件库（方法论层）

- 日期：2026-11-21
- 状态：v0，待评审
- 范围：`windows_to_kylin` 场景下的 **transformation 组件**
- 首个使用方：`v2_libgit2_util_full` 的试点（仅作为测试床，不进统计，不在组件里写该任务细节）

## 1. 这个库里放什么

这里只放**从已成功的迁移中抽取出来的方法论**，回答“这类迁移怎么做、哪里会错、怎么验证”。

不放：

- 当前任务的文件清单、调用点行号、函数分步实现；
- 可直接粘贴的目标实现或头文件片段；
- 某个项目的专属命名、构建命令、测试名。

放：

- 适用场景与触发条件；
- 成功迁移中重复出现的判断与动作；
- 源平台/目标平台的语义差异；
- 已经踩过的坑；
- 行为级验证策略；
- 适用边界（什么时候不该用）。

## 2. 与 anchor 的分工

| | anchor | transformation（本库） |
|---|---|---|
| 语料 | 当前任务的源码、头文件、调用方 | 其他任务/项目的成功迁移 |
| 回答 | 在哪里、要守住什么 | 怎么变、有什么坑 |
| 形态 | 任务相关，可含位置与契约 | 项目无关，规则与决策 |
| 产出方式 | v2 的源侧抽取流水线 | 本库手工抽取，后续自动化 |

anchor 不在本库中。本库只负责 transformation；两者在使用时 join。

## 3. 来源与 provenance

所有组件只引用**已经验证通过**的迁移：

| 来源 | 任务 | 验证状态 | 提供什么 |
|---|---|---|---|
| libarchive 读磁盘 | `v3/windows_to_kylin/tasks/l2_libarchive_read_disk` | gold 正控通过 | 目录遍历、nlink/inode/device、符号链接/硬链接、访问顺序、文件类型 |
| libarchive 写磁盘 | `v3/windows_to_kylin/tasks/l2_libarchive_write_disk` | gold 正控通过 | 恢复路径、权限/时间等元数据、符号链接/硬链接、部分写入与错误 |
| libuv 进程 | `v3/windows_to_kylin/tasks/l2_libuv_process` | gold 正控通过 | `CreateProcess` → fork/exec/posix_spawn、stdio、env、wait |
| libuv 线程 | `v3/windows_to_kylin/tasks/l2_libuv_thread` | gold 正控通过 | 线程/互斥/条件变量/rwlock/TLS |
| libuv 文件系统 | `v3/windows_to_kylin/tasks/l2_libuv_fs` | gold 正控通过 | open/stat/realpath/目录/readlink 语义 |
| 既有任务的构建入口 | 上述任务及其 `prepare.sh` / 构建配置 | 可复现 | 单文件或源目录被移除后的构建发现与失败形态 |

引用方式：组件里写“来自哪个迁移的哪类经验”，不复制其实现代码。

## 4. 组件清单

| ID | 组件 | 触发条件 |
|---|---|---|
| `T1` | [平台契约恢复](components/T1/README.md) | 目标平台实现缺失，共享头文件/调用方还在 |
| `T2` | [文件抽象层移植](components/T2/README.md) | 要移植 open/read/write/stat/目录/路径/时间 |
| `T3` | [进程创建移植](components/T3/README.md) | 要移植进程启动、stdio 捕获、环境、等待 |
| `T4` | [线程与同步移植](components/T4/README.md) | 要移植线程、互斥、条件变量、rwlock、TLS |
| `T5` | [构建发现与移除边界](components/T5/README.md) | 源目录/实现文件被整体移除后的构建与链接 |

组件之间可以组合：T1 通常先读，T2–T4 按缺失层选择，T5 负责让实现真正进入构建。

## 5. 抽取原则

1. **只写可迁移的决策**。能写成“当 X 时选 Y，因为 Z”的，才进组件；只对某个项目成立的实现细节不进。
2. **每条坑都要有来源**。坑要么在成功迁移中被处理过，要么在该迁移的失败/返修记录里出现过。
3. **验证写成行为**。不写测试文件路径和命令，写“什么行为必须成立”。
4. **显式写边界**。每个组件都有“不适用”的条件，避免 agent 把规则硬套。
5. **不含答案**。组件描述方法；具体符号名、文件布局、构建命令由 agent 从当前工作区恢复。

## 6. 当前缺口

- 只有 transformation，没有 anchor；anchor 仍由 v2 的源侧抽取负责。
- 进程组件的超时/信号细节只覆盖到“如何正确报告退出”，未覆盖 kill/进程组（当前来源迁移里不是重点）。
- 文件组件未覆盖网络文件系统、异步 I/O 和 Windows 专有重解析点。
- 构建组件是经验规则，不是对所有构建系统的保证。

## 7. 下一步

1. 评审五个组件的粒度与边界；
2. libgit2 util 试点已完成（`run_once`，不进统计）；
3. 按仓库级切分，在与建库来源不重叠的 held-out 题上验证；
4. 根据失败点补组件，而不是补任务答案；
5. 再把本库的抽取过程自动化（history_scan → align → abstract → validate）。