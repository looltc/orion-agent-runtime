"""Runtime 子系统（V2 事件驱动执行器）。

设计文档第 7 节运行流程的事件驱动实现：
  1. 用户提交 goal
  2. Kernel 创建 task
  3. Scheduler 分配 task
  4. Planner 根据 world_state 生成下一步 action
  5. Capability 执行动作
  6. Perception 采集结果
  7. World Model 更新状态
  8. Audit / Safety 记录并判断
  9. Reflection 在任务结束后沉淀经验
  10. 若未完成，回到第 4 步

最关键约束（设计文档第 7 节红线）：
  "Planner 每次只负责'下一步'，不要一次输出完整 50 步流程。"

本模块是 V2 入口，与 V1 的 core/workflow.py 并行存在（ORION_RUNTIME 开关切换）。
"""

from orion_agent_runtime.runtime.agent_runtime import AgentRuntime, RunResult
from orion_agent_runtime.runtime.executor_async import (
    execute_step_async,
    AsyncApprovalHook,
)

__all__ = [
    "AgentRuntime",
    "RunResult",
    "execute_step_async",
    "AsyncApprovalHook",
]
