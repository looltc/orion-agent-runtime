"""Browser Tools 测试 —— 验证浏览器工具桥接层。

核心断言：
- 所有 browser_* 工具已注册到 _TOOL_REGISTRY
- Mock 模式下每个工具可正确调用浏览器能力并返回字符串结果
- 工具调用触发对应的 browser.* 事件
- V2 完整流程：AgentRuntime + MockBrowserCapability + mock LLM 可完成简单任务

设计文档红线："Planner 不直连底层驱动——对底层驱动的调用必须经过 Capability 层"。
"""

import asyncio

import pytest

from orion_agent_runtime.bus import EventBus, EventType, make_event
from orion_agent_runtime.capabilities.base import (
    CapabilityRegistry,
    reset_registry,
)
from orion_agent_runtime.capabilities.browser.mock import MockBrowserCapability
from orion_agent_runtime.tools import registry as tool_registry


# ---- 所有 browser_* 工具名 ----

EXPECTED_BROWSER_TOOLS = {
    "browser_open",
    "browser_navigate",
    "browser_go_back",
    "browser_go_forward",
    "browser_new_tab",
    "browser_switch_tab",
    "browser_close_tab",
    "browser_click",
    "browser_type",
    "browser_press_key",
    "browser_select_option",
    "browser_hover",
    "browser_scroll",
    "browser_snapshot",
    "browser_get_links",
    "browser_get_page_text",
    "browser_screenshot",
    "browser_wait",
    "browser_evaluate_js",
    "browser_close",
}


# ---- fixture：注册 MockBrowserCapability 到全局 registry ----

@pytest.fixture
def mock_browser():
    """注册一个 MockBrowserCapability 到全局 CapabilityRegistry。"""
    reset_registry()
    registry = CapabilityRegistry()
    cap = MockBrowserCapability()
    registry.register(cap)
    # 替换全局单例
    import orion_agent_runtime.capabilities.base as base
    base._default_registry = registry
    yield cap
    reset_registry()


# ---- 工具注册验证 ----

def test_all_browser_tools_registered():
    """所有 browser_* 工具应在工具导入后注册到 _TOOL_REGISTRY。"""
    # 触发 tools 包导入（注册 browser_tools）
    import orion_agent_runtime.tools  # noqa: F401

    registered = set(tool_registry._TOOL_REGISTRY.keys())
    missing = EXPECTED_BROWSER_TOOLS - registered
    assert not missing, f"Missing browser tools: {missing}"


def test_browser_tools_have_correct_origin():
    """所有 browser_* 工具应为 local origin。"""
    import orion_agent_runtime.tools  # noqa: F401

    for name in EXPECTED_BROWSER_TOOLS:
        spec = tool_registry.get_tool(name)
        assert spec.origin == "local", f"{name} should be local origin"


def test_browser_tools_have_args_model():
    """所有 browser_* 工具应有 args_model（用于参数校验）。"""
    import orion_agent_runtime.tools  # noqa: F401

    for name in EXPECTED_BROWSER_TOOLS:
        spec = tool_registry.get_tool(name)
        assert spec.args_model is not None, f"{name} should have args_model"
        assert spec.handler is not None, f"{name} should have handler"


# ---- 工具调用（Mock 模式）----

def test_browser_open_tool(mock_browser):
    """browser_open 工具应启动浏览器。"""
    from orion_agent_runtime.tools.browser_tools import browser_open

    result = asyncio.run(browser_open())
    assert "opened" in result.lower()


def test_browser_open_with_url_tool(mock_browser):
    """browser_open 带 URL 应自动导航。"""
    from orion_agent_runtime.tools.browser_tools import browser_open

    result = asyncio.run(browser_open(url="https://example.com"))
    assert "example.com" in result


def test_browser_navigate_tool(mock_browser):
    """browser_navigate 工具应导航到 URL。"""
    from orion_agent_runtime.tools.browser_tools import browser_navigate

    result = asyncio.run(browser_navigate(url="https://example.com"))
    assert "example.com" in result
    assert "Title" in result
    assert mock_browser.current_url == "https://example.com"


def test_browser_click_tool(mock_browser):
    """browser_click 工具应点击元素。"""
    from orion_agent_runtime.tools.browser_tools import browser_click

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_click(selector="#btn"))
    assert "Clicked" in result
    assert "#btn" in result
    assert mock_browser.clicks["#btn"] == 1


