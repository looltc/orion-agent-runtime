"""MockBrowserCapability —— 浏览器能力的内存模拟实现。

用途：
- 无浏览器环境（CI、无 Playwright 安装）时的回退
- 单元测试（确定性、无副作用、不发真实网络请求）

模拟语义：
- 维护一个"虚拟页面"：current_url / current_title / dom 文本 / 已输入字段
- navigate 记录 url + 推测 title（取 url host）
- click/type/snapshot/extract_dom 基于内存状态返回确定性结果
- screenshot 返回占位数据
- 支持多标签页（虚拟）、后退/前进、JS 执行、等待等高级操作

所有动作仍 emit browser.* 事件（若注入 bus），保证事件流与真实实现一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from orion_agent_runtime.capabilities.base import Capability, CapabilityResult


class MockBrowserCapability(Capability):
    """内存模拟的浏览器能力。"""

    name = "browser"

    def __init__(self, bus: Optional[Any] = None) -> None:
        super().__init__(bus=bus)
        self.current_url: Optional[str] = None
        self.current_title: Optional[str] = None
        # selector -> 文本（模拟输入框内容）
        self.inputs: Dict[str, str] = {}
        # selector -> 点击次数
        self.clicks: Dict[str, int] = {}
        # 虚拟 DOM 文本（navigate 时按 url 生成可预测内容）
        self.dom_text: str = ""
        # 虚拟多标签页
        self._tab_urls: List[Optional[str]] = []
        self._tab_titles: List[Optional[str]] = []
        self._active_tab: int = 0
        # 导航历史（后退/前进）
        self._history: List[str] = []
        self._history_index: int = -1
        # JS 执行记录
        self.js_calls: List[str] = []

    # ---- 生命周期 ----

    async def open(self, url: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        self._opened = True
        if not self._tab_urls:
            self._tab_urls = [None]
            self._tab_titles = [None]
        if url:
            return await self.navigate(url, **kwargs)
        return CapabilityResult.ok(status="opened")

    async def close(self) -> CapabilityResult:
        self._opened = False
        self._tab_urls = []
        self._tab_titles = []
        self._active_tab = 0
        self._history = []
        self._history_index = -1
        await self._emit("browser.closed", {})
        return CapabilityResult.ok()

    # ---- 导航 ----

    async def navigate(self, url: str, **kwargs: Any) -> CapabilityResult:
        self.current_url = url
        # 推测 title：取 host
        title = url.split("//")[-1].split("/")[0] if "://" in url else url
        self.current_title = title
        # 生成可预测的虚拟 DOM（让 extract_dom 有内容）
        self.dom_text = (
            f"<html><head><title>{title}</title></head>"
            f"<body><h1>{title}</h1>"
            f"<input id='q' name='q' placeholder='Search'></input>"
            f"<button id='btn'>Search</button>"
            f"<a href='/page1'>Page 1</a>"
            f"<a href='/page2'>Page 2</a>"
            f"<select id='lang'><option value='en'>English</option><option value='zh'>中文</option></select>"
            f"</body></html>"
        )
        self.inputs.clear()
        self.clicks.clear()
        # 更新导航历史
        # 如果回退后导航新 URL，截断后续历史
        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        self._history.append(url)
        self._history_index = len(self._history) - 1
        # 更新当前标签页
        if self._tab_urls:
            self._tab_urls[self._active_tab] = url
            self._tab_titles[self._active_tab] = title
        payload = {"url": url, "title": title}
        await self._emit("browser.navigate", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def go_back(self, **kwargs: Any) -> CapabilityResult:
        if self._history_index <= 0:
            return CapabilityResult.fail("no previous page in history")
        self._history_index -= 1
        url = self._history[self._history_index]
        title = url.split("//")[-1].split("/")[0] if "://" in url else url
        self.current_url = url
        self.current_title = title
        self._regenerate_dom()
        if self._tab_urls:
            self._tab_urls[self._active_tab] = url
            self._tab_titles[self._active_tab] = title
        payload = {"url": url, "title": title}
        await self._emit("browser.navigate", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def go_forward(self, **kwargs: Any) -> CapabilityResult:
        if self._history_index >= len(self._history) - 1:
            return CapabilityResult.fail("no next page in history")
        self._history_index += 1
        url = self._history[self._history_index]
        title = url.split("//")[-1].split("/")[0] if "://" in url else url
        self.current_url = url
        self.current_title = title
        self._regenerate_dom()
        if self._tab_urls:
            self._tab_urls[self._active_tab] = url
            self._tab_titles[self._active_tab] = title
        payload = {"url": url, "title": title}
        await self._emit("browser.navigate", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def new_tab(self, url: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        if url:
            title = url.split("//")[-1].split("/")[0] if "://" in url else url
        else:
            title = "New Tab"
            url = "about:blank"
        self._tab_urls.append(url)
        self._tab_titles.append(title)
        self._active_tab = len(self._tab_urls) - 1
        self.current_url = url
        self.current_title = title
        if url != "about:blank":
            self._regenerate_dom()
        else:
            self.dom_text = ""
        payload = {
            "tab_count": len(self._tab_urls),
            "active_index": self._active_tab,
            "url": self.current_url,
            "title": self.current_title,
        }
        await self._emit("browser.navigate", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def switch_tab(self, index: int, **kwargs: Any) -> CapabilityResult:
        if index < 0 or index >= len(self._tab_urls):
            return CapabilityResult.fail(
                f"tab index {index} out of range [0, {len(self._tab_urls) - 1}]"
            )
        self._active_tab = index
        self.current_url = self._tab_urls[index]
        self.current_title = self._tab_titles[index]
        if self.current_url:
            self._regenerate_dom()
        payload = {
            "active_index": index,
            "tab_count": len(self._tab_urls),
            "url": self.current_url,
            "title": self.current_title,
        }
        await self._emit("browser.navigate", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def close_tab(self, index: Optional[int] = None, **kwargs: Any) -> CapabilityResult:
        if not self._tab_urls:
            return CapabilityResult.fail("no tabs available")
        if index is None:
            index = self._active_tab
        if index < 0 or index >= len(self._tab_urls):
            return CapabilityResult.fail(
                f"tab index {index} out of range [0, {len(self._tab_urls) - 1}]"
            )
        self._tab_urls.pop(index)
        self._tab_titles.pop(index)
        if self._tab_urls:
            if self._active_tab >= len(self._tab_urls):
                self._active_tab = len(self._tab_urls) - 1
            self.current_url = self._tab_urls[self._active_tab]
            self.current_title = self._tab_titles[self._active_tab]
            self._regenerate_dom()
        else:
            self._active_tab = 0
            self.current_url = None
            self.current_title = None
            self.dom_text = ""
        payload = {
            "tab_count": len(self._tab_urls),
            "closed_index": index,
            "url": self.current_url,
        }
        await self._emit("browser.closed", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    def get_tabs(self) -> List[Dict[str, Any]]:
        """获取所有标签页信息（同步，不发射事件）。"""
        result = []
        for i, url in enumerate(self._tab_urls):
            result.append({
                "index": i,
                "url": url,
                "active": i == self._active_tab,
            })
        return result

    # ---- 交互 ----

    async def click(self, selector: str, **kwargs: Any) -> CapabilityResult:
        self.clicks[selector] = self.clicks.get(selector, 0) + 1
        payload = {"selector": selector}
        await self._emit("browser.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(selector=selector, click_count=self.clicks[selector])

    async def type(self, selector: str, text: str, **kwargs: Any) -> CapabilityResult:
        self.inputs[selector] = text
        payload = {"selector": selector, "text": text}
        await self._emit("browser.type", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(selector=selector, text=text)

    async def press_key(self, key: str, **kwargs: Any) -> CapabilityResult:
        payload = {"key": key}
        await self._emit("browser.type", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(key=key)

    async def select_option(self, selector: str, value: str, **kwargs: Any) -> CapabilityResult:
        payload = {"selector": selector, "value": value}
        await self._emit("browser.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(selector=selector, value=value)

    async def hover(self, selector: str, **kwargs: Any) -> CapabilityResult:
        payload = {"selector": selector}
        await self._emit("browser.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(selector=selector)

    async def scroll(self, direction: str = "down", amount: int = 500, **kwargs: Any) -> CapabilityResult:
        if direction not in ("up", "down", "top", "bottom"):
            return CapabilityResult.fail(f"unknown scroll direction: {direction}")
        payload = {"direction": direction, "amount": amount}
        await self._emit("browser.click", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    # ---- 信息获取 ----

    async def snapshot(self, **kwargs: Any) -> CapabilityResult:
        payload = {"url": self.current_url, "title": self.current_title}
        await self._emit("browser.snapshot", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def get_page_text(self, **kwargs: Any) -> CapabilityResult:
        """提取页面可读文本（简化：用 dom_text 去标签）。"""
        selector = kwargs.get("selector")
        if selector and selector in self.dom_text:
            text = f"[{selector}]"
        else:
            # 简易去标签：替换常见标签为空格/换行
            import re
            text = self.dom_text
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        truncated = text[:8000] if len(text) > 8000 else text
        return CapabilityResult.ok(text=truncated, truncated=len(text) > 8000)

    async def get_element_text(self, selector: str, **kwargs: Any) -> CapabilityResult:
        if selector in self.dom_text:
            text = f"[content of {selector}]"
        elif selector in self.inputs:
            text = self.inputs[selector]
        else:
            return CapabilityResult.fail(f"element not found: {selector}")
        return CapabilityResult.ok(selector=selector, text=text)

    async def extract_dom(self, **kwargs: Any) -> CapabilityResult:
        selector = kwargs.get("selector")
        html = self.dom_text
        if selector and selector in self.dom_text:
            html = f"<element id='{selector}'>{self.inputs.get(selector, '')}</element>"
        truncated = html[:5000] if len(html) > 5000 else html
        return CapabilityResult.ok(html=truncated, truncated=len(html) > 5000)

    async def screenshot(self, path: Optional[str] = None, **kwargs: Any) -> CapabilityResult:
        return CapabilityResult.ok(
            path=path or "<memory>",
            bytes_len=1024,
            mock=True,
        )

    # ---- 高级操作 ----

    async def wait_for(
        self,
        selector: str,
        state: str = "visible",
        timeout: int = 30000,
        **kwargs: Any,
    ) -> CapabilityResult:
        """Mock 模式直接返回成功（模拟元素已存在）。"""
        payload = {"selector": selector, "state": state}
        await self._emit("browser.snapshot", payload,
                         task_id=kwargs.get("task_id"), run_id=kwargs.get("run_id"))
        return CapabilityResult.ok(**payload)

    async def evaluate_js(self, script: str, **kwargs: Any) -> CapabilityResult:
        """Mock 模式记录 JS 调用并返回占位结果。"""
        self.js_calls.append(script)
        return CapabilityResult.ok(result=f"[mock result for: {script[:100]}]")

    # ---- 内部辅助 ----

    def _regenerate_dom(self) -> None:
        """根据 current_url 重新生成虚拟 DOM。"""
        if self.current_url:
            title = (
                self.current_url.split("//")[-1].split("/")[0]
                if "://" in self.current_url
                else self.current_url
            )
            self.dom_text = (
                f"<html><head><title>{title}</title></head>"
                f"<body><h1>{title}</h1>"
                f"<input id='q' name='q' placeholder='Search'></input>"
                f"<button id='btn'>Search</button>"
                f"<a href='/page1'>Page 1</a>"
                f"<a href='/page2'>Page 2</a>"
                f"<select id='lang'><option value='en'>English</option><option value='zh'>中文</option></select>"
                f"</body></html>"
            )
            self.inputs.clear()
            self.clicks.clear()
