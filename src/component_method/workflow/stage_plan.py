"""最终方法的执行计划。

执行单元是 :mod:`component_method.workflow.blocks` 中的原子块。 工作区级别的
embedding 和协议候选生成是运行前置条件，不属于任何单任务块。
"""

from __future__ import annotations

from component_method.workflow.blocks import BLOCKS, PER_TASK_BLOCKS


STAGES = tuple(
    {
        "name": block.name,
        "title": block.title,
        "steps": block.steps,
        "requires": block.requires,
        "produces": block.produces,
        "scope": block.scope,
    }
    for block in BLOCKS
)

PIPELINE = PER_TASK_BLOCKS

STAGE_BY_NAME = {stage["name"]: stage for stage in STAGES}