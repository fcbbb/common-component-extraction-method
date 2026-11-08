# 共性组件抽取流水线多语言重构方案

## 1. 背景

当前流水线以 Python 生产源码为唯一输入语言。Python 不仅存在于源码解析阶段，还进入了组件数据契约、Agent 文件提交协议、组件运行时验证、发布目录结构、任务执行环境和正式评测流程。

现有实现可以分为两类：

- **方法级通用能力**：工作流编排、输入冻结、哈希校验、语义向量计算、候选图融合、候选压缩、组件审核流程、组件检索、Docker 隔离和结果汇总。
- **Python 语言能力**：Python 文件发现、AST 和 token 解析、代码单位命名、协议关系提取、组件源码格式、入口点定义、编译导入、运行时调用观测、稳定导入包和 Python 测试执行。

如果直接为第二种语言复制现有目录，会迅速形成多套不一致的抽取、审核和发布流程。正确方向是保留 Python 作为流水线控制器，将被分析仓库的语言行为下沉到显式的语言后端。

本文给出从当前单语言实现迁移到可持续扩展的多语言架构的实施方案。方案优先保证已有 Python 实验行为和发布结果不发生隐式变化，首个新增后端选择 C++，之后按同一套后端契约继续接入 Java、Go、JavaScript/TypeScript 或其他目标语言。架构不将语言数量固定为两种。

## 2. 目标与非目标

### 2.1 目标

1. Python 继续作为流水线控制器和默认语言后端。
2. 源码扫描、结构信号、协议关系和运行时验证均通过语言后端调用。
3. 核心流水线不再判断 `.py`、`FunctionDef`、`ClassDef`、`PYTHONPATH` 或 `run(common)`。
4. 一个任务或仓库可声明一个或多个语言后端；每个源码单元、候选和组件都必须带有明确的 `language` 和 `backend_id`。
5. 组件制品支持多文件和非 Python 构建方式。
6. 检索、证据引用、任务盲边界和发布审计继续保持语言无关。
7. Python 迁移期间，现有测试、输入哈希和关键产物结构具有可解释的兼容策略。

### 2.2 非目标

1. 不要求首轮同时交付所有目标语言；首先用 C++ 验证抽象，后续语言逐个通过同一套契约测试接入。
2. 不把流水线控制器改写成 C++、Java、Go 或其他语言。
3. 不允许 Agent 自由提供未经信任的编译和执行命令。
4. 不在初次重构中支持一个组件横跨多种语言。
5. 不改变候选选择、任务盲抽取和后续任务检索的实验原则。
6. 不以正则表达式替代正式解析器作为长期语言实现。

## 3. 当前耦合分析

当前非 vendor Python 主代码约 16,500 行。语言耦合主要集中在以下位置。

| 区域 | 当前语言绑定 | 重构强度 |
| --- | --- | --- |
| `source_scan/` | Python AST、函数/类/方法单元 | 高 |
| `signal_analysis/` | Python tokenize、AST 骨架 | 中高 |
| `protocol_candidates/` | decorator、`self`/`cls`、Python 调用与定义 | 中高 |
| `component_build/submission.py` | `.py`、Python 编译、`run(common)` | 高 |
| `component_build/validation/` | import、`compile()`、frame profiler、async | 极高 |
| `library_publish/` | `component.py`、Python import 示例 | 中高 |
| `retrieval/` | 大部分语言无关，物化阶段绑定 Python package | 低到中 |
| `task_execution/` | `PYTHONPATH`、Python 语法检查、pytest 语义 | 高 |
| `workflow/` | 阶段编排和冻结逻辑 | 低 |
| `reporting/` | 结果读取和汇总 | 低 |

预计工作量：

- 只增加一种新语言但不建立稳定抽象：修改或复制约 5,000 至 8,000 行，后续维护成本高。
- 建立正式多语言架构：首次修改约 7,000 至 10,000 行。
- 完成架构后，每个新语言后端约 1,500 至 3,500 行；C++ 因预处理、编译和链接复杂度，预计位于上限或超过上限，不含语言专用测试镜像和评测适配。

## 4. 目标架构

### 4.1 分层

