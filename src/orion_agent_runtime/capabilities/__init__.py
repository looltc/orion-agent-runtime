"""能力层（V2 架构）。

设计文档第 3/4 节：Capability Layer 统一 Browser/Desktop/Terminal/File/API。
设计原则（红线）："Planner 不直接依赖 Playwright / UIA 细节"——
对底层驱动的调用必须经过 Capability 层。

每个 Capability 是一个独立 worker，输出统一的 CapabilityResult。
所有动作可通过 EventBus 发出对应事件（browser.*/desktop.*/terminal.* 等）。
"""

from orion_agent_runtime.capabilities.base import (
    Capability,
    CapabilityError,
    CapabilityRegistry,
    CapabilityResult,
    get_registry,
)

__all__ = [
    "Capability",
    "CapabilityResult",
    "CapabilityError",
    "CapabilityRegistry",
    "get_registry",
]
