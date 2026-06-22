"""Browser Capability 子包。

设计文档第 4 节 capabilities/browser：Playwright 驱动，
负责网页导航、点击、输入、下载、DOM 采集、截图。

两种实现：
- BrowserCapability：真实 Playwright（chromium 优先），需 ORION_BROWSER_MODE=real
- MockBrowserCapability：内存模拟，无浏览器环境/测试时回退（默认）

完整 Browser Use Agent 接口：
- 生命周期：open / close
- 导航：navigate / go_back / go_forward / new_tab / switch_tab / close_tab
- 交互：click / type / press_key / select_option / hover / scroll
- 信息：snapshot / get_page_text / get_element_text / extract_dom / screenshot
- 高级：wait_for / evaluate_js
"""

from orion_agent_runtime.capabilities.browser.capability import (
    BrowserCapability,
    create_browser_capability,
)

__all__ = ["BrowserCapability", "create_browser_capability"]