目标架构分为四层：

```text
workflow / reporting / retrieval policy
                |
language-neutral component pipeline
                |
LanguageBackend interfaces
                |
python / cpp / java / go / javascript / ... backends
```

核心流水线只处理规范化数据，不直接导入语言解析库。

### 4.2 建议目录

```text
src/component_method/
  languages/
    __init__.py
    registry.py
    contracts.py
    base.py
    python/
      __init__.py
      backend.py
      discovery.py
      units.py
      lexical.py
      structure.py
      protocol.py
      artifact.py
      runtime.py
      publication.py
      task_runtime.py
    cpp/
      __init__.py
      backend.py
      discovery.py
      units.py
      lexical.py
      structure.py
      protocol.py
      artifact.py
      runtime.py
      publication.py
      task_runtime.py
    java/
      ...
  source_scan/
    prepare_inputs.py
  signal_analysis/
    ngrams.py
    fusion.py
    prepare_embeddings.py
    compute_embeddings.py
  protocol_candidates/
    build_candidates.py
    extraction.py
    protocol_recall.py
  component_build/
  library_publish/
  retrieval/
  task_execution/
  workflow/
```

`source_scan/units.py` 等现有 Python 实现先迁移到 `languages/python/`，原模块保留兼容导入，待所有调用点迁移后再删除。

## 5. 语言无关数据契约

### 5.1 SourceUnit

现有 `unit_id="method:Class.method"` 同时承担类型、名字和层级关系，难以表达 C++ 重载/模板/命名空间、JavaScript 导出和 Go receiver。应改为结构化对象：

```json
{
  "schema": "source-unit-v2",
  "language": "python",
  "backend_id": "python@1",
  "file_id": "src/package/parser.py",
  "unit_key": "稳定哈希",
  "kind": "method",
  "qualified_name": "Parser.parse",
  "display_name": "parse",
  "parent_qualified_name": "Parser",
  "signature": "parse(self, value: str) -> Node",
  "span": {
    "start_line": 20,
    "end_line": 42
  },
  "source_code": "...",
  "metadata": {}
}
```

约束：

- `kind` 使用规范枚举，如 `module`、`namespace`、`function`、`class`、`struct`、`method`、`interface`、`constructor`、`destructor`、`type`、`constant_group`。
- `qualified_name` 只由语言后端解释，核心算法不得按冒号或点号拆分语义。
- `unit_key` 由语言、backend identity、文件、kind、qualified name、签名共同生成。
- 重载函数、模板特化和同名符号必须拥有不同 `unit_key`，即使 `qualified_name` 相同。
- 多语言仓库中，`unit_key` 必须包含 `language`，不允许不同后端的单元发生身份冲突。

### 5.2 UnitProfile

协议召回需要统一 profile：

```json
{
  "unit_key": "...",
  "defined_symbols": ["Parser", "Parser.parse"],
  "referenced_symbols": ["Token", "normalize"],
  "calls": ["normalize", "Token.from_value"],
  "registration_keys": [],
  "flow_names": ["previous_value"],
  "state_reads": ["Parser.cache"],
  "state_writes": ["Parser.cache"],
  "related_members": ["Parser.validate"],
  "protocol_markers": ["visitor", "factory"]
}
```

核心协议召回只消费这些字段。何种语法构成 call、state 或 registration 由后端决定。

### 5.3 ComponentArtifact

现有 `library.content` 只能表达一个 Python 文件。替换为多文件制品：

```json
{
  "schema": "component-artifact-v2",
  "language": "cpp",
  "backend_id": "cpp@1",
  "files": [
    {
      "path": "include/component/parser_support.hpp",
      "content": "...",
      "role": "header"
    },
    {
      "path": "src/parser_support.cpp",
      "content": "...",
      "role": "source"
    }
  ],
  "entrypoints": [
    {
      "kind": "function",
      "qualified_name": "component::parse",
      "signature": "Node parse(std::string_view value)",
      "purpose": "..."
    }
  ],
  "runtime": {
    "backend": "cpp",
    "artifact_type": "static_library",
    "toolchain": "repository"
  }
}
```

