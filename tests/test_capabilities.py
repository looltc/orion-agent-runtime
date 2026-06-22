"""P0/P1: Capability 抽象 + Browser/Desktop Mock 测试。

核心断言（设计文档第 8 节验收点）：
- 浏览器能力可独立运行：导航/点击/输入/截图/DOM（Mock 验证协议正确性）
- 桌面能力：窗口聚焦/控件查找/点击/输入/截图
- Mock 可完成协议：open/close/snapshot 正确
- CapabilityResult 标准化结构
- CapabilityRegistry 注册/注销/查询
- 动作 emit 事件（事件驱动闭环）

设计文档红线："Planner 不直连底层驱动——对底层驱动的调用必须经过 Capability 层"。
"""

import asyncio
import pytest

from orion_agent_runtime.bus import EventBus, EventType, make_event
from orion_agent_runtime.capabilities.base import (
    Capability,
    CapabilityError,
    CapabilityRegistry,
    CapabilityResult,
    get_registry,
    reset_registry,
)
from orion_agent_runtime.capabilities.browser.mock import MockBrowserCapability
from orion_agent_runtime.capabilities.desktop.mock import MockDesktopCapability


# ---------- CapabilityResult ----------

def test_result_ok():
    r = CapabilityResult.ok(url="https://x.com", title="X")
    assert r.success is True
    assert r.error is None
    assert r.data["url"] == "https://x.com"


def test_result_fail():
    r = CapabilityResult.fail("not opened")
    assert r.success is False
    assert r.error == "not opened"


# ---------- CapabilityRegistry ----------

def test_registry_register_and_get():
    cap = MockBrowserCapability()
    reg = CapabilityRegistry()
    reg.register(cap)
    assert reg.has("browser")
    assert reg.get("browser") is cap


def test_registry_get_unknown_raises():
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityError):
        reg.get("nonexistent")


def test_registry_list():
    reg = CapabilityRegistry()
    reg.register(MockBrowserCapability())
    reg.register(MockDesktopCapability())
    assert sorted(reg.list()) == ["browser", "desktop"]


def test_registry_unregister():
    cap = MockBrowserCapability()
    reg = CapabilityRegistry()
    reg.register(cap)
    reg.unregister("browser")
    assert not reg.has("browser")


def test_registry_close_all(tmp_path):
    reg = CapabilityRegistry()
    reg.register(MockBrowserCapability())
    reg.register(MockDesktopCapability())
    asyncio.run(reg.close_all())
    assert reg.list() == []


# ---------- MockBrowserCapability ----------

def test_browser_open_and_close():
    cap = MockBrowserCapability()
    r = asyncio.run(cap.open(url="https://example.com"))
    assert r.success
    assert r.data["url"] == "https://example.com"
    assert cap.opened
    r2 = asyncio.run(cap.close())
    assert not cap.opened


def test_browser_navigate():
    cap = MockBrowserCapability()
    r = asyncio.run(cap.navigate("https://example.com"))
    assert r.success
    assert r.data["url"] == "https://example.com"
    assert cap.current_url == "https://example.com"
    assert cap.current_title is not None


def test_browser_click():
    cap = MockBrowserCapability()
    asyncio.run(cap.open(url="https://x.com"))
    r = asyncio.run(cap.click("#btn"))
    assert r.success
    assert r.data["selector"] == "#btn"
    assert cap.clicks["#btn"] == 1
    # 再点一次
    asyncio.run(cap.click("#btn"))
    assert cap.clicks["#btn"] == 2


def test_browser_type():
    cap = MockBrowserCapability()
    asyncio.run(cap.open(url="https://x.com"))
    r = asyncio.run(cap.type("#q", "hello"))
    assert r.success
    assert cap.inputs["#q"] == "hello"


def test_browser_snapshot():
    cap = MockBrowserCapability()
    asyncio.run(cap.open(url="https://x.com"))
    r = asyncio.run(cap.snapshot())
    assert r.success
    assert r.data["url"] == "https://x.com"