def test_browser_type_tool(mock_browser):
    """browser_type 工具应输入文本。"""
    from orion_agent_runtime.tools.browser_tools import browser_type

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_type(selector="#q", text="hello world"))
    assert "Typed" in result
    assert "hello world" in result
    assert mock_browser.inputs["#q"] == "hello world"


def test_browser_press_key_tool(mock_browser):
    """browser_press_key 工具应按键。"""
    from orion_agent_runtime.tools.browser_tools import browser_press_key

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_press_key(key="Enter"))
    assert "Enter" in result


def test_browser_select_option_tool(mock_browser):
    """browser_select_option 工具应选择下拉选项。"""
    from orion_agent_runtime.tools.browser_tools import browser_select_option

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_select_option(selector="#lang", value="zh"))
    assert "Selected" in result
    assert "zh" in result


def test_browser_hover_tool(mock_browser):
    """browser_hover 工具应悬停。"""
    from orion_agent_runtime.tools.browser_tools import browser_hover

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_hover(selector=".menu"))
    assert "Hovered" in result
    assert ".menu" in result


def test_browser_scroll_tool(mock_browser):
    """browser_scroll 工具应滚动页面。"""
    from orion_agent_runtime.tools.browser_tools import browser_scroll

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_scroll(direction="down", amount=300))
    assert "Scrolled" in result
    assert "down" in result


def test_browser_snapshot_tool(mock_browser):
    """browser_snapshot 工具应返回页面结构化摘要。"""
    from orion_agent_runtime.tools.browser_tools import browser_snapshot

    asyncio.run(mock_browser.open(url="https://example.com"))
    result = asyncio.run(browser_snapshot())
    assert "[Page]" in result
    assert "example.com" in result
    # 应包含交互元素
    assert "[Links]" in result or "[Inputs]" in result or "[Buttons]" in result


def test_browser_get_page_text_tool(mock_browser):
    """browser_get_page_text 工具应返回纯文本。"""
    from orion_agent_runtime.tools.browser_tools import browser_get_page_text

    asyncio.run(mock_browser.open(url="https://example.com"))
    result = asyncio.run(browser_get_page_text())
    # Mock 模式下应返回去标签的文本
    assert "<html>" not in result
    assert len(result) >= 0


def test_browser_screenshot_tool(mock_browser):
    """browser_screenshot 工具应截图。"""
    from orion_agent_runtime.tools.browser_tools import browser_screenshot

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_screenshot())
    assert "Screenshot" in result


def test_browser_wait_tool(mock_browser):
    """browser_wait 工具应等待元素。"""
    from orion_agent_runtime.tools.browser_tools import browser_wait

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_wait(selector="#btn", state="visible", timeout=5000))
    assert "visible" in result.lower()


def test_browser_evaluate_js_tool(mock_browser):
    """browser_evaluate_js 工具应执行 JS。"""
    from orion_agent_runtime.tools.browser_tools import browser_evaluate_js

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_evaluate_js(script="document.title"))
    assert "JS result" in result


def test_browser_close_tool(mock_browser):
    """browser_close 工具应关闭浏览器。"""
    from orion_agent_runtime.tools.browser_tools import browser_close

    asyncio.run(mock_browser.open(url="https://x.com"))
    result = asyncio.run(browser_close())
    assert "closed" in result.lower()


def test_browser_tab_management_tool(mock_browser):
    """browser_new_tab/switch_tab/close_tab 工具应正确管理标签页。"""
    from orion_agent_runtime.tools.browser_tools import (
        browser_new_tab,
        browser_switch_tab,
        browser_close_tab,
    )

    asyncio.run(mock_browser.open(url="https://tab0.com"))
    # 新建标签页
    r1 = asyncio.run(browser_new_tab(url="https://tab1.com"))
    assert "tab1.com" in r1
    assert mock_browser.get_tabs().__len__() == 2

    # 切换回第一个标签页
    r2 = asyncio.run(browser_switch_tab(index=0))
    assert "tab0" in r2

    # 关闭第二个标签页
    r3 = asyncio.run(browser_close_tab(index=1))
    assert "Remaining" in r3
    assert mock_browser.get_tabs().__len__() == 1


def test_browser_go_back_forward_tool(mock_browser):
    """browser_go_back / browser_go_forward 应导航历史。"""
    from orion_agent_runtime.tools.browser_tools import (
        browser_go_back,
        browser_go_forward,
        browser_navigate,
    )

    asyncio.run(browser_navigate(url="https://page1.com"))
    asyncio.run(browser_navigate(url="https://page2.com"))

    # 后退
    r1 = asyncio.run(browser_go_back())
    assert "page1.com" in r1

    # 前进
    r2 = asyncio.run(browser_go_forward())
    assert "page2.com" in r2


