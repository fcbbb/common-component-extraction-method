# 运行要求

本目录的入口只依赖系统里已有的工具；镜像、任务源码、模型凭据和 MUSA 硬件由使用者自备。
`./bootstrap.sh` 和 `python3 tools/bench.py doctor` 会逐项检查，缺什么就报什么。

## 最小可跑矩阵

| 场景 | 需要的环境 | 判分硬件 |
|---|---|---|
| `ipp_to_vsipl` | Docker + `migration/ipp:cpu`（ubuntu:24.04 构建）+ 一份 jvsip 树（`VSIPL_ROOT`） | 任意 x86_64 |
| `windows_to_kylin` | Docker + `migration/kylin:sp3-p2`（由 `macrosan/kylin:v10-sp3-2403` + `almalinux:8` 构建） | 任意 x86_64 |
| `cuda_to_musa` | Docker + `migration/musa:s4000` + 可 SSH 的 MTT S4000 主机 | 真实 MTT S4000 |

没有 MUSA 硬件的机器把 `bench.yaml` 里 `cuda_to_musa.enabled` 改成 `false`，其余两个场景不受影响。

## 必备软件

| 组件 | 版本 | 检查方式 |
|---|---|---|
| Linux | x86_64；WSL2 可用 | `uname -m` |
| Python | >= 3.12 | `python3 --version` |
| PyYAML | >= 6.0 | `python3 -c "import yaml"` |
| Node.js | **24.9.0**（固定版本） | `node -v` |
| DSH | `@deepseek-ai/dsh` 0.2.2-rc.1（由 `../dsh/package-lock.json` 固定） | `npm ci` 后 `doctor` |
| Docker | 可用的 daemon，建议 >= 24 | `docker info` |
| Python docker SDK | >= 5.0.3（随 `pip install -e ..` 安装） | `python3 -c "import docker"`；缺失时方法阶段自动回退 host 平面 |
| git | 任意较新版本 | `git --version` |
| ssh / rsync | 仅 MUSA 远端需要 | `ssh -V`、`rsync --version` |

Node 不是 24.9.0 时，设 `COMPONENT_DSH_NODE_BIN=/path/to/node` 指向正确版本，或先 `nvm use 24.9.0`。
`bench.py` 不会替你切换 Node 版本。

## 需要联网的端点

首次准备会访问：

- Docker Hub：`ubuntu:24.04`、`macrosan/kylin:v10-sp3-2403`、`almalinux:8`；
- GitHub：40 个 A/B 任务包的 `prepare.sh` 会克隆固定 commit（IPP 的 20 题已 vendored，不需要联网）；
- npm registry：`../dsh` 的 `npm ci`；
- PyPI：`requirements.txt`（仅 PyYAML；方法包本体按 `../pyproject.toml` 安装）；
- 模型服务：`OPENAI_API_BASE` 指向的地址。

MUSA 镜像的构建参数和 wheel 来源见 `env/Dockerfile.musa` 与 `env/README.md`，需要厂商材料，不能从公网直接得到。

## 磁盘

建议预留 **20 GB** 以上：

| 内容 | 大致占用 |
|---|---|
| `../dsh/node_modules` | ~1 GB |
| 三个场景的 `work/`（物化后） | ~300 MB |
| Docker 镜像 | 数 GB |
| `reports/`（每次运行） | 数百 MB |

## 凭据

模型凭据三选一，优先级从高到低：

1. 命令行 `--api-base/--api-key/--model`；
2. 仓库根 `.env`（`../.env`）：`OPENAI_API_BASE`、`OPENAI_API_KEY`、`MODEL_NAME`；
3. `bench.env` 或继承的 shell 环境。

不要把 `.env`、`bench.env`、`env/remote.yaml` 提交到仓库。`bench.env.example` 和
`env/remote.yaml.example` 是模板。

MUSA 远端还需要 `env/remote.yaml`（主机、用户、askpass 等），格式见 `env/remote.yaml.example`。

## 不随仓库分发

| 内容 | 来源 |
|---|---|
| `../dsh/node_modules`、`../dsh/plugins/*/dist` | `cd ../dsh && npm ci && npm run build` |
| Docker 镜像 | `python3 tools/bench.py env`，或使用者自行构建 |
| 任务 `work/` | 各任务包的 `prepare.sh` |
| 任务 `gold/` | `prepare.sh` 从上游目标平台实现重新生成 |
| `reports/` | 本地运行产物，按需单独归档 |
| 组件库（方法臂） | 不需要外部提供：每次尝试由主 agent 在当次工作区现场抽取并发布；宿主机需可导入 `component_method`、可访问 Docker（`DOCKER_HOST`），镜像需具备目标工具链 |
| 方法准备镜像（方法臂） | 宿主机本地 Docker 镜像，含 `bash` 与 `python3`。本地场景默认用场景镜像；远端 MUSA 的目标镜像只在远端，需设 `METHOD_STAGE_IMAGE`（例如本地已有的 `migration/kylin:sp3-p2`） |
| `env/remote.yaml` | 从 `env/remote.yaml.example` 复制并填写 |

## 自检顺序

```bash
./bootstrap.sh                 # 只检查，不改动系统
./bootstrap.sh --fix           # 额外执行 npm ci && npm run build
./bootstrap.sh --build-images  # 额外执行 bench.py env
python3 tools/bench.py doctor --arm method
```