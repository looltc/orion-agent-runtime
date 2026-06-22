"""DesktopCapability 抽象接口（占位，真实 UIA 留里程碑 C）。

设计文档第 4 节 capabilities/desktop：
  Windows UIA / macOS Accessibility / Linux AT-SPI。

本次范围（里程碑 B）：仅定义抽象方法 + 工厂选择 mock。
真实实现时需 pywinauto（Windows）/ pyobjc（macOS）/ atspi（Linux）。

接口（设计文档第 4 节）：
  focus(window_id) / click(target) / type(text) / find(control) / snapshot()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from orion_agent_runtime.capabilities.base import (
    Capability,
    CapabilityError,
    CapabilityResult,
)
from orion_agent_runtime.capabilities.desktop.mock import MockDesktopCapability


class DesktopCapability(Capability):
    """桌面自动化能力（抽象占位）。

    真实实现（里程碑 C）应：
    - 优先使用无障碍树（UIA/AX/AT-SPI），不靠截图
    - 截图仅作为兜底
    - 按平台适配（Windows/macOS/Linux）
    """

    name = "desktop"

    async def open(self, **kwargs: Any) -> CapabilityResult:
        """初始化桌面连接（连接 OS 无障碍框架）。"""
        # 占位：真实实现按平台连接 UIA/AX/AT-SPI
        self._opened = True
        return CapabilityResult.ok(platform="placeholder", status="placeholder_no_real_driver")

    async def focus(self, window_id: str, **kwargs: Any) -> CapabilityResult:
        """聚焦指定窗口（desktop.focus 事件）。"""
        # 占位
        payload = {"window": window_id}
        await self._emit("desktop.focus", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(window=window_id)

    async def click(self, target: str, **kwargs: Any) -> CapabilityResult:
        """点击桌面控件（desktop.click 事件）。"""
        payload = {"target": target}
        await self._emit("desktop.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(target=target)

    async def type(self, text: str, **kwargs: Any) -> CapabilityResult:
        """输入文本（desktop.type 事件）。"""
        payload = {"text": text}
        await self._emit("desktop.type", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(text=text)

    async def find(self, query: str, **kwargs: Any) -> CapabilityResult:
        """查找桌面控件（返回匹配列表）。"""
        return CapabilityResult.ok(query=query, matches=[])

    async def snapshot(self, **kwargs: Any) -> CapabilityResult:
        """采集桌面状态快照（无障碍树优先，截图兜底）。"""
        payload = {"active_window": None, "windows": []}
        await self._emit("desktop.snapshot", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)


def create_desktop_capability(bus: Optional[Any] = None, **kwargs: Any) -> Capability:
    """工厂：当前默认返回 Mock（真实 UIA 留里程碑 C）。"""
    # 未来可按 ORION_DESKTOP_MODE=real|mock 选择
    return MockDesktopCapability(bus=bus)
