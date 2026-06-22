"""Scheduler 子系统（V2 架构）。

设计文档第 4 节 scheduler 模块：
  任务状态机、优先级、抢占、暂停恢复、并发配额。

接口（设计文档第 4 节）：
  create_task(goal, priority) / pause(task_id) / resume(task_id) / cancel(task_id) / next_runnable()

验收点：
  - 支持 READY/RUNNING/BLOCKED/WAITING/DONE/PAUSED 状态
  - 支持暂停恢复（任务失败后可恢复——设计文档第 8 节）
  - 优先级队列
"""

from orion_agent_runtime.scheduler.scheduler import Scheduler
from orion_agent_runtime.scheduler.task import Task, TaskStatus

__all__ = ["Scheduler", "Task", "TaskStatus"]
