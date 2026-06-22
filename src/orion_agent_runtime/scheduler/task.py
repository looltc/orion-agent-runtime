"""Task 数据模型 + TaskStatus 状态机枚举。

设计文档第 4 节 scheduler：
  Task 状态：READY / RUNNING / BLOCKED / WAITING / DONE / PAUSED / FAILED

状态机迁移规则（合法迁移）：
  READY     → RUNNING（调度启动）
  RUNNING   → BLOCKED（等待资源）
  RUNNING   → WAITING（等待外部事件/审批）
  RUNNING   → DONE（正常完成）
  RUNNING   → PAUSED（人工暂停）
  RUNNING   → FAILED（执行失败）
  BLOCKED   → RUNNING（资源就绪）
  BLOCKED   → PAUSED（人工暂停）
  WAITING   → RUNNING（外部事件到达）
  WAITING   → PAUSED（人工暂停）
  PAUSED    → RUNNING（恢复）
  PAUSED    → CANCELLED（取消）
  DONE/FAILED/CANCELLED → 终态（不可迁移）
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态枚举。"""
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING = "waiting"
    DONE = "done"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 终态：不可再迁移
TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}

# 合法状态迁移表：from_status -> set[to_status]
_VALID_TRANSITIONS: Dict[TaskStatus, set] = {
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.BLOCKED,
        TaskStatus.WAITING,
        TaskStatus.DONE,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.CANCELLED},
    TaskStatus.WAITING: {TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.CANCELLED},
    TaskStatus.PAUSED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    # 终态无迁移
    TaskStatus.DONE: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class Task(BaseModel):
    """任务模型（调度单元）。

    字段覆盖设计文档第 4 节 scheduler/task.py：
    - id / goal / priority / status / created_at
    - success_criteria：可验证的验收点
    - run_id：绑定的运行 id
    - iterations / result / error：运行时指标
    - snapshot_data：暂停时保存的世界状态快照（支持恢复）
    """

    id: str
    goal: str
    priority: int = 0  # 越高越优先
    status: TaskStatus = TaskStatus.READY
    success_criteria: List[str] = Field(default_factory=list)
    run_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    iterations: int = 0
    result: Optional[Any] = None
    error: Optional[str] = None
    # 暂停恢复支持：保存时持久化世界状态快照
    snapshot_data: Optional[Dict[str, Any]] = None

    def __lt__(self, other: "Task") -> bool:
        """优先级排序（heapq 用）：优先级高的先出，同优先级按创建时间早的先出。"""
        return task_priority_key(self) < task_priority_key(other)

    def can_transition(self, to_status: TaskStatus) -> bool:
        """检查状态迁移是否合法。"""
        return to_status in _VALID_TRANSITIONS.get(self.status, set())

    def transition(self, to_status: TaskStatus) -> "Task":
        """执行状态迁移，返回新 Task 实例（不可变语义）。

        非法迁移抛 ValueError。
        终态不可再迁移。
        """
        if self.status in TERMINAL_STATUSES:
            raise ValueError(
                f"task {self.id} is in terminal status {self.status.value}, cannot transition"
            )
        if not self.can_transition(to_status):
            raise ValueError(
                f"invalid transition: {self.status.value} -> {to_status.value} "
                f"for task {self.id}"
            )
        data = self.model_dump()
        data["status"] = to_status
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return Task.model_validate(data)


def task_priority_key(task: Task):
    """优先级排序 key（priority 越高越靠前，相同则按创建时间早的优先）。"""
    return (-task.priority, task.created_at)