兼容期内允许读取旧 `library.content`，但进入核心流水线后立即转换成 `ComponentArtifact`。

### 5.4 SmokeCase

不要把测试写死为 `test_py` 和 `run(common)`：

```json
{
  "case_id": "case-1",
  "entrypoint_id": "...",
  "files": [
    {
      "path": "component_smoke.cpp",
      "content": "..."
    }
  ],
  "expected_paths": [
    {
      "entrypoint_id": "...",
      "mode": {
        "arguments": {"format": "json"}
      }
    }
  ],
  "sources": []
}
```

运行命令不能由模型填写，而由可信语言后端生成。

## 6. LanguageBackend 接口

建议在 `languages/base.py` 定义多个小接口，避免一个巨型 backend 类。

```python
class SourceBackend(Protocol):
    language_id: str

    def eligible_files(self, root: Path, source_subdir: str) -> Iterable[Path]: ...
    def extract_units(self, file_id: str, source: str) -> list[SourceUnit]: ...
    def validate_source(self, file_id: str, source: str) -> list[Diagnostic]: ...


class SignalBackend(Protocol):
    def normalized_tokens(self, unit: SourceUnit) -> TokenStream: ...
    def structural_tokens(self, unit: SourceUnit) -> TokenStream: ...
    def build_profile(self, unit: SourceUnit) -> UnitProfile: ...


class ArtifactBackend(Protocol):
    def validate_artifact(self, artifact: ComponentArtifact) -> list[Diagnostic]: ...
    def validate_entrypoints(self, artifact: ComponentArtifact) -> list[Diagnostic]: ...
    def validate_grounding(
        self,
        artifact: ComponentArtifact,
        repository: Path,
        members: list[SourceUnitRef],
    ) -> list[Diagnostic]: ...


class RuntimeBackend(Protocol):
    def prepare_smoke(
        self,
        artifact: ComponentArtifact,
        case: SmokeCase,
        workspace: Path,
    ) -> RuntimeInvocation: ...

    def parse_observations(
        self,
        invocation: RuntimeInvocation,
        result: ProcessResult,
    ) -> list[ExecutionObservation]: ...


class PublicationBackend(Protocol):
    def materialize_component(
        self,
        artifact: ComponentArtifact,
        destination: Path,
    ) -> PublishedComponent: ...

    def render_loading_instructions(self, published: PublishedComponent) -> str: ...


class TaskBackend(Protocol):
    def task_environment(self, task: TaskRecord, bundle: Path | None) -> TaskEnvironmentSpec: ...
    def validate_repository_edits(self, repository: Path) -> list[Diagnostic]: ...
```

注册表根据任务配置选择一个或多个后端：

```python
backends = language_registry.resolve(config["languages"])
backend = backends.for_path(source_path)
```

兼容期内可将旧配置 `language: python` 归一化为 `languages: [{id: python}]`。多语言仓库中的路径归属由各后端的文件规则与可选 include/exclude 配置决定；一个文件被多个后端同时声明时必须报冲突，不得静默选择。

推荐配置形态：

```yaml
languages:
  - id: python
    include: ["src/**/*.py"]
  - id: cpp
    include: ["include/**/*.h", "include/**/*.hh", "include/**/*.hpp", "include/**/*.hxx", "src/**/*.cc", "src/**/*.cpp", "src/**/*.cxx"]
    compile_database: "build/compile_commands.json"
candidate_policy:
  cross_language_edges: false
```

初期允许一个仓库同时启用多个后端，但一个候选和一个组件制品只属于一个后端。跨语言调用关系未来可通过单独的 bridge analyzer 加入；在证据模型定义清楚前，不把文件名相似或 FFI 字符串匹配直接当成跨语言候选边。

禁止以扩展名在核心模块内动态分支，例如：

```python
if path.suffix == ".py":
    ...
elif path.suffix in {".cpp", ".hpp"}:
    ...
```

扩展名选择必须封装在对应语言的 `eligible_files()` 中。

## 7. 核心算法如何保留

### 7.1 可直接保留

