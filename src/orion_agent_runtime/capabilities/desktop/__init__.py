"""Desktop Capability 子包。

设计文档第 4 节 capabilities/desktop：
  Windows UIA / macOS Accessibility / Linux AT-SPI，负责桌面窗口操作。
  接口：focus(window_id) / click(target) / type(text) / find(control) / snapshot()

本次（里程碑 A+B）范围：仅抽象接口 + Mock 实现。
真实 UIA 留待里程碑 C（设计文档第 10 节：C 桌面与反思）。

设计文档第 11 节红线："不要只靠截图做桌面自动化，优先使用无障碍树，截图作为兜底"。
真实实现时应优先走 accessibility tree（UIA/AX/AT-SPI），snapshot 返回无障碍树。
"""

from orion_agent_runtime.capabilities.desktop.capability import (
    DesktopCapability,
    create_desktop_capability,
)
from orion_agent_runtime.capabilities.desktop.mock import MockDesktopCapability

__all__ = ["DesktopCapability", "MockDesktopCapability", "create_desktop_capability"]
