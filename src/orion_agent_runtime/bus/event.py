"""统一事件数据模型与事件类型常量。

严格遵循设计文档第 5 节：所有模块之间传递尽量使用统一事件对象。
事件类型目录来源于现有 audit_log.py 的 event_type 枚举 + 设计文档第 5 节扩展。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType:
    """事件类型常量目录（按域分组）。

    这些字符串既是 EventBus 的路由键，也是审计日志的 event_type。
    复用现有 audit_log.py 已有的事件名，保证 V1/V2 事件可互译。
    """

    # ---- task 生命周期 ----
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"

    # ---- plan 规划 ----
    PLAN_GENERATED = "plan.generated"
    PLAN_REPAIRED = "plan.repaired"
    PLAN_NEXT_ACTION = "plan.next_action"

    # ---- action 动作（统一执行语义）----
    ACTION_REQUESTED = "action.requested"
    ACTION_COMPLETED = "action.completed"
    ACTION_FAILED = "action.failed"

    # ---- browser 能力 ----
    BROWSER_NAVIGATE = "browser.navigate"
    BROWSER_CLICK = "browser.click"
    BROWSER_TYPE = "browser.type"
    BROWSER_SNAPSHOT = "browser.snapshot"
    BROWSER_CLOSED = "browser.closed"

    # ---- desktop 能力 ----
    DESKTOP_FOCUS = "desktop.focus"
    DESKTOP_CLICK = "desktop.click"
    DESKTOP_TYPE = "desktop.type"
    DESKTOP_SNAPSHOT = "desktop.snapshot"

    # ---- terminal / filesystem / api 能力 ----
    TERMINAL_RUN = "terminal.run"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    API_CALL = "api.call"

    # ---- perception 感知 ----
    VISION_LOCATED = "vision.located"
    VISION_DESCRIBED = "vision.described"
    OCR_EXTRACTED = "ocr.extracted"

    # ---- memory 记忆 ----
    MEMORY_WRITE = "memory.write"
    MEMORY_READ = "memory.read"

    # ---- world 世界模型 ----
    WORLD_UPDATED = "world.updated"

    # ---- audit & safety ----
    AUDIT_RECORDED = "audit.recorded"
    SAFETY_APPROVED = "safety.approved"
    SAFETY_REJECTED = "safety.rejected"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    STAGNATION_DETECTED = "stagnation_detected"

    # ---- goal verification（复用 V1 checker 语义）----
    GOAL_VERIFICATION_START = "goal_verification_start"
    GOAL_VERIFICATION_COMPLETED = "goal_verification_completed"
    GOAL_VERIFICATION_FAILED = "goal_verification_failed"


class Event(BaseModel):
    """统一事件对象（设计文档第 5 节）。

    所有模块之间传递的标准化消息。字段与设计文档完全一致：
    id / timestamp / source / target / type / task_id / run_id / payload。
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str  # 发出模块，如 "planner"/"browser"/"executor"
    target: Optional[str] = None  # 目标模块，None 表示广播
    type: str  # 见 EventType
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def make_event(
    type: str,
    source: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    target: Optional[str] = None,
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Event:
    """构造事件的便捷工厂（自动填充 id 与 timestamp）。"""
    return Event(
        type=type,
        source=source,
        target=target,
        task_id=task_id,
        run_id=run_id,
        payload=payload or {},
    )