- `signal_analysis/ngrams.py` 的最大共享区间算法。
- 语义向量生成、归一化、矩阵校验和复用逻辑。
- HNSW 跨文件近邻查询。
- `fusion.py` 的信号阈值、图连通分量和候选嵌套消除框架。
- 协议候选的种子排序、边界限制和边际覆盖选择。
- packet 合并算法。
- 组件合同的业务字段和任务盲限制。
- 检索阶段的 catalog 完整扫描、证据精确匹配、去重和选择上限。
- Docker 网络、挂载和权限隔离。
- workflow、断点恢复、manifest、SHA-256 和结果汇总。

### 7.2 需要参数化

- 候选中的单位身份从 `(file_id, unit_id)` 改为 `unit_key`，展示信息单独保存。
- 扫描阶段对已启用后端 fan-out，按稳定顺序合并单位和 manifest；所有缓存键包含 backend identity。
- 候选图默认按语言后端分区构建，避免无语义依据的跨语言边；检索 catalog 可以汇总多个分区。
- `fusion._remove_nested_candidate_units()` 调用后端提供的 ancestor 关系。
- `protocol_recall.build_profiles()` 改为调用 `SignalBackend.build_profile()`。
- `component_build` 的入口点验证改为调用 `ArtifactBackend`。
- `validation` 的运行时命令、观测记录和覆盖判定改为调用 `RuntimeBackend`。
- 发布器的文件名、目录结构、加载说明和稳定入口改为调用 `PublicationBackend`。
- 任务执行的环境变量、编译器和编辑检查改为调用 `TaskBackend`。

## 8. Python 后端迁移

Python 必须作为第一个后端迁移，并保持行为等价。

### 8.1 文件迁移映射

| 当前文件 | 目标位置或处理方式 |
| --- | --- |
| `source_scan/units.py` | `languages/python/units.py` |
| `source_scan/unit_extraction.py` | `languages/python/discovery.py` |
| `signal_analysis/clone_signal.py` 中 tokenize 部分 | `languages/python/lexical.py` |
| `signal_analysis/ast_signal.py` | `languages/python/structure.py` |
| `protocol_candidates/protocol_recall.py` 中 AST profile | `languages/python/protocol.py` |
| `component_build/submission.py` 中 `.py` 校验 | `languages/python/artifact.py` |
| `component_build/validation/runtime.py` | 拆分为通用控制器和 `languages/python/runtime.py` |
| `component_build/context/component_context.py` 的 grounding | `languages/python/artifact.py` |
| `library_publish/component_cards.py` 的 AST 签名提取 | `languages/python/publication.py` |
| `task_execution/runtime_support/check_edits.py` | 通用 Git 检查加 `languages/python/task_runtime.py` |

### 8.2 兼容要求

Python 后端迁移完成时必须满足：

1. 对同一冻结源码，代码单位数量和顺序一致。
2. 旧 `unit_id` 可由新结构确定性渲染。
3. clone、skeleton 和 semantic 输入集合一致。
4. 协议候选排名和成员集合一致，或通过显式版本升级记录变化。
5. 旧组件 JSON 可无损迁移到新 schema。
6. Python smoke 的实际 callable 观测结果一致。
7. 现有 `pytest` 测试全部通过。

不建议为了追求完全相同的 JSON 字节而长期保留不合理结构。需要改变产物时，应升级 schema 并同时保留转换器和差异报告。

## 9. C++ 及后续语言接入方案

首个新增后端设置为 C++。C++ 不是多语言支持的终点，而是用来验证通用契约能否覆盖编译型语言、多文件制品和复杂构建系统的第一个实例。C++ 能检验以下抽象是否真实成立：

- 头文件与实现文件、声明与定义的关系。
- 命名空间、重载、操作符、模板和模板特化的稳定身份。
- 宏、条件编译和不同 compile flags 对语义解析的影响。
- 多文件、header-only、静态库和动态库组件制品。
- 编译、链接与运行三个独立阶段。
- CMake、Ninja、Make、Meson 或 Bazel 等仓库既有工具链。
- 自由函数、静态成员、实例方法和构造器的入口差异。

