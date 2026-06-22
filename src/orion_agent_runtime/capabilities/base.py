"""Capability 抽象基类（V2 架构基石）。

设计文档第 4 节 capabilities/* 模块 + 第 11 节红线：
  "不要让 Planner 直接操作 Playwright 或 UIA，
   对底层驱动的调用必须经过 Capability 层。"

统一协议：
- 所有 Capability 返回 CapabilityResult（标准化结构，便于事件 payload）
- 所有动作为 async（事件驱动 Runtime 全异步）
- Capability 可选接入 EventBus，把动作转为事件

抽象方法（最小契约，各子类按域扩展）：
- async open(...)：打开/启动会话（浏览器开页、桌面聚焦等）
- async snapshot()：采集当前状态（DOM/无障碍树/截图等）
- async close()：释放资源
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CapabilityError(Exception):
    """Capability 执行错误。"""


class CapabilityResult(BaseModel):
    """统一的 Capability 动作结果（所有能力层动作的标准返回）。

    success=False 时 error 必填；data 携带结构化结果供事件 payload 直接使用。
    """

    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def ok(cls, **data: Any) -> "CapabilityResult":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, **data: Any) -> "CapabilityResult":
        return cls(success=False, error=error, data=data)


class Capability(ABC):
    """能力层抽象基类。

    子类必须实现：name（能力名）、open、snapshot、close。
    动作方法（click/type 等）由各子类按域定义，但统一返回 CapabilityResult。

    接入事件总线（可选）：
      构造时传入 bus，则每个动作完成后自动 emit 对应事件。
      不传 bus 时为纯能力调用，不发事件（便于单测）。
    """

    # 能力名（子类覆盖）：browser/desktop/terminal/filesystem/api
    name: str = "capability"

    def __init__(self, bus: Optional[Any] = None) -> None:
        self._bus = bus
        self._opened: bool = False

    @property
    def opened(self) -> bool:
        return self._opened

    # ---- 生命周期 ----
    @abstractmethod
    async def open(self, **kwargs: Any) -> CapabilityResult:
        """打开/初始化会话。"""

    @abstractmethod
    async def snapshot(self) -> CapabilityResult:
        """采集当前状态快照。"""

    async def close(self) -> CapabilityResult:
        """释放资源（默认实现标记关闭，子类可覆盖）。"""
        self._opened = False
        return CapabilityResult.ok()

    async def __aenter__(self) -> "Capability":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---- 事件发射 helper（子类调用）----
    async def _emit(self, event_type: str, payload: Dict[str, Any],
                    *, task_id: Optional[str] = None, run_id: Optional[str] = None) -> None:
        """把动作结果转为事件发到总线（bus 为空时静默跳过）。"""
        if self._bus is None:
            return
        # 延迟导入避免循环依赖
        from orion_agent_runtime.bus.event import Event

        await self._bus.emit(
            Event(
                type=event_type,
                source=self.name,
                task_id=task_id,
                run_id=run_id,
                payload=payload,
            )
        )


# ---- 能力注册中心（与 tools/registry 解耦：tools 是 LLM 可调函数，capabilities 是底层驱动）----
class CapabilityRegistry:
    """能力注册中心：按 name 索引已实例化的 Capability。

    与 tools/registry 区别：
    - tools/registry：面向 LLM 的工具函数（add/mul/knowledge_search...），同步 handler
    - capabilities：面向底层驱动（Browser/Desktop...），async，包装为 Capability 对象

    AgentRuntime 通过 registry 取能力，避免硬编码具体实现。
    """

    def __init__(self) -> None:
        self._caps: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if not capability.name:
            raise ValueError("capability.name must be set")
        self._caps[capability.name] = capability

    def unregister(self, name: str) -> None:
        self._caps.pop(name, None)

    def get(self, name: str) -> Capability:
        if name not in self._caps:
            raise CapabilityError(f"capability not registered: {name}")
        return self._caps[name]

    def has(self, name: str) -> bool:
        return name in self._caps

    def list(self) -> List[str]:
        return list(self._caps.keys())

    async def close_all(self) -> None:
        """关闭所有已注册能力（优雅退出）。"""
        for cap in self._caps.values():
            try:
                await cap.close()
            except Exception:
                pass
        self._caps.clear()


# 进程级单例（与 EventBus/MemoryManager 单例模式保持一致）
_default_registry: Optional[CapabilityRegistry] = None


def get_registry() -> CapabilityRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = CapabilityRegistry()
    return _default_registry


def reset_registry() -> None:
    """重置全局 registry（测试用）。"""
    global _default_registry
    _default_registry = None
