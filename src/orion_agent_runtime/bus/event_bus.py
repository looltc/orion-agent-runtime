"""EventBus —— 模块间唯一通信通道（asyncio 原生）。

设计原则（设计文档第 4 节 bus 模块）：
- 内存事件总线 + 持久化事件流（支持 run_id 级回放审计）
- 支持事件路由、重放、订阅、回放审计

接口（设计文档第 4 节）：
- emit(event)
- on(event_type, handler)
- replay(run_id)
- ack(event_id)

关键约束：
- handler 必须是 async（事件驱动 Runtime 全异步）
- handler 异常被隔离，不阻塞总线（记录到 AUDIT 但不向上抛）
- 支持 "*" 通配订阅所有事件
- 持久化按 run_id 分文件，支持 replay 重放整个 run
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from orion_agent_runtime.bus.event import Event
from orion_agent_runtime.config import get_config

logger = logging.getLogger(__name__)

# 事件 handler 的类型：接收 Event，返回 Awaitable
EventHandler = Callable[[Event], Awaitable[None]]

# 通配符：订阅所有事件类型
WILDCARD = "*"


class EventBus:
    """asyncio 原生事件总线 + 持久化事件流。

    线程模型：单事件循环内运行；emit 是 async，并发派发给所有匹配 handler。
    持久化：每个 run_id 一个 JSONL 文件，append-only，供 replay。
    """

    def __init__(self, event_store_dir: Optional[Path] = None) -> None:
        # event_type -> list[handler]；WILDCARD 单独存
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._wildcard_handlers: List[EventHandler] = []
        # 默认走 config.event_store_dir；测试可注入临时路径
        self._store_dir = event_store_dir
        # 已派发事件的 ack 集合（event_id -> bool）；用于幂等回放消费
        self._acked: set[str] = set()

    # ---- 订阅 ----
    def on(self, event_type: str, handler: EventHandler) -> None:
        """注册异步 handler。event_type="*" 订阅所有事件。"""
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(
                f"handler must be async (coroutine function): {handler!r}"
            )
        if event_type == WILDCARD:
            self._wildcard_handlers.append(handler)
        else:
            self._handlers.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: EventHandler) -> None:
        """取消注册（测试与清理用）。"""
        if event_type == WILDCARD:
            if handler in self._wildcard_handlers:
                self._wildcard_handlers.remove(handler)
        else:
            lst = self._handlers.get(event_type, [])
            if handler in lst:
                lst.remove(handler)

    def clear(self) -> None:
        """清空所有订阅（测试用）。"""
        self._handlers.clear()
        self._wildcard_handlers.clear()
        self._acked.clear()

    # ---- 发布 ----
    async def emit(self, event: Event) -> str:
        """派发事件给所有匹配 handler + 持久化。返回 event.id。

        handler 异常被隔离：记日志但不向上抛，保证总线不因单个 handler 崩溃。
        持久化失败也不阻塞派发（只记日志）。
        """
        # 1. 持久化（先落盘，保证可回放；失败不阻塞派发）
        try:
            self._persist(event)
        except Exception as e:  # pragma: no cover - I/O 容错
            logger.warning("event persist failed for %s: %s", event.id, e)

        # 2. 收集匹配 handler（精确 + 通配）
        matched = list(self._handlers.get(event.type, []))
        matched.extend(self._wildcard_handlers)

        # 3. 并发派发，每个 handler 异常隔离
        if matched:
            results = await asyncio.gather(
                *(self._safe_call(h, event) for h in matched),
                return_exceptions=True,
            )
            for h, r in zip(matched, results):
                if isinstance(r, Exception):
                    logger.warning(
                        "event handler %s raised on event %s: %s",
                        getattr(h, "__name__", h),
                        event.id,
                        r,
                    )
        return event.id

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        await handler(event)

    # ---- ack（幂等消费支持）----
    def ack(self, event_id: str) -> None:
        """标记事件已被某消费者处理（幂等消费支持）。"""
        self._acked.add(event_id)

    def is_acked(self, event_id: str) -> bool:
        return event_id in self._acked

    # ---- 持久化与回放 ----
    def _store_root(self) -> Path:
        if self._store_dir is not None:
            return self._store_dir
        return Path(get_config().event_store_dir)

    def _run_file(self, run_id: Optional[str]) -> Path:
        root = self._store_root()
        root.mkdir(parents=True, exist_ok=True)
        # 无 run_id 的事件归入 _no_run.jsonl
        return root / f"{run_id or '_no_run'}.jsonl"

    def _persist(self, event: Event) -> None:
        path = self._run_file(event.run_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    async def replay(self, run_id: str) -> "List[Event]":
        """重放某个 run 的所有持久化事件（按时间顺序）。

        返回事件列表（不重新派发）。消费方可自行决定如何应用。
        """
        path = self._run_file(run_id)
        if not path.exists():
            return []
        events: List[Event] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.model_validate_json(line))
                except Exception as e:  # pragma: no cover - 容错
                    logger.warning("skip malformed event line: %s", e)
        # 按 timestamp 稳定排序（落盘已是 append 顺序，通常已有序）
        events.sort(key=lambda e: e.timestamp)
        return events

    def replay_sync(self, run_id: str) -> List[Event]:
        """replay 的同步版本（非事件循环上下文使用，如 CLI 审计）。"""
        path = self._run_file(run_id)
        if not path.exists():
            return []
        events: List[Event] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.model_validate_json(line))
                except Exception:
                    continue
        events.sort(key=lambda e: e.timestamp)
        return events


# ---- 进程级单例（与 V1 的 MemoryManager 单例模式保持一致）----
_default_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 单例。"""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def reset_event_bus() -> None:
    """重置全局 EventBus（测试用：清空订阅 + 重建实例）。"""
    global _default_bus
    _default_bus = None


def export_events_jsonl(run_id: str, out_path: Optional[Path] = None) -> Path:
    """导出某 run 的事件流为独立 JSONL 文件（审计/归档用）。"""
    events = get_event_bus().replay_sync(run_id)
    target = out_path or (Path(get_config().runtime_state_dir) / f"events_{run_id}.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        for e in events:
            f.write(e.model_dump_json() + "\n")
    return target
