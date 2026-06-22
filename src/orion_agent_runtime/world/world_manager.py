"""WorldManager —— 事件驱动的世界状态管理器。

设计文档第 4 节 world 模块 + 第 7 节运行流程：
  Capability 执行动作 → Perception 采集结果 → World Model 更新状态

WorldManager 订阅事件总线上的 capability / action 事件，根据事件类型 apply 更新
内存中的 WorldState，并在状态变更后 emit world.updated 事件（形成事件驱动闭环）。

接口（设计文档第 4 节）：
- apply(event)
- snapshot()
- restore(snapshot)
- diff(previous_snapshot)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from orion_agent_runtime.bus.event import Event, EventType
from orion_agent_runtime.bus.event_bus import EventBus
from orion_agent_runtime.world.state import WorldState

logger = logging.getLogger(__name__)


class WorldManager:
    """订阅事件并维护 WorldState。

    使用方式：
        world = WorldManager(bus)
        await world.start()          # 订阅事件
        ...
        snap = world.snapshot()      # 取当前快照
        world.restore(snap)          # 恢复
    """

    def __init__(self, bus: EventBus, *, auto_subscribe: bool = True) -> None:
        self._bus = bus
        self._state: WorldState = WorldState()
        # 是否自动 emit world.updated（避免在 apply 内部触发的事件再次被自身消费导致递归）
        self._emit_updates: bool = True
        self._auto_subscribe = auto_subscribe
        self._subscribed: bool = False

    # ---- 订阅生命周期 ----
    def start(self) -> None:
        """注册事件订阅（幂等）。"""
        if self._subscribed:
            return
        if not self._auto_subscribe:
            return
        # 订阅能力层动作事件
        self._bus.on(EventType.BROWSER_NAVIGATE, self._on_browser_event)
        self._bus.on(EventType.BROWSER_CLICK, self._on_browser_event)
        self._bus.on(EventType.BROWSER_TYPE, self._on_browser_event)
        self._bus.on(EventType.BROWSER_SNAPSHOT, self._on_browser_snapshot)
        self._bus.on(EventType.DESKTOP_FOCUS, self._on_desktop_event)
        self._bus.on(EventType.DESKTOP_CLICK, self._on_desktop_event)
        self._bus.on(EventType.ACTION_COMPLETED, self._on_action_completed)
        self._bus.on(EventType.ACTION_FAILED, self._on_action_failed)
        self._bus.on(EventType.TASK_CREATED, self._on_task_created)
        self._bus.on(EventType.TASK_COMPLETED, self._on_task_terminal)
        self._bus.on(EventType.TASK_FAILED, self._on_task_terminal)
        self._subscribed = True

    def stop(self) -> None:
        """取消订阅（测试用）。"""
        if not self._subscribed:
            return
        for et, h in self._handlers():
            self._bus.off(et, h)
        self._subscribed = False

    def _handlers(self):
        return [
            (EventType.BROWSER_NAVIGATE, self._on_browser_event),
            (EventType.BROWSER_CLICK, self._on_browser_event),
            (EventType.BROWSER_TYPE, self._on_browser_event),
            (EventType.BROWSER_SNAPSHOT, self._on_browser_snapshot),
            (EventType.DESKTOP_FOCUS, self._on_desktop_event),
            (EventType.DESKTOP_CLICK, self._on_desktop_event),
            (EventType.ACTION_COMPLETED, self._on_action_completed),
            (EventType.ACTION_FAILED, self._on_action_failed),
            (EventType.TASK_CREATED, self._on_task_created),
            (EventType.TASK_COMPLETED, self._on_task_terminal),
            (EventType.TASK_FAILED, self._on_task_terminal),
        ]

    # ---- 查询接口（设计文档第 4 节）----
    def snapshot(self) -> Dict[str, Any]:
        return self._state.snapshot()

    def state(self) -> WorldState:
        """返回当前 WorldState 对象（只读访问）。"""
        return self._state

    def restore(self, snapshot: Dict[str, Any]) -> None:
        self._state = WorldState.model_validate(snapshot)

    def diff(self, previous: Dict[str, Any]) -> Dict[str, Any]:
        prev = WorldState.model_validate(previous)
        return self._state.diff(prev)

    # ---- 显式 apply（设计文档第 4 节 apply(event) 接口）----
    async def apply(self, event: Event) -> Optional[Dict[str, Any]]:
        """根据事件更新世界状态，返回变更 diff（无变更返回 None）。

        此方法既是公共接口，也作为内部 handler 被总线调用（总线派发时也是 apply）。
        状态变更后 emit world.updated（抑制递归）。
        """
        prev = self._state
        new_state = self._apply_event(self._state, event)
        if new_state is None:
            return None
        self._state = new_state
        changed = new_state.diff(prev)
        if changed and self._emit_updates:
            # emit world.updated 让其他订阅者感知变更
            self._emit_updates = False
            try:
                await self._bus.emit(
                    Event(
                        type=EventType.WORLD_UPDATED,
                        source="world",
                        task_id=event.task_id,
                        run_id=event.run_id,
                        payload={"changed": list(changed.keys())},
                    )
                )
            finally:
                self._emit_updates = True
        return changed

    # ---- 事件→状态映射（纯函数，便于单测）----
    def _apply_event(self, state: WorldState, event: Event) -> Optional[WorldState]:
        et = event.type
        p = event.payload

        if et == EventType.BROWSER_NAVIGATE:
            url = p.get("url")
            title = p.get("title")
            if url is None and title is None:
                return None
            return state.with_browser(url=url, title=title)

        if et in (EventType.BROWSER_CLICK, EventType.BROWSER_TYPE):
            # 点击/输入更新最近动作
            return state.with_action(
                {"type": et, "selector": p.get("selector"), "text": p.get("text")}
            )

        if et == EventType.BROWSER_SNAPSHOT:
            return state.with_observation(
                {"type": "browser_snapshot", "url": p.get("url"), "title": p.get("title")}
            )

        if et == EventType.DESKTOP_FOCUS:
            win = p.get("window") or p.get("window_id")
            if win is None:
                return None
            return state.with_desktop(active_window=win)

        if et == EventType.DESKTOP_CLICK:
            return state.with_action(
                {"type": et, "target": p.get("target")}
            )

        if et == EventType.ACTION_COMPLETED:
            # 工具/能力执行完成：把结果作为观察记录 + 命中变量提取
            new_state = state.with_observation(
                {
                    "type": "action_completed",
                    "source": p.get("source"),
                    "tool": p.get("tool"),
                    "result": _truncate(p.get("result")),
                }
            )
            var = p.get("variable")
            if var:
                new_state = new_state.with_variable(var, p.get("result"))
            return new_state

        if et == EventType.ACTION_FAILED:
            return state.with_observation(
                {
                    "type": "action_failed",
                    "source": p.get("source"),
                    "tool": p.get("tool"),
                    "error": p.get("error"),
                }
            )

        if et == EventType.TASK_CREATED:
            return state.with_task_context(
                {
                    "goal": p.get("goal"),
                    "success_criteria": p.get("success_criteria", []),
                    "status": "running",
                    "task_id": event.task_id,
                    "run_id": event.run_id,
                }
            )

        if et in (EventType.TASK_COMPLETED, EventType.TASK_FAILED):
            return state.with_task_context(
                {"status": p.get("status"), "iterations": p.get("iterations")}
            )

        return None

    # ---- 内部 handler（包装 apply，吞掉总线异常）----
    async def _on_browser_event(self, event: Event) -> None:
        await self.apply(event)

    async def _on_browser_snapshot(self, event: Event) -> None:
        await self.apply(event)

    async def _on_desktop_event(self, event: Event) -> None:
        await self.apply(event)

    async def _on_action_completed(self, event: Event) -> None:
        await self.apply(event)

    async def _on_action_failed(self, event: Event) -> None:
        await self.apply(event)

    async def _on_task_created(self, event: Event) -> None:
        await self.apply(event)

    async def _on_task_terminal(self, event: Event) -> None:
        await self.apply(event)


def _truncate(value: Any, limit: int = 500) -> Any:
    """截断超长结果，避免世界状态膨胀。"""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "...(截断)"
    return value
