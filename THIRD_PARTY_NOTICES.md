# 第三方内容与许可证说明

`src/component_method/` 中的部分组件发现与运行支持实现源自 FeatureBench 项目，并随本仓库中的 `LICENSE` 按 MIT 许可证分发。

`src/component_method/task_execution/vendor/official_eval/` 包含 SWE-rebench 正式评测解析器的最小运行子集，许可证见该目录中的 `LICENSE`。

本仓库同级的 `offline_artifacts/` 目录包含 18 个第三方开源项目的生产源码快照和任务材料。源码快照附带的许可证或声明文件位于对应任务的 `source_snapshot/repository_licenses/` 目录。相关项目的著作权和许可证条款仍归各自权利人所有。

离线制品还包含 SWE-rebench 任务元数据和实验生成结果。在将全部离线材料公开上传到 GitHub 前，应复核上游数据集条款和每个项目的许可证。

分发时应：

1. 将 `repository/` 作为代码仓库主体；
2. 对 `offline_artifacts/` 完成许可证复核；
3. 将复核后的离线材料作为独立 Release 资产或受控复现包发布。