def test_browser_tool_without_capability():
    """未注册浏览器能力时，工具应返回错误信息而非抛异常。"""
    reset_registry()
    from orion_agent_runtime.tools.browser_tools import browser_navigate

    result = asyncio.run(browser_navigate(url="https://example.com"))
    assert "not available" in result.lower() or "error" in result.lower()
    reset_registry()


# ---- 事件发射验证 ----

def test_browser_tools_emit_events(tmp_path):
    """浏览器工具调用应触发 browser.* 事件。"""
    reset_registry()
    bus = EventBus(event_store_dir=tmp_path)
    cap = MockBrowserCapability(bus=bus)
    registry = CapabilityRegistry()
    registry.register(cap)
    import orion_agent_runtime.capabilities.base as base
    base._default_registry = registry

    received = []

    async def collect(ev):
        received.append(ev)

    bus.on(EventType.BROWSER_NAVIGATE, collect)
    bus.on(EventType.BROWSER_CLICK, collect)
    bus.on(EventType.BROWSER_TYPE, collect)

    from orion_agent_runtime.tools.browser_tools import (
        browser_navigate,
        browser_click,
        browser_type,
    )

    asyncio.run(browser_navigate(url="https://x.com"))
    asyncio.run(browser_click(selector="#btn"))
    asyncio.run(browser_type(selector="#q", text="hi"))

    event_types = [e.type for e in received]
    assert EventType.BROWSER_NAVIGATE in event_types
    assert EventType.BROWSER_CLICK in event_types
    assert EventType.BROWSER_TYPE in event_types

    reset_registry()


# ---- V2 完整流程（AgentRuntime + Mock Browser + Mock LLM）----

def test_v2_browser_workflow(tmp_path):
    """V2 模式下，AgentRuntime 用 mock browser 工具完成简单任务。

    模拟场景：LLM 决策序列为
      1. browser_navigate("https://example.com")
      2. browser_snapshot()  → 观察页面
      3. finish("Done")

    浏览器工具通过全局 CapabilityRegistry 获取能力实例，
    因此这里把 MockBrowserCapability 注册到全局 registry（与 V1 bootstrap_browser 一致）。
    """
    from orion_agent_runtime.core.models import ReactAction
    from orion_agent_runtime.kernel import Kernel
    from orion_agent_runtime.bus import EventBus, reset_event_bus
    from orion_agent_runtime.memory import MemoryManager
    from orion_agent_runtime.world import WorldManager
    from orion_agent_runtime.scheduler import Scheduler
    from orion_agent_runtime.runtime import AgentRuntime

    # 准备全局 CapabilityRegistry（浏览器工具从这里取能力）
    reset_registry()
    global_cap = MockBrowserCapability()
    import orion_agent_runtime.capabilities.base as base
    base._default_registry = CapabilityRegistry()
    base._default_registry.register(global_cap)

    # 构造隔离 Kernel（不依赖全局单例）
    reset_event_bus()
    bus = EventBus(event_store_dir=tmp_path / "events")
    memory = MemoryManager(db_path=tmp_path / "mem.db")
    world = WorldManager(bus)
    scheduler = Scheduler()
    kernel = Kernel(bus=bus, world=world, scheduler=scheduler, memory=memory)
    asyncio.run(kernel.start())

    runtime = AgentRuntime(kernel)

    # mock 决策序列
    decisions = iter([
        ReactAction(
            type="call_tool",
            thought="Navigate to the page",
            tool="browser_navigate",
            arguments={"url": "https://example.com"},
        ),
        ReactAction(
            type="call_tool",
            thought="Take a snapshot",
            tool="browser_snapshot",
            arguments={},
        ),
        ReactAction(
            type="finish",
            thought="Task complete",
            answer="Browser task completed successfully",
        ),
    ])

    async def mock_decide(state):
        return next(decisions)

    runtime.set_decide_fn(mock_decide)

    result = asyncio.run(runtime.run(
        goal="Navigate to example.com and report what you see",
        user_id="test",
    ))

    assert result.status in {"done", "goal_achieved"}
    # 应执行了 2 个工具调用（navigate + snapshot）
    assert result.iterations >= 2
    # 浏览器状态应已被导航
    assert global_cap.current_url == "https://example.com"

    asyncio.run(kernel.shutdown())
    reset_registry()
    reset_event_bus()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
