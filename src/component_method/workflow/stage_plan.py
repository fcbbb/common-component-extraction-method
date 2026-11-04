"""最终方法的八阶段执行计划。"""

from __future__ import annotations


STAGES = (
    {
        "number": 1,
        "name": "source_scan",
        "title": "扫描和切分源码",
        "entrypoints": ("component_method.source_scan.prepare_inputs",),
    },
    {
        "number": 2,
        "name": "signal_analysis",
        "title": "计算结构、重复代码和语义信号",
        "entrypoints": (
            "component_method.signal_analysis.prepare_embeddings",
            "component_method.signal_analysis.compute_embeddings",
        ),
    },
    {
        "number": 3,
        "name": "protocol_candidates",
        "title": "生成协议候选",
        "entrypoints": ("component_method.protocol_candidates.build_candidates",),
    },
    {
        "number": 4,
        "name": "component_build",
        "title": "抽取、审核和运行时验证组件",
        "entrypoints": (
            "component_method.component_build.run_extraction",
            "component_method.component_build.curate_components",
            "component_method.component_build.prepare_reviews",
            "component_method.component_build.run_reviews",
        ),
    },
    {
        "number": 5,
        "name": "library_publish",
        "title": "发布组件库",
        "entrypoints": ("component_method.library_publish.publish_library",),
    },
    {
        "number": 6,
        "name": "retrieval",
        "title": "针对任务检索组件",
        "entrypoints": ("component_method.retrieval.run_retrieval",),
    },
    {
        "number": 7,
        "name": "task_execution",
        "title": "运行直接基线和组件方案",
        "entrypoints": ("component_method.task_execution.run_task",),
    },
    {
        "number": 8,
        "name": "reporting",
        "title": "汇总 20 个任务结果",
        "entrypoints": ("component_method.reporting.summarize",),
    },
)


STAGE_BY_NAME = {stage["name"]: stage for stage in STAGES}