C++ 后端的语义解析首选 Clang LibTooling/libclang，并优先消费仓库的 `compile_commands.json`。Tree-sitter 可作为没有可用编译参数时的词法和容错结构后备，但不应伪装成完整语义结果。不得用正则表达式构造长期 AST/profile 实现。

头文件应在实际 translation unit 的编译上下文中解析，不能随意选择一组默认 flags 单独解析。若同一头文件在不同宏或编译参数下产生不同语义，后端应保留 configuration identity，并在归并时显式处理差异。

### 9.1 C++ 源码单元

- translation unit
- namespace
- class、struct、union 和 enum
- free function 和 member function
- constructor、destructor 和 conversion/operator function
- function template、class template 和 specialization
- type alias 和 concept，仅在候选边界或协议分析有价值时启用
- macro definition，作为独立低置信度单元，不与 AST 单元混合

单元身份优先使用 Clang USR，并绑定规范化签名、源文件和后端版本。只有声明的符号与具有定义的符号要分开记录，再通过 `declares/defines` 关系连接，避免同一个头文件被多个 translation unit 重复计数。

### 9.2 C++ 制品与构建

`ArtifactBackend` 至少支持 `header_only`、`object`、`static_library`、`shared_library` 和 `executable` 类型。制品必须声明 C++ standard、ABI/编译器约束、include path 和所需的仓库内依赖。

构建命令不能由 Agent 自由填写。`TaskBackend` 应从受信的适配器中选择仓库现有构建方式，例如 CMake preset、已有 Ninja target 或明确的编译参数模板。不得为通过组件验证而联网下载依赖。

### 9.3 C++ 运行时观测

Python 当前使用 `sys.setprofile` 判断入口点是否真正执行。C++ 按证据能力分层实现：

1. 由可信生成器产生 smoke harness，显式调用声明入口，并记录入参、返回状态和调用标识。
2. 工具链允许时，使用 LLVM source-based coverage 或等价的编译器覆盖能力，将运行记录映射回入口符号和源码 span。
3. 对无法插桩的仓库，只能将 harness 直接调用标记为较低等级证据，不得推断未观测的内部路径。
4. ASan、UBSan 等 sanitizer 结果只作为安全性诊断，不作为入口已执行的覆盖证据。

任何层级都不得把“编译成功”或“链接成功”当成“入口已执行”。

### 9.4 第三种及后续语言

C++ 后端完成后，后续语言不应复制主流程，而应仅新增后端包、运行镜像/工具链声明和契约测试数据。每接入一种语言都必须实现能力矩阵，不支持的能力显式标记，不得由核心层猜测：

| 能力 | 必选 | 说明 |
| --- | --- | --- |
| 文件发现与单元提取 | 是 | 产出稳定 SourceUnit |
| 词法与结构信号 | 是 | 支持 clone/skeleton 候选 |
| 协议 profile | 是 | 至少提供定义、引用和调用关系 |
| 制品校验 | 是 | 校验多文件和入口声明 |
| 可执行 smoke | 是 | 必须实际执行声明入口 |
| 精细内部覆盖 | 否 | 用 capability 和证据等级表达 |
| 发布和任务环境 | 是 | 不得假设 Python import 模型 |

第三种语言是架构验收点：如果接入时仍需修改候选图、检索策略、workflow 或通用验证控制器，说明前述语言边界仍不完整。

## 10. 分阶段实施计划

### 阶段 0：冻结当前行为

目标：为重构建立可比较基线。

任务：

- 保存代表性仓库的 units、signals、candidates、packet、组件和 runtime observation 金样。
- 增加每阶段 schema 版本和排序规则测试。
- 为关键 Python 语义增加 characterization tests。
- 记录当前完整测试结果和关键产物统计。

验收：重构前的 Python 行为可以通过自动化脚本重放和比较。

预计：3 至 5 个工程日。

### 阶段 1：引入语言注册与通用契约

目标：核心模块可获得 backend，但暂时只有 Python 实现。

任务：

- 新建 `languages/contracts.py`、`base.py` 和 `registry.py`。
- 在 workspace/task 配置加入 `languages` 列表，并兼容旧 `language: python`。
- 定义 SourceUnit、UnitProfile、ComponentArtifact、Entrypoint、SmokeCase。
- 增加旧 schema 到新 schema 的转换器。

