"""事件总线子系统（V2 架构基石）。

模块间唯一通信通道，支持事件路由、订阅、回放审计。
设计原则：事件驱动优先——模块之间尽量通过 Event 交互，减少直接函数耦合。
"""

from orion_agent_runtime.bus.event import Event, EventType, make_event
from orion_agent_runtime.bus.event_bus import (
    EventBus,
    get_event_bus,
    reset_event_bus,
)

__all__ = [
    "Event",
    "EventType",
    "make_event",
    "EventBus",
    "get_event_bus",
    "reset_event_bus",
]
