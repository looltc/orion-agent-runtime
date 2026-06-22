"""Scheduler —— 任务调度器。

设计文档第 4 节 scheduler：
  任务状态机、优先级、暂停恢复、并发配额。

接口（设计文档第 4 节）：
  create_task(goal, priority) / pause(task_id) / resume(task_id) / cancel(task_id) / next_runnable()

关键约束（设计文档第 8 节验收点）：
  - 任务失败后可恢复并从最近状态继续（暂停时保存 snapshot_data）
  - 所有任务记录可追踪（配合 audit）
"""

from __future__ import annotations

import heapq
import logging
from typing import Dict, List, Optional

from orion_agent_runtime.scheduler.task import (
    TERMINAL_STATUSES,
    Task,
    TaskStatus,
    task_priority_key,
)

logger = logging.getLogger(__name__)


class Scheduler:
    """任务调度器（进程内，基于优先级队列）。

    所有操作同步（状态机迁移本身是纯计算，异步化留给 Kernel/EventBus 层）。
    """

    def __init__(self, *, max_concurrent: int = 1) -> None:
        self.max_concurrent = max_concurrent
        self._tasks: Dict[str, Task] = {}
        # 优先级队列（heapq，最小堆，key 用 -priority + created_at）
        self._queue: List[Task] = []
        self._heap_valid: bool = True  # 脏标记：任务更新后需重建堆

    # ---- 创建 ----
    def create_task(
        self,
        goal: str,
        priority: int = 0,
        *,
        task_id: str,
        success_criteria: Optional[List[str]] = None,
        run_id: Optional[str] = None,
    ) -> Task:
        """创建任务并加入调度队列（初始状态 READY）。"""
        if task_id in self._tasks:
            raise ValueError(f"task {task_id} already exists")
        task = Task(
            id=task_id,
            goal=goal,
            priority=priority,
            success_criteria=success_criteria or [],
            run_id=run_id,
        )
        self._tasks[task_id] = task
        heapq.heappush(self._queue, task)
        self._heap_valid = True
        return task

    # ---- 状态迁移 ----
    def start(self, task_id: str) -> Task:
        """READY → RUNNING（调度启动）。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.RUNNING)
        self._update(task_id, new_task)
        return new_task

    def complete(self, task_id: str, *, result: Optional[object] = None) -> Task:
        """RUNNING → DONE。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.DONE)
        if result is not None:
            data = new_task.model_dump()
            data["result"] = result
            new_task = Task.model_validate(data)
        self._update(task_id, new_task)
        return new_task

    def fail(self, task_id: str, *, error: str) -> Task:
        """RUNNING → FAILED。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.FAILED)
        data = new_task.model_dump()
        data["error"] = error
        new_task = Task.model_validate(data)
        self._update(task_id, new_task)
        return new_task

    def pause(self, task_id: str, *, snapshot_data: Optional[Dict] = None) -> Task:
        """RUNNING/BLOCKED/WAITING → PAUSED（保存快照供恢复）。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.PAUSED)
        if snapshot_data is not None:
            data = new_task.model_dump()
            data["snapshot_data"] = snapshot_data
            new_task = Task.model_validate(data)
        self._update(task_id, new_task)
        return new_task

    def resume(self, task_id: str) -> Task:
        """PAUSED → RUNNING（恢复执行）。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.RUNNING)
        self._update(task_id, new_task)
        return new_task

    def block(self, task_id: str) -> Task:
        """RUNNING → BLOCKED（等待资源）。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.BLOCKED)
        self._update(task_id, new_task)
        return new_task

    def unblock(self, task_id: str) -> Task:
        """BLOCKED → RUNNING（资源就绪）。"""
        task = self._require(task_id)
        new_task = task.transition(TaskStatus.RUNNING)
        self._update(task_id, new_task)
        return new_task

    def cancel(self, task_id: str) -> Task:
        """任意非终态 → CANCELLED。"""
        task = self._require(task_id)
        if task.status in TERMINAL_STATUSES:
            raise ValueError(f"task {task_id} already in terminal status {task.status.value}")
        new_task = task.transition(TaskStatus.CANCELLED)
        self._update(task_id, new_task)
        return new_task

    # ---- 查询 ----
    def next_runnable(self) -> Optional[Task]:
        """取下一个可运行的 READY 任务（按优先级排序）。

        跳过 RUNNING/BLOCKED/WAITING/DONE/PAUSED/FAILED/CANCELLED。
        """
        self._rebuild_heap_if_needed()
        while self._queue:
            task = heapq.heappop(self._queue)
            if task.id not in self._tasks:
                continue  # 已删除
            if task.status == TaskStatus.READY:
                return self._tasks[task.id]
            # 非 READY 的不重新入队（后续状态变更会触发 rebuild）
        return None

    def get(self, task_id: str) -> Task:
        return self._require(task_id)

    def list_all(self) -> List[Task]:
        return list(self._tasks.values())

    def list_by_status(self, status: TaskStatus) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == status]

    def running_count(self) -> int:
        return len(self.list_by_status(TaskStatus.RUNNING))

    # ---- 内部 ----
    def _require(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            raise KeyError(f"task not found: {task_id}")
        return self._tasks[task_id]

    def _update(self, task_id: str, new_task: Task) -> None:
        self._tasks[task_id] = new_task
        self._heap_valid = False  # 状态变更使堆失效

    def _rebuild_heap_if_needed(self) -> None:
        if self._heap_valid:
            return
        self._queue = []
        for task in self._tasks.values():
            if task.status == TaskStatus.READY:
                heapq.heappush(self._queue, task)
        self._heap_valid = True

    def remove(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._heap_valid = False