验收：配置未写 `languages` 或旧 `language` 时仍默认 Python；现有命令可运行。

预计：4 至 6 个工程日。

### 阶段 2：迁移扫描和信号

目标：核心扫描与信号模块不再导入 Python AST/tokenize。

任务：

- 迁移文件发现、单元提取、token 和结构流。
- `prepare_embeddings.py` 调用 SourceBackend。
- clone 和 skeleton 仅消费规范 TokenStream。
- fusion 使用结构化 ancestor API。

验收：Python units、clone 和 skeleton 金样一致。

预计：5 至 8 个工程日。

### 阶段 3：迁移协议关系和候选

目标：协议召回算法与语言 profile 分离。

任务：

- 将 `_ProfileVisitor` 和 Python 语义移至后端。
- 通用层只构建 profile 倒排索引和关系图。
- relation kind 使用通用枚举，后端可增加带命名空间的扩展关系。
- 候选身份统一使用 unit key。

验收：Python 候选集合和选择统计一致，或产生经批准的版本化差异。

预计：5 至 8 个工程日。

### 阶段 4：迁移组件制品和提交协议

目标：Agent 可以提交非 Python、多文件组件。

任务：

- `library` 字段升级为 artifact。
- 文件提交协议允许后端声明的安全扩展名和目录布局。
- 组件字段验证与语言源码验证分离。
- 修改抽取和审核提示词，移除顶层 Python function/class 假设。

验收：旧 Python Agent 输出通过转换器继续工作；新格式支持多文件。

预计：6 至 9 个工程日。

### 阶段 5：迁移运行时验证

目标：通用验证控制器不执行 Python 专用逻辑。

任务：

- 将 compile/import/profile 逻辑迁移到 Python RuntimeBackend。
- 通用控制器负责容器、超时、日志、case 隔离和结果归并。
- 定义统一 ExecutionObservation。
- capability 覆盖判断只消费 observation，不解析语言源码。

验收：当前 runtime observation 测试迁移后全部通过。

预计：8 至 12 个工程日。

### 阶段 6：迁移发布、检索物化和任务执行

目标：组件文件布局和任务环境不再固定为 Python。

任务：

- PublicationBackend 生成语言专用布局和加载说明。
- selection bundle 不再固定创建 `component_api/*.py`。
- TaskBackend 提供 bundle 挂载、环境变量和编辑检查。
- catalog 增加 language、artifact type 和入口点签名。

验收：Python 任务执行和正式评测保持一致。

预计：6 至 9 个工程日。

### 阶段 7：实现 C++ 后端

目标：完成一条非 Python 端到端路径。

任务：

- C++ 头文件/源文件扫描、Clang 解析、词法信号和结构信号。
- C++ UnitProfile，包括声明/定义、调用、类型和模板关系。
- C++ artifact、编译/链接、smoke harness 和执行观测。
- CMake/compile database 任务环境与编辑检查。
- C++ 组件发布、检索物化和任务交付。

验收：至少一个冻结 C++ 仓库完成源码扫描、候选生成、组件抽取、审核、发布、检索、任务执行和评测；另有一个头文件与源文件分离的用例验证去重和链接。

预计：18 至 30 个工程日。

### 阶段 8：验证第 N 种语言的可插拔接入

目标：证明架构不是只对 Python+C++ 特制。

任务：

- 建立 backend scaffold 和统一 contract test kit。
- 选择下一种目标语言，只通过新增 `languages/<id>/`、工具链声明和测试 fixture 完成接入。
- 记录该语言的 capability matrix 和运行时证据等级。
- 将多语言仓库中的单元分区、候选隔离和检索合并纳入端到端测试。

验收：新语言接入不需在 workflow、候选图、检索策略和通用验证控制器中增加语言条件分支。

预计：6 至 20 个工程日/语言，具体取决于解析器、构建系统和运行时观测能力。

## 11. 文件级改造清单

### 必须重构

