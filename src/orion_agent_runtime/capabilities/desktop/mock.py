"""MockDesktopCapability —— 桌面能力的内存模拟实现。

用途：
- 单元测试（确定性、无副作用）
- 无桌面 UIA/pywinauto 环境时的回退

模拟语义：
- 维护虚拟窗口列表和活动窗口
- focus/click/type 基于内存状态返回确定性结果
- snapshot 返回当前虚拟桌面状态
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from orion_agent_runtime.capabilities.base import Capability, CapabilityResult


class MockDesktopCapability(Capability):
    """内存模拟的桌面能力。"""

    name = "desktop"

    def __init__(self, bus: Optional[Any] = None) -> None:
        super().__init__(bus=bus)
        self.windows: List[str] = []
        self.active_window: Optional[str] = None
        self.clicks: Dict[str, int] = {}
        self.typed: List[str] = []

    async def open(self, **kwargs: Any) -> CapabilityResult:
        self._opened = True
        return CapabilityResult.ok(platform="mock", windows=self.windows)

    async def focus(self, window_id: str, **kwargs: Any) -> CapabilityResult:
        if window_id not in self.windows:
            self.windows.append(window_id)
        self.active_window = window_id
        payload = {"window": window_id}
        await self._emit("desktop.focus", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(window=window_id)

    async def click(self, target: str, **kwargs: Any) -> CapabilityResult:
        self.clicks[target] = self.clicks.get(target, 0) + 1
        payload = {"target": target}
        await self._emit("desktop.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(target=target, click_count=self.clicks[target])

    async def type(self, text: str, **kwargs: Any) -> CapabilityResult:
        self.typed.append(text)
        payload = {"text": text}
        await self._emit("desktop.type", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(text=text)

    async def find(self, query: str, **kwargs: Any) -> CapabilityResult:
        # 模拟查找：匹配包含 query 的窗口名
        matches = [w for w in self.windows if query.lower() in w.lower()]
        return CapabilityResult.ok(query=query, matches=matches)

    async def snapshot(self, **kwargs: Any) -> CapabilityResult:
        payload = {
            "active_window": self.active_window,
            "windows": list(self.windows),
        }
        await self._emit("desktop.snapshot", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def close(self) -> CapabilityResult:
        self._opened = False
        self.windows.clear()
        self.active_window = None
        return CapabilityResult.ok()