def test_browser_extract_dom():
    cap = MockBrowserCapability()
    asyncio.run(cap.open(url="https://x.com"))
    r = asyncio.run(cap.extract_dom())
    assert r.success
    assert "<html>" in r.data["html"]


def test_browser_screenshot():
    cap = MockBrowserCapability()
    asyncio.run(cap.open(url="https://x.com"))
    r = asyncio.run(cap.screenshot())
    assert r.success
    assert "bytes_len" in r.data


# ---------- MockDesktopCapability ----------

def test_desktop_open_and_close():
    cap = MockDesktopCapability()
    r = asyncio.run(cap.open())
    assert r.success
    assert cap.opened
    asyncio.run(cap.close())
    assert not cap.opened


def test_desktop_focus():
    cap = MockDesktopCapability()
    asyncio.run(cap.focus("Notepad"))
    assert cap.active_window == "Notepad"
    assert "Notepad" in cap.windows


def test_desktop_click():
    cap = MockDesktopCapability()
    asyncio.run(cap.focus("Notepad"))
    r = asyncio.run(cap.click("File->Save"))
    assert r.success
    assert cap.clicks["File->Save"] == 1


def test_desktop_type():
    cap = MockDesktopCapability()
    r = asyncio.run(cap.type("Hello"))
    assert r.success
    assert "Hello" in cap.typed


def test_desktop_find():
    cap = MockDesktopCapability()
    asyncio.run(cap.focus("Notepad"))
    asyncio.run(cap.focus("Chrome"))
    r = asyncio.run(cap.find("notepad"))
    assert r.success
    assert "Notepad" in r.data["matches"]


def test_desktop_snapshot():
    cap = MockDesktopCapability()
    asyncio.run(cap.focus("Notepad"))
    asyncio.run(cap.focus("Chrome"))
    r = asyncio.run(cap.snapshot())
    assert r.success
    assert r.data["active_window"] == "Chrome"
    assert len(r.data["windows"]) == 2


# ---------- 事件发射（事件驱动闭环） ----------

def test_browser_emits_events(tmp_path):
    """浏览器动作应 emit browser.* 事件到总线。"""
    bus = EventBus(event_store_dir=tmp_path)
    cap = MockBrowserCapability(bus=bus)
    received = []

    async def collect(ev):
        received.append(ev)

    bus.on(EventType.BROWSER_NAVIGATE, collect)
    bus.on(EventType.BROWSER_CLICK, collect)

    asyncio.run(cap.navigate("https://x.com"))
    asyncio.run(cap.click("#btn"))
    assert len(received) == 2
    assert received[0].type == EventType.BROWSER_NAVIGATE
    assert received[1].type == EventType.BROWSER_CLICK


def test_desktop_emits_events(tmp_path):
    """桌面动作应 emit desktop.* 事件到总线。"""
    bus = EventBus(event_store_dir=tmp_path)
    cap = MockDesktopCapability(bus=bus)
    received = []

    async def collect(ev):
        received.append(ev)

    bus.on(EventType.DESKTOP_FOCUS, collect)
    bus.on(EventType.DESKTOP_CLICK, collect)

    asyncio.run(cap.focus("Notepad"))
    asyncio.run(cap.click("File"))
    assert len(received) == 2
    assert received[0].payload["window"] == "Notepad"


# ---------- 工厂函数 ----------

def test_create_browser_capability_default_mock():
    """ORION_BROWSER_MODE 默认 mock，应返回 MockBrowserCapability。"""
    from orion_agent_runtime.capabilities.browser.capability import create_browser_capability
    cap = create_browser_capability()
    assert isinstance(cap, MockBrowserCapability)


def test_create_desktop_capability_returns_mock():
    from orion_agent_runtime.capabilities.desktop.capability import create_desktop_capability
    cap = create_desktop_capability()
    assert isinstance(cap, MockDesktopCapability)


# ---------- 全局 registry 单例 ----------

def test_global_registry_singleton():
    reset_registry()
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
    reset_registry()  # 清理


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