- `source_scan/units.py`
- `source_scan/unit_extraction.py`
- `signal_analysis/clone_signal.py`
- `signal_analysis/ast_signal.py`
- `protocol_candidates/protocol_recall.py`
- `component_build/contracts.py`
- `component_build/extraction/service.py`
- `component_build/submission.py`
- `component_build/validation/runtime.py`
- `component_build/validation/service.py`
- `component_build/repair/service.py`
- `library_publish/component_cards.py`
- `library_publish/agent_bundle.py`
- `library_publish/publish_library.py`
- `retrieval/selection_bundle.py`
- `task_execution/core/environment.py`
- `task_execution/core/evaluation.py`
- `task_execution/core/task.py`
- `task_execution/runtime_support/check_edits.py`

### 轻量参数化

- `signal_analysis/prepare_embeddings.py`
- `protocol_candidates/build_candidates.py`
- `protocol_candidates/extraction.py`
- `protocol_candidates/freeze.py`
- `component_build/run_extraction.py`
- `component_build/run_reviews.py`
- `retrieval/service.py`
- `retrieval/submission.py`
- `task_execution/run_task.py`
- `workflow/run_batch.py`
- `tools/prepare_workspace.py`
- `tools/preflight.py`

### 基本保持

- `signal_analysis/ngrams.py`
- `signal_analysis/compute_embeddings.py`
- `workflow/run_stage.py`
- `workflow/batch_common.py` 中通用状态与哈希逻辑
- `reporting/summarize.py`
- 发布完整性和清单验证框架

## 12. 测试策略

### 12.1 通用契约测试

- SourceUnit 稳定身份和排序。
- schema 版本转换。
- 非法路径、符号链接和目录逃逸。
- artifact 多文件完整性。
- backend 注册、缺失和重复注册。

### 12.2 Python 回归测试

- 现有 `tests/stage_03_protocol_candidates/`。
- 现有 `tests/stage_04_component_build/`。
- 现有 `tests/stage_05_library_publish/`。
- 现有 `tests/stage_06_retrieval/`。
- 现有 `tests/stage_07_task_execution/`。
- 新增冻结产物差异测试。

### 12.3 后端契约测试套件

所有后端必须通过同一组测试：

1. 可以稳定扫描同一源码两次。
2. 单元 span 不越界且不引用其他文件。
3. token/structure stream 与源码单元一一对应。
4. profile 引用的符号和关系具有源码依据。
5. artifact 路径均在输出目录内。
6. entrypoint 声明与实际制品一致。
7. smoke case 至少实际执行一个声明入口。
8. 未执行的入口不得标记 validated。
9. 网络关闭且源码挂载只读。
10. 发布包可从无关工作目录加载或执行。
11. 多后端文件归属无遗漏、无冲突，且结果不依赖后端注册顺序。
12. 同仓库多语言单元默认分别建图，检索阶段可合并 catalog，但不得丢失语言身份。

### 12.4 端到端测试矩阵

| 后端 | 扫描 | 候选 | 抽取 | 审核 | Runtime | 发布 | 检索 | 任务 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Python | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 |
| C++ | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 至少 1 个任务 |
| 后续每个后端 | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 | 至少 1 个任务 |
| Python+C++ 混合仓库 | 必须 | 必须 | 分语言 | 分语言 | 分语言 | 分语言 | 合并 catalog | 至少 1 个任务 |

## 13. 版本和兼容策略

需要升级的主要 schema：

- `source-unit-v1` 到 `source-unit-v2`
- `component-draft-v1` 到 `component-draft-v2`
- `component-artifact-v1` 到 `component-artifact-v2`
- bundle schema 7 到新的多语言版本
- smoke/validation 结果增加 language 和 backend identity

每个后端必须提供实现身份摘要：

```json
{
  "language": "python",
  "backend_version": "1",
  "parser": "stdlib-ast",
  "parser_version": "3.12",
  "implementation_sha256": "..."
}
```

该身份进入 embedding manifest、候选 manifest、组件审核缓存键和发布 manifest。后端代码或解析器版本变化时，不得静默复用旧产物。

对 C++ 还必须记录编译器 ID/版本、目标 triple、C++ standard、compile database 摘要和关键预处理宏摘要。一个任务启用多个后端时，manifest 保存有序 backend identity 列表及路径归属规则摘要。

