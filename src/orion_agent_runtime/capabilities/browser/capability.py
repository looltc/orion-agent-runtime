"""BrowserCapability —— 真实 Playwright 实现 + Mock 回退。

设计文档第 4 节：Playwright 驱动，负责网页导航、点击、输入、下载、DOM 采集、截图。
验收点：浏览器能力可独立运行，能完成 打开页面/点击/输入/提取DOM/截图。

模式切换（ORION_BROWSER_MODE）：
- "real"：真实 Playwright chromium（需 pip install playwright && playwright install）
- "mock"（默认）：内存模拟，无浏览器环境/测试回退

完整 Browser Use Agent 能力：
- 导航：navigate / go_back / go_forward / new_tab / switch_tab / close_tab
- 交互：click / type / press_key / select_option / hover / scroll
- 信息：snapshot / get_page_text / extract_dom / screenshot
- 高级：wait_for / evaluate_js
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from orion_agent_runtime.capabilities.base import (
    Capability,
    CapabilityError,
    CapabilityResult,
)
from orion_agent_runtime.capabilities.browser.mock import MockBrowserCapability
from orion_agent_runtime.config import get_config

logger = logging.getLogger(__name__)


class BrowserCapability(Capability):
    """真实 Playwright 浏览器能力。

    懒加载：open() 时才启动 chromium，避免 import 即启动浏览器。
    所有动作 emit browser.* 事件（若注入了 bus）。
    """

    name = "browser"

    def __init__(self, bus: Optional[Any] = None, *, headless: bool = True) -> None:
        super().__init__(bus=bus)
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None  # persistent context (launch_persistent_context 产物)
        self._page = None
        self._pages: List = []  # 所有标签页引用
        self._current_url: Optional[str] = None
        self._current_title: Optional[str] = None

    # ---- 生命周期 ----

    async def open(self, url: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        """启动浏览器并可选导航到 url。

        使用 launch_persistent_context 持久化 profile，手动过的验证码
        和登录态会保留到 runtime_state/browser_profile/，下次自动跳过。
        """
        try:
            if self._playwright is None:
                from playwright.async_api import async_playwright
                from orion_agent_runtime.config import get_config
                cfg = get_config()

                self._playwright = await async_playwright().start()
                profile_dir = str(cfg.runtime_state_dir.resolve() / "browser_profile")
                self._context = await self._playwright.chromium.launch_persistent_context(
                    profile_dir,
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1280, "height": 800},
                )
                self._browser = self._context.browser
                # 反检测：擦除 webdriver 标记
                await self._context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => false});
                """)
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                self._pages = list(self._context.pages)
            if url:
                nav_result = await self.navigate(url, **kwargs)
                if not nav_result.success:
                    # 导航失败则关闭浏览器，下次 open 会重新创建
                    await self._close_all()
                return nav_result
            self._opened = True
            return CapabilityResult.ok(status="opened")
        except Exception as e:
            return CapabilityResult.fail(f"browser open failed: {e}")

    async def close(self) -> CapabilityResult:
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._browser = None
            self._context = None
            self._playwright = None
            self._pages = []
            self._opened = False
        await self._emit("browser.closed", {})
        return CapabilityResult.ok()

    async def _close_all(self) -> None:
        """内部清理：关闭浏览器和 playwright，重置全部状态。"""
        try:
            if self._page:
                await self._page.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._browser = None
        self._context = None
        self._playwright = None
        self._pages = []
        self._opened = False

    # ---- 导航 ----

    async def navigate(self, url: str, **kwargs: Any) -> CapabilityResult:
        """导航到 url 并等待内容稳定（browser.navigate 事件）。

        等待策略：
        1. 先用 networkidle（短超时 5s，覆盖大部分静态/SSR 页面）
        2. 超时则降级到 domcontentloaded（对百度/微博等长连接页面足够）
        3. domcontentloaded 后额外等 1s 让 SPA 首屏 JS 完成渲染
        """
        if self._page is None:
            return CapabilityResult.fail("browser not opened; call open() first")
        timeout = kwargs.get("timeout", 30000)
        try:
            # 快速尝试 networkidle（5s 内没空闲就降级，不硬等）
            try:
                await self._page.goto(url, wait_until="networkidle",
                                      timeout=min(timeout, 5000))
            except Exception:
                logger.debug("navigate networkidle failed for %s, fallback to domcontentloaded", url)
                await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                # 给 SPA JS 渲染留点时间
                await asyncio.sleep(1)
            self._current_url = url
            self._current_title = await self._page.title()
            self._opened = True
            payload = {"url": self._current_url, "title": self._current_title}
            await self._emit("browser.navigate", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"navigate failed: {e}", url=url)

    async def go_back(self, **kwargs: Any) -> CapabilityResult:
        """浏览器后退。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            resp = await self._page.go_back()
            self._current_url = self._page.url
            self._current_title = await self._page.title()
            payload = {"url": self._current_url, "title": self._current_title}
            await self._emit("browser.navigate", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"go_back failed: {e}")

    async def go_forward(self, **kwargs: Any) -> CapabilityResult:
        """浏览器前进。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            resp = await self._page.go_forward()
            self._current_url = self._page.url
            self._current_title = await self._page.title()
            payload = {"url": self._current_url, "title": self._current_title}
            await self._emit("browser.navigate", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"go_forward failed: {e}")

    async def new_tab(self, url: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        """新建标签页，可选导航到 url。"""
        if self._browser is None:
            return CapabilityResult.fail("browser not opened")
        try:
            page = await self._browser.new_page()
            self._pages.append(page)
            if url:
                await page.goto(url)
            self._page = page
            self._current_url = page.url
            self._current_title = await page.title()
            payload = {
                "tab_count": len(self._pages),
                "active_index": len(self._pages) - 1,
                "url": self._current_url,
                "title": self._current_title,
            }
            await self._emit("browser.navigate", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"new_tab failed: {e}")

    async def switch_tab(self, index: int, **kwargs: Any) -> CapabilityResult:
        """切换到指定标签页。"""
        if not self._pages:
            return CapabilityResult.fail("no tabs available")
        if index < 0 or index >= len(self._pages):
            return CapabilityResult.fail(
                f"tab index {index} out of range [0, {len(self._pages) - 1}]"
            )
        try:
            self._page = self._pages[index]
            self._current_url = self._page.url
            self._current_title = await self._page.title()
            payload = {
                "active_index": index,
                "tab_count": len(self._pages),
                "url": self._current_url,
                "title": self._current_title,
            }
            await self._emit("browser.navigate", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"switch_tab failed: {e}")

    async def close_tab(self, index: Optional[int] = None, **kwargs: Any) -> CapabilityResult:
        """关闭指定标签页（默认关闭当前标签页）。"""
        if not self._pages:
            return CapabilityResult.fail("no tabs available")
        if index is None:
            index = self._pages.index(self._page) if self._page in self._pages else 0
        if index < 0 or index >= len(self._pages):
            return CapabilityResult.fail(
                f"tab index {index} out of range [0, {len(self._pages) - 1}]"
            )
        try:
            await self._pages[index].close()
            self._pages.pop(index)
            # 切换到最后一个标签页
            if self._pages:
                self._page = self._pages[-1]
                self._current_url = self._page.url
                self._current_title = await self._page.title()
            else:
                self._page = None
                self._current_url = None
                self._current_title = None
            payload = {
                "tab_count": len(self._pages),
                "closed_index": index,
                "url": self._current_url,
            }
            await self._emit("browser.closed", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"close_tab failed: {e}")

    def get_tabs(self) -> List[Dict[str, Any]]:
        """获取所有标签页信息（同步，不发射事件）。"""
        result = []
        for i, page in enumerate(self._pages):
            result.append({
                "index": i,
                "url": page.url,
                "active": page is self._page,
            })
        return result

    # ---- 交互 ----

    async def click(self, selector: str, **kwargs: Any) -> CapabilityResult:
        """点击元素，自动等待可见。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.click(selector, timeout=kwargs.get("timeout", 30000))
            payload = {"selector": selector}
            await self._emit("browser.click", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(selector=selector)
        except Exception as e:
            return CapabilityResult.fail(f"click failed: {e}", selector=selector)

    async def type(self, selector: str, text: str, **kwargs: Any) -> CapabilityResult:
        """在输入框中填写文本。

        策略：先检测可见性；不可见则 evaluate 强制显示元素，
        然后用 click+fill 正常输入（触发 React/Vue 事件），
        保证框架内部状态同步。仅在所有方式都失败时用 evaluate 兜底。
        """
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.wait_for_selector(selector, state="attached", timeout=5000)
            # 检测可见性
            visible = await self._page.evaluate(f"""
                (()=>{{const e=document.querySelector('{selector}');if(!e)return 0;
                const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0?1:0}})()
            """)
            if not visible:
                # 强制显示：改 CSS 让元素可见
                await self._page.evaluate(f"""
                    const e=document.querySelector('{selector}');
                    if(e){{e.style.cssText='display:block!important;visibility:visible!important;opacity:1!important;position:static!important'}}
                """)
                await asyncio.sleep(0.2)
            # click 聚焦 → 逐字符输入（触发完整键盘事件，百度无法拦截重置）
            filled = False
            try:
                await self._page.click(selector, timeout=3000)
                # 先全选删除现有值
                await self._page.keyboard.press("Control+a")
                await self._page.keyboard.press("Backspace")
                # 逐字符输入
                await self._page.keyboard.type(text, delay=30)
                await asyncio.sleep(0.1)
                # 验证
                actual = await self._page.evaluate(f"document.querySelector('{selector}').value")
                if actual == text:
                    filled = True
            except Exception:
                pass
            if not filled:
                # 兜底：原生 setter + 事件（绕过所有 JS 拦截）
                escaped = text.replace("\\", "\\\\").replace("'", "\\'")
                await self._page.evaluate(f"""
                    (()=>{{
                        const e=document.querySelector('{selector}');
                        if(!e)return;
                        const desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
                        const ns=desc?desc.set:null;
                        if(ns){{ns.call(e,'');e.dispatchEvent(new Event('input',{{bubbles:true}}));ns.call(e,'{escaped}');e.dispatchEvent(new Event('input',{{bubbles:true}}));}}
                        else{{e.value='';e.dispatchEvent(new Event('input',{{bubbles:true}}));e.value='{escaped}';e.dispatchEvent(new Event('input',{{bubbles:true}}));}}
                        e.dispatchEvent(new Event('change',{{bubbles:true}}));
                    }})()
                """)
                actual = await self._page.evaluate(f"document.querySelector('{selector}').value")
                if actual == text:
                    filled = True
            # 等 React 状态同步（不要 blur，避免百度 blur handler 重置值）
            await asyncio.sleep(0.3)
            if not filled:
                return CapabilityResult.fail(
                    f"type verification failed: expected '{text}' got '{actual}'",
                    selector=selector
                )
        except Exception as e:
            return CapabilityResult.fail(f"type failed: {e}", selector=selector)
        payload = {"selector": selector, "text": text}
        await self._emit("browser.type", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(selector=selector, text=text)

    async def press_key(self, key: str, **kwargs: Any) -> CapabilityResult:
        """按下键盘按键（Enter, Tab, Escape, ArrowDown 等）。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.keyboard.press(key)
            payload = {"key": key}
            await self._emit("browser.type", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(key=key)
        except Exception as e:
            return CapabilityResult.fail(f"press_key failed: {e}", key=key)

    async def select_option(self, selector: str, value: str, **kwargs: Any) -> CapabilityResult:
        """选择下拉菜单选项。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.select_option(selector, value)
            payload = {"selector": selector, "value": value}
            await self._emit("browser.click", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(selector=selector, value=value)
        except Exception as e:
            return CapabilityResult.fail(f"select_option failed: {e}", selector=selector)

    async def hover(self, selector: str, **kwargs: Any) -> CapabilityResult:
        """鼠标悬停在元素上。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.hover(selector, timeout=kwargs.get("timeout", 30000))
            payload = {"selector": selector}
            await self._emit("browser.click", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(selector=selector)
        except Exception as e:
            return CapabilityResult.fail(f"hover failed: {e}", selector=selector)

    async def scroll(self, direction: str = "down", amount: int = 500, **kwargs: Any) -> CapabilityResult:
        """滚动页面。direction: up/down/top/bottom。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            if direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "down":
                await self._page.evaluate(f"window.scrollBy(0, {amount})")
            else:
                return CapabilityResult.fail(f"unknown scroll direction: {direction}")
            payload = {"direction": direction, "amount": amount}
            await self._emit("browser.click", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"scroll failed: {e}")

    # ---- 信息获取 ----

    async def snapshot(self, **kwargs: Any) -> CapabilityResult:
        """采集当前页快照（url + title + DOM 摘要）。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            url = self._page.url
            title = await self._page.title()
            self._current_url = url
            self._current_title = title
            payload = {"url": url, "title": title}
            await self._emit("browser.snapshot", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(f"snapshot failed: {e}")

    async def get_page_text(self, **kwargs: Any) -> CapabilityResult:
        """提取页面可读文本。优先取主内容区可视部分，回退 body。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            selector = kwargs.get("selector")
            if selector:
                element = await self._page.query_selector(selector)
                text = await element.inner_text() if element else ""
            else:
                # 用 JS 提取可视区域文本（滚动后能读到不同内容）
                text = await self._page.evaluate("""
                    (() => {
                        // 优先取主内容区
                        const content = document.querySelector('#bodyContent, #mw-content-text, main, article, #content, [role=main]') || document.body;
                        const vh = window.innerHeight;
                        const vw = window.innerWidth;
                        const parts = [];
                        const walk = (node) => {
                            if (node.nodeType === 3) { // text node
                                const t = node.textContent.trim();
                                if (t) {
                                    const r = node.parentElement.getBoundingClientRect();
                                    if (r.top < vh && r.bottom > 0 && r.left < vw && r.right > 0) {
                                        parts.push(t);
                                    }
                                }
                            } else if (node.nodeType === 1) {
                                const tag = node.tagName;
                                if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return;
                                const r = node.getBoundingClientRect();
                                if (r.bottom < 0 || r.top > vh) return; // off-screen
                                for (const c of node.childNodes) walk(c);
                            }
                        };
                        walk(content);
                        return parts.join('\\n');
                    })()
                """) or ""
            truncated = text[:8000] if len(text) > 8000 else text
            return CapabilityResult.ok(text=truncated, truncated=len(text) > 8000)
        except Exception as e:
            return CapabilityResult.fail(f"get_page_text failed: {e}")

    async def get_element_text(self, selector: str, **kwargs: Any) -> CapabilityResult:
        """提取指定元素的文本内容。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            element = await self._page.query_selector(selector)
            if element is None:
                return CapabilityResult.fail(f"element not found: {selector}")
            text = await element.inner_text()
            return CapabilityResult.ok(selector=selector, text=text)
        except Exception as e:
            return CapabilityResult.fail(f"get_element_text failed: {e}")

    async def extract_dom(self, **kwargs: Any) -> CapabilityResult:
        """提取页面 DOM 内容（可选 selector 限定）。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            selector = kwargs.get("selector")
            if selector:
                element = await self._page.query_selector(selector)
                html = await element.inner_html() if element else ""
            else:
                html = await self._page.content()
            # 截断避免事件 payload 过大
            truncated = html[:5000] if len(html) > 5000 else html
            return CapabilityResult.ok(html=truncated, truncated=len(html) > 5000)
        except Exception as e:
            return CapabilityResult.fail(f"extract_dom failed: {e}")

    async def screenshot(self, path: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        """截图，返回保存路径或 bytes。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            if path:
                await self._page.screenshot(path=path, full_page=kwargs.get("full_page", False))
                return CapabilityResult.ok(path=path)
            else:
                data = await self._page.screenshot(full_page=kwargs.get("full_page", False))
                return CapabilityResult.ok(bytes_len=len(data))
        except Exception as e:
            return CapabilityResult.fail(f"screenshot failed: {e}")

    # ---- 高级操作 ----

    async def wait_for(
        self,
        selector: str,
        state: str = "visible",
        timeout: int = 30000,
        **kwargs: Any,
    ) -> CapabilityResult:
        """等待元素达到指定状态（visible/hidden/attached/detached）。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            await self._page.wait_for_selector(selector, state=state, timeout=timeout)
            payload = {"selector": selector, "state": state}
            await self._emit("browser.snapshot", payload,
                             task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
            return CapabilityResult.ok(**payload)
        except Exception as e:
            return CapabilityResult.fail(
                f"wait_for({selector}, {state}) timed out: {e}",
                selector=selector,
            )

    async def evaluate_js(self, script: str, **kwargs: Any) -> CapabilityResult:
        """执行 JavaScript 并返回结果。"""
        if self._page is None:
            return CapabilityResult.fail("browser not opened")
        try:
            result = await self._page.evaluate(script)
            return CapabilityResult.ok(result=result)
        except Exception as e:
            return CapabilityResult.fail(f"evaluate_js failed: {e}")


def create_browser_capability(bus: Optional[Any] = None, **kwargs: Any) -> Capability:
    """工厂：根据 ORION_BROWSER_MODE 选择 real 或 mock 实现。

    默认 mock（避免无浏览器环境/CI 失败）；real 需显式配置。
    """
    cfg = get_config()
    mode = cfg.browser_mode.lower()
    if mode == "real":
        # 从配置注入 headless，**kwargs 中显式传入的值优先
        merged = {"headless": cfg.browser_headless}
        merged.update(kwargs)
        return BrowserCapability(bus=bus, **merged)
    return MockBrowserCapability(bus=bus)
