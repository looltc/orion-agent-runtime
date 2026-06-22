"""Browser Tools —— 将 BrowserCapability 桥接为 LLM 可调用工具。

设计文档红线："Planner 不直连底层驱动——对底层驱动的调用必须经过 Capability 层"。
本模块遵循该原则：每个工具 handler 通过 CapabilityRegistry 获取 BrowserCapability，
再调用对应方法。

所有 handler 为 async 函数（V2 AgentRuntime 原生支持 async handler）。
V1 同步 executor 也支持（通过 asyncio.run 桥接，见 core/executor.py）。

工具按功能分组：
- 导航：browser_open / browser_navigate / browser_go_back / browser_go_forward
         browser_new_tab / browser_switch_tab / browser_close_tab
- 交互：browser_click / browser_type / browser_press_key / browser_select_option
         browser_hover / browser_scroll
- 信息：browser_snapshot / browser_get_links / browser_get_page_text / browser_screenshot
- 高级：browser_wait / browser_evaluate_js
- 生命周期：browser_close
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field

from orion_agent_runtime.tools.registry import register_tool

logger = logging.getLogger(__name__)


# ---- helper：获取 BrowserCapability ----

def _get_browser():
    """从全局 CapabilityRegistry 获取浏览器能力实例。"""
    from orion_agent_runtime.capabilities.base import get_registry
    return get_registry().get("browser")


async def _get_browser_or_error():
    """获取浏览器能力，若未注册则返回错误信息。"""
    try:
        from orion_agent_runtime.capabilities.base import get_registry
        return get_registry().get("browser")
    except Exception as e:
        return f"browser capability not available: {e}"


# ---- 参数模型 ----

class BrowserOpenArgs(BaseModel):
    url: Optional[str] = Field(None, description="初始 URL（可选，传则自动导航）")

class BrowserNavigateArgs(BaseModel):
    url: str = Field(..., description="要导航到的完整 URL")

class BrowserGoBackArgs(BaseModel):
    pass

class BrowserGoForwardArgs(BaseModel):
    pass

class BrowserNewTabArgs(BaseModel):
    url: Optional[str] = Field(None, description="新标签页要打开的 URL")

class BrowserSwitchTabArgs(BaseModel):
    index: int = Field(..., description="标签页索引（从 0 开始）")

class BrowserCloseTabArgs(BaseModel):
    index: Optional[int] = Field(None, description="要关闭的标签页索引（默认关闭当前）")

class BrowserClickArgs(BaseModel):
    selector: str = Field(..., description="CSS 选择器，如 '#login-btn', 'button:has-text(\"Submit\")'")

class BrowserTypeArgs(BaseModel):
    selector: str = Field(..., description="输入框的 CSS 选择器")
    text: str = Field(..., description="要输入的文本")

class BrowserPressKeyArgs(BaseModel):
    key: str = Field(..., description="按键名称，如 Enter, Tab, Escape, ArrowDown, Control+a")

class BrowserSelectOptionArgs(BaseModel):
    selector: str = Field(..., description="select 元素的 CSS 选择器")
    value: str = Field(..., description="要选择的 option value")

class BrowserHoverArgs(BaseModel):
    selector: str = Field(..., description="要悬停的元素的 CSS 选择器")

class BrowserScrollArgs(BaseModel):
    direction: str = Field("down", description="滚动方向：up, down, top, bottom")
    amount: int = Field(500, description="滚动像素数（up/down 时有效）")

class BrowserSnapshotArgs(BaseModel):
    pass

class BrowserGetLinksArgs(BaseModel):
    pass

class BrowserGetPageTextArgs(BaseModel):
    selector: Optional[str] = Field(None, description="可选 CSS 选择器限定范围（不传则提取整个页面）")

class BrowserScreenshotArgs(BaseModel):
    path: Optional[str] = Field(None, description="截图保存路径（不传则截到内存）")

class BrowserWaitArgs(BaseModel):
    selector: str = Field(..., description="要等待的元素 CSS 选择器")
    state: str = Field("visible", description="等待状态：visible, hidden, attached, detached")
    timeout: int = Field(30000, description="超时时间（毫秒）")

class BrowserEvaluateJsArgs(BaseModel):
    script: str = Field(..., description="要执行的 JavaScript 代码")

class BrowserCloseArgs(BaseModel):
    pass


# ---- 导航工具 ----

@register_tool(
    "browser_open",
    "启动浏览器实例（如果尚未启动）。可传入 URL 在启动后自动导航到目标页面。"
    "首次调用浏览器操作前需先调用此工具。",
    BrowserOpenArgs,
)
async def browser_open(url: Optional[str] = None) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.open(url=url)
    if result.success:
        parts = [f"Browser opened"]
        if result.data.get("url"):
            parts.append(f"Navigated to: {result.data['url']}")
            parts.append(f"Title: {result.data.get('title', '')}")
        return ". ".join(parts)
    return f"Error: {result.error}"


@register_tool(
    "browser_navigate",
    "导航到指定 URL 并等待页面加载完成。返回页面 URL 和标题。",
    BrowserNavigateArgs,
)
async def browser_navigate(url: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    # 若浏览器未打开，自动 open
    if not cap.opened:
        await cap.open()
    result = await cap.navigate(url)
    if result.success:
        return f"Navigated to: {result.data['url']} | Title: {result.data.get('title', '')}"
    return f"Error: {result.error}"


@register_tool(
    "browser_go_back",
    "浏览器后退到上一页。",
    BrowserGoBackArgs,
)
async def browser_go_back() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.go_back()
    if result.success:
        return f"Back to: {result.data['url']} | Title: {result.data.get('title', '')}"
    return f"Error: {result.error}"


@register_tool(
    "browser_go_forward",
    "浏览器前进到下一页。",
    BrowserGoForwardArgs,
)
async def browser_go_forward() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.go_forward()
    if result.success:
        return f"Forward to: {result.data['url']} | Title: {result.data.get('title', '')}"
    return f"Error: {result.error}"


@register_tool(
    "browser_new_tab",
    "新建浏览器标签页，可选导航到 URL。返回当前标签页信息。",
    BrowserNewTabArgs,
)
async def browser_new_tab(url: Optional[str] = None) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.new_tab(url=url)
    if result.success:
        return (
            f"New tab opened. Active tab: {result.data.get('active_index', 0)}, "
            f"Total tabs: {result.data.get('tab_count', 1)}, "
            f"URL: {result.data.get('url', '')}"
        )
    return f"Error: {result.error}"


@register_tool(
    "browser_switch_tab",
    "切换到指定索引的标签页（索引从 0 开始）。返回切换后的页面信息。",
    BrowserSwitchTabArgs,
)
async def browser_switch_tab(index: int) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.switch_tab(index)
    if result.success:
        return (
            f"Switched to tab {result.data.get('active_index', index)}. "
            f"Total tabs: {result.data.get('tab_count', 1)}, "
            f"URL: {result.data.get('url', '')}, "
            f"Title: {result.data.get('title', '')}"
        )
    return f"Error: {result.error}"


@register_tool(
    "browser_close_tab",
    "关闭指定标签页（默认关闭当前标签页）。返回剩余标签页信息。",
    BrowserCloseTabArgs,
)
async def browser_close_tab(index: Optional[int] = None) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.close_tab(index=index)
    if result.success:
        tabs = cap.get_tabs()
        tab_info = ", ".join(f"[{t['index']}]{t['url'] or 'empty'}" for t in tabs)
        return f"Tab closed. Remaining tabs ({len(tabs)}): {tab_info}"
    return f"Error: {result.error}"


# ---- 交互工具 ----

@register_tool(
    "browser_click",
    "点击页面上的元素。selector 支持 CSS 选择器。"
    "常见写法：'#login-btn', '.nav-link', 'button:has-text(\"Submit\")', "
    "'a[href=\"/about\"]'。点击前会自动等待元素可见。",
    BrowserClickArgs,
)
async def browser_click(selector: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.click(selector)
    if result.success:
        return f"Clicked: {selector}"
    return f"Error: {result.error}"


@register_tool(
    "browser_type",
    "在输入框中填写文本（会先清空已有内容）。selector 用 CSS 选择器指定输入框。",
    BrowserTypeArgs,
)
async def browser_type(selector: str, text: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.type(selector, text)
    if result.success:
        return f"Typed '{text}' into {selector}"
    return f"Error: {result.error}"


@register_tool(
    "browser_press_key",
    "按下键盘按键。常用于提交表单（Enter）、切换焦点（Tab）、关闭弹窗（Escape）等。"
    "组合键用 '+' 连接，如 'Control+a', 'Shift+Tab'。",
    BrowserPressKeyArgs,
)
async def browser_press_key(key: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.press_key(key)
    if result.success:
        return f"Key pressed: {key}"
    return f"Error: {result.error}"


@register_tool(
    "browser_select_option",
    "选择下拉菜单（select）中的选项。需要 select 的 CSS 选择器和 option 的 value。",
    BrowserSelectOptionArgs,
)
async def browser_select_option(selector: str, value: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.select_option(selector, value)
    if result.success:
        return f"Selected '{value}' in {selector}"
    return f"Error: {result.error}"


@register_tool(
    "browser_hover",
    "将鼠标悬停在指定元素上（触发 hover 效果、下拉菜单展开等）。",
    BrowserHoverArgs,
)
async def browser_hover(selector: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.hover(selector)
    if result.success:
        return f"Hovered on: {selector}"
    return f"Error: {result.error}"


@register_tool(
    "browser_scroll",
    "滚动页面。direction: up（向上）、down（向下，默认）、top（回到顶部）、bottom（滚动到底部）。"
    "amount 为滚动像素数（up/down 有效，默认 500）。",
    BrowserScrollArgs,
)
async def browser_scroll(direction: str = "down", amount: int = 500) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.scroll(direction=direction, amount=amount)
    if result.success:
        msg = f"Scrolled {direction}" + (f" by {amount}px" if direction in ("up", "down") else "")
        # 滚到底部/顶部时附上当前可见的标题，给 LLM 提供上下文
        if direction in ("bottom", "top"):
            try:
                headings = await cap._page.evaluate("""
                    (() => {
                        const vh = window.innerHeight, vw = window.innerWidth;
                        const hs = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
                        const visible = [];
                        hs.forEach(h => {
                            const r = h.getBoundingClientRect();
                            if (r.top < vh && r.bottom > 0) visible.push(h.innerText.trim());
                        });
                        return visible.slice(-5);
                    })()
                """)
                if headings:
                    msg += f"\n可见标题: {' | '.join(h[:60] for h in headings)}"
            except Exception:
                pass
        return msg
    return f"Error: {result.error}"


# ---- 信息获取工具 ----

@register_tool(
    "browser_snapshot",
    "获取当前页面的结构化摘要，包括 URL、标题、所有可交互元素（链接、输入框、按钮、下拉菜单）"
    "和页面文本内容。这是了解页面内容和决定下一步操作的主要方式。"
    "会自动等待动态内容渲染完成（最多 3 秒）。",
    BrowserSnapshotArgs,
)
async def browser_snapshot() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened. Call browser_open or browser_navigate first."
    # 对真实 Playwright 使用 PageExtractor
    from orion_agent_runtime.config import get_config
    if get_config().browser_mode.lower() == "real" and hasattr(cap, "_page") and cap._page:
        # 等待动态内容渲染：如果 body 文本很短（< 200 字符），
        # 可能是 SPA 还在加载，最多再等 3 秒让 JS 渲染
        await _wait_for_content(cap._page)
        from orion_agent_runtime.capabilities.browser.extractor import PageExtractor
        try:
            return await PageExtractor.extract_snapshot(cap._page)
        except Exception as e:
            # 回退到基础 snapshot
            result = await cap.snapshot()
            if result.success:
                return f"[Page] URL: {result.data['url']} | Title: {result.data.get('title', '')}\n(Note: enhanced extraction failed: {e})"
            return f"Error: {result.error}"
    # Mock 模式：用 extract_from_html
    from orion_agent_runtime.capabilities.browser.extractor import PageExtractor
    url = cap.current_url or "about:blank"
    title = cap.current_title or ""
    html = cap.dom_text if hasattr(cap, "dom_text") else ""
    snapshot = PageExtractor.extract_from_html(html, url=url, title=title)
    # 补充标签页信息
    tabs = cap.get_tabs()
    if len(tabs) > 1:
        tab_info = ", ".join(f"[{t['index']}]{t['url'] or 'empty'}{' (active)' if t['active'] else ''}" for t in tabs)
        snapshot = f"[Tabs] {len(tabs)} tabs: {tab_info}\n" + snapshot
    return snapshot


async def _wait_for_content(page: Any, max_wait_ms: int = 5000, stable_interval_ms: int = 500) -> None:
    """等待页面内容稳定，用于 SPA 动态渲染场景。

    策略（比"字符数阈值"更鲁棒）：
    1. 轮询 page.inner_text("body")
    2. 若连续 2 次内容相同且非空 → 认为渲染稳定，返回
    3. 最多等 max_wait_ms（5 秒）

    相比旧的">=200 字符"判据，本策略能识别"页面还在变"的状态：
    导航头虽已渲染，但天气数据还在 AJAX 加载时，文本会持续变化，
    此时继续等待；只有当文本真正稳定后才返回。
    """
    import asyncio
    last_text = ""
    stable_count = 0
    waited = 0
    while waited < max_wait_ms:
        try:
            current = await page.inner_text("body")
        except Exception:
            break
        if current == last_text and len(current.strip()) > 0:
            stable_count += 1
            if stable_count >= 2:  # 连续 2 次相同 → 稳定
                return
        else:
            stable_count = 0
        last_text = current
        await asyncio.sleep(stable_interval_ms / 1000)
        waited += stable_interval_ms


@register_tool(
    "browser_get_links",
    "提取当前页面所有链接，包括链接文本、目标 URL 和 CSS 选择器。",
    BrowserGetLinksArgs,
)
async def browser_get_links() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened."
    from orion_agent_runtime.config import get_config
    if get_config().browser_mode.lower() == "real" and hasattr(cap, "_page") and cap._page:
        from orion_agent_runtime.capabilities.browser.extractor import PageExtractor
        try:
            return await PageExtractor.extract_links(cap._page)
        except Exception as e:
            return f"Error extracting links: {e}"
    # Mock 模式
    from orion_agent_runtime.capabilities.browser.extractor import PageExtractor
    html = cap.dom_text if hasattr(cap, "dom_text") else ""
    return PageExtractor.extract_from_html(
        html, url=cap.current_url or "", title=cap.current_title or ""
    ).split("[Content]")[0].strip()


@register_tool(
    "browser_get_page_text",
    "获取页面的纯文本内容（去除所有 HTML 标签）。可选 selector 限定提取范围。",
    BrowserGetPageTextArgs,
)
async def browser_get_page_text(selector: Optional[str] = None) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened."
    result = await cap.get_page_text(selector=selector)
    if result.success:
        return result.data.get("text", "")
    return f"Error: {result.error}"


@register_tool(
    "browser_screenshot",
    "对当前页面截图。可指定保存路径，不传路径则截到内存（仅返回信息）。",
    BrowserScreenshotArgs,
)
async def browser_screenshot(path: Optional[str] = None) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened."
    result = await cap.screenshot(path=path)
    if result.success:
        if path:
            return f"Screenshot saved to: {path}"
        return f"Screenshot taken (bytes: {result.data.get('bytes_len', 'unknown')})"
    return f"Error: {result.error}"


# ---- 高级操作工具 ----

@register_tool(
    "browser_wait",
    "等待页面上的元素达到指定状态后再继续。state: visible（可见，默认）、hidden（隐藏）、"
    "attached（已挂载）、detached（已移除）。超时则返回错误。",
    BrowserWaitArgs,
)
async def browser_wait(selector: str, state: str = "visible", timeout: int = 30000) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.wait_for(selector=selector, state=state, timeout=timeout)
    if result.success:
        return f"Element {selector} is now {state}."
    return f"Error: {result.error}"


@register_tool(
    "browser_evaluate_js",
    "在当前页面执行 JavaScript 代码并返回结果。适用于获取页面数据、修改 DOM、触发事件等高级操作。",
    BrowserEvaluateJsArgs,
)
async def browser_evaluate_js(script: str) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.evaluate_js(script)
    if result.success:
        return f"JS result: {result.data.get('result', '')}"
    return f"Error: {result.error}"


class BrowserExtractResultsArgs(BaseModel):
    max_results: int = Field(10, description="最多返回多少条结果")


@register_tool(
    "browser_extract_results",
    "提取当前页面的搜索结果列表（支持百度、Google 等搜索引擎）。"
    "每个结果包含标题、URL 和摘要。结果编号后 LLM 可配合 browser_click 点击指定项。"
    "搜索后先用此工具提取结构化结果，再决定下一步操作。",
    BrowserExtractResultsArgs,
)
async def browser_extract_results(max_results: int = 10) -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened."
    try:
        js = f"""
            (() => {{
                const results = [];
                const seen = new Set();
                // 策略1: 百度 result 容器
                ['#content_left .result', '#content_left .c-container',
                 '#content_left h3 a', '.c-container h3 a',
                 '#content_left [mu]'].forEach(sel => {{
                    try {{
                        document.querySelectorAll(sel).forEach(el => {{
                            if (results.length >= {max_results}) return;
                            const a = el.tagName === 'A' ? el : el.querySelector('a');
                            if (!a || !a.href) return;
                            const title = a.innerText.trim().substring(0, 100);
                            const href = a.href;
                            const key = title + href;
                            if (!seen.has(key) && title.length > 3 && !title.includes('广告') && href.startsWith('http') && !href.includes('baidu.com/js/')) {{
                                seen.add(key);
                                // 尝试提取摘要
                                const abs = el.querySelector('.c-abstract, .c-span-last, [class*="abstract"]');
                                const snippet = abs ? abs.innerText.trim().substring(0, 150) : '';
                                results.push({{title, href, snippet}});
                            }}
                        }});
                    }} catch(e) {{}}
                }});
                // 策略2: 通用——页面中看起来像结果标题的链接（去重用 seen set）
                if (!results.length) {{
                    const mainContent = document.querySelector('#content_left, #main, .content, main, article, [role=main]') || document.body;
                    const links = mainContent.querySelectorAll('a[href^="http"]');
                    for (const a of links) {{
                        if (results.length >= {max_results}) break;
                        const title = a.innerText.trim();
                        const href = a.href;
                        const key = title + href;
                        const skip = title.length < 8 || title.length > 150 ||
                            title.includes('广告') || title.includes('登录') ||
                            href.includes('baidu.com/js/') || href.includes('passport.baidu.com') ||
                            href.includes('e.baidu.com');
                        if (!skip && !seen.has(key) && href.startsWith('http')) {{
                            seen.add(key);
                            const parent = a.closest('div,li,section');
                            const ctx = parent ? parent.innerText.trim().substring(0, 150) : '';
                            results.push({{title, href, snippet: ctx}});
                        }}
                    }}
                }}
                return results;
            }})()
        """
        result = await cap._page.evaluate(js)
        if not result:
            return "(未找到搜索结果——可能仍在百度首页或验证码页面，请确认已成功搜索)"
        lines = [f"共 {len(result)} 条结果:"]
        for i, r in enumerate(result):
            title = r.get('title', '')[:80]
            href = r.get('href', '')[:120]
            snippet = r.get('snippet', '')
            lines.append(f"  {i+1}. {title}")
            lines.append(f"     URL: {href}")
            if snippet and snippet != title:
                # 仅取摘要中与标题不重复的第一行
                first_line = snippet.split('\n')[0][:100]
                if first_line and first_line not in title:
                    lines.append(f"     摘要: {first_line}")
        return "\n".join(lines)
    except Exception as e:
        return f"提取搜索结果失败: {e}"


class BrowserSectionsArgs(BaseModel):
    pass


@register_tool(
    "browser_extract_sections",
    "提取页面所有标题/章节结构（h1-h6 标签），返回层级化目录。"
    "适用于需要了解页面结构、定位特定章节、或提取最后章节标题的场景。"
    "无需额外参数，直接调用即可获得页面大纲。",
    BrowserSectionsArgs,
)
async def browser_extract_sections() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    if not cap.opened:
        return "Error: browser not opened."
    try:
        headings = await cap._page.evaluate("""
            (() => {
                const results = [];
                const hs = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
                hs.forEach((h, i) => {
                    const level = parseInt(h.tagName.substring(1));
                    const text = h.innerText.trim().substring(0, 200);
                    const id = h.id || '';
                    if (text.length > 1) results.push({index: i+1, level, text, id});
                });
                return results;
            })()
        """)
        if not headings:
            return "页面中未找到标题元素 (h1-h6)"
        lines = [f"共 {len(headings)} 个标题:"]
        for h in headings:
            indent = "  " * (h['level'] - 1)
            lines.append(f"{indent}{h['index']}. [{h['id'] or '-'}] {h['text']}")
        return "\n".join(lines)
    except Exception as e:
        return f"提取章节失败: {e}"


# ---- 生命周期 ----

@register_tool(
    "browser_close",
    "关闭浏览器并释放所有资源。通常在完成所有浏览操作后调用。",
    BrowserCloseArgs,
)
async def browser_close() -> str:
    cap = await _get_browser_or_error()
    if isinstance(cap, str):
        return cap
    result = await cap.close()
    if result.success:
        return "Browser closed."
    return f"Error: {result.error}"