## 14. 安全要求

1. 后端只能返回结构化 RuntimeInvocation，不能执行任意 host shell。
2. 编译和测试必须在隔离容器中执行。
3. 仓库源码始终只读，只有指定输出目录或任务工作区可写。
4. 运行时镜像必须固定 ID 或 digest。
5. 禁止后端从网络下载编译依赖。
6. 构建缓存不得包含宿主凭证或跨任务可写状态。
7. artifact 文件路径必须经过与当前 submission 协议同等级别的目录逃逸和符号链接检查。
8. 不同语言的工具链输出应设定大小、时间和进程限制。

## 15. 主要风险

### 15.1 伪通用抽象

如果接口仍使用 `class`、`method`、Python import 等概念，只是把文件移动到 backend 目录，C++ 或任一后续语言仍会迫使核心层增加条件分支。判断标准是核心模块能否在不知道扩展名和语法节点类型的情况下运行。

### 15.2 运行时覆盖证据变弱

不同语言的可观测能力不同。不能因为新语言难以插桩，就把 validated 降级成“编译成功”或“测试进程返回 0”。每个后端必须明确覆盖证据等级，并在发布信息中暴露。

### 15.3 组件制品与仓库构建系统耦合

C++、Java、JavaScript 等语言可能需要仓库依赖和构建配置。组件制品应默认复用任务仓库已有工具链，不应复制完整构建工程或下载新依赖。

### 15.4 旧产物不可比

结构化 unit key 和 artifact schema 会改变哈希。迁移时必须区分“算法结果变化”和“序列化格式变化”，通过转换器和语义比较工具说明差异。

### 15.5 提示词仍隐含 Python

即使代码接口完成抽象，提示词中的 function、class、`.py`、import 和 `run(common)` 仍可能约束模型输出。提示词必须拆成通用部分和后端附加部分，并进入后端身份摘要。

## 16. 里程碑与退出条件

### M1：Python 后端完成

- 核心模块不直接导入 `ast`、`tokenize` 或 `symtable`。
- 核心模块不包含 `.py`、`PYTHONPATH`、`run(common)` 判断。
- Python 全量测试通过。
- 代表性冻结产物完成语义对比。

### M2：多文件 artifact 完成

- 抽取、审核、修复、发布和检索均消费 ComponentArtifact。
- 旧 `library.content` 仅通过兼容转换器存在。
- Python 发布包仍可被现有任务 Agent 使用。

### M3：C++ 候选和组件完成

- C++ 可完成扫描、信号、候选和组件抽取。
- 组件有源码证据和协议合同。
- RuntimeBackend 能证明入口实际执行。

### M4：C++ 端到端完成

- 至少一个任务完成发布库冻结后的检索。
- 任务 Agent 能读取 C++ 组件包并使用仓库既有工具链完成编译和链接。
- 正式评测使用原始任务环境，而不是组件构建镜像。

### M5：多后端扩展性完成

- 第三种语言通过统一契约测试接入，核心层无该语言专用分支。
- 至少一个混合语言仓库完成扫描、候选分区、catalog 合并和检索。
- 新增后端有独立 capability matrix、工具链身份和端到端任务。

## 17. 推荐决策

建议采用以下实施原则：

1. **控制器继续使用 Python。** 重构对象是被分析语言，不是流水线实现语言。
2. **先迁移 Python，再实现 C++，随后持续接入其他语言。** C++ 是首个新增后端，不是支持范围上限。
3. **优先抽象运行时验证。** 这是语言绑定最深、也最影响组件可信度的部分。
4. **组件改为多文件 artifact。** 不为不同语言继续扩展 `library.content` 特例。
5. **核心层只消费规范化事实。** AST、token、构建工具和加载方式全部属于后端。
6. **保持任务盲和冻结边界。** 多语言改造不得削弱实验的信息隔离原则。

按此方案实施，工作流、候选图算法、检索策略和实验审计能够继续复用；第 N 种语言的主要成本被限制在解析、语言语义、制品验证、运行时观测和任务环境五个清晰边界内，而不是继续复制整条流水线。
