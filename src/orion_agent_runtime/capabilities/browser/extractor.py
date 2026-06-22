"""PageExtractor —— 将页面 DOM 转为 LLM 友好的结构化文本。

职责：
- 从 Playwright Page 提取可交互元素（链接、输入框、按钮、下拉菜单）
- 提取页面纯文本内容（含 iframe 内内容）
- 格式化为结构化文本供 LLM 消费

输出格式示例：
  [Page] URL: https://example.com | Title: Example
  [Links]
    1. "Home" → https://example.com/ [a:has-text("Home") >> nth=0]
  [Inputs]
    1. [text] name="q" placeholder="Search" [input[name="q"]]
  [Buttons]
    1. "Submit" [button:has-text("Submit")]
  [Selects]
    1. name="lang" [select[name="lang"]]
  [Content]
    Main text content here...

iframe 支持：
- page.frames 返回主框架 + 所有 iframe
- _all_frames() 枚举所有可访问框架（跨域 iframe 会被 try/except 跳过）
- 内容提取优先取语义化区域（main/article/#content）以过滤导航/页脚噪声
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---- 文本截断限制 ----
_MAX_LINKS = 50
_MAX_INPUTS = 20
_MAX_BUTTONS = 30
_MAX_SELECTS = 10
# 与 capability.get_page_text() 的 8000 字符保持一致
_MAX_CONTENT_CHARS = 8000

# 语义化内容区域选择器（按优先级排序）
# 优先从这些区域提取正文，避免抓到全站导航/页脚/版权噪声
_CONTENT_SELECTORS = [
    "main", "article", "#content", ".content",
    "#main", ".main", "#article", ".article",
    "[role='main']", "#wrapper", ".wrapper",
]


class PageExtractor:
    """从 Playwright Page 提取 LLM 友好的结构化文本。

    所有方法为 async（直接接收 Playwright Page 对象）。
    纯函数，不发射事件，不依赖 Capability 实例。
    """

    # ---- 页面快照（最常用的提取方式）----

    @staticmethod
    async def extract_snapshot(page: Any) -> str:
        """提取完整页面快照（URL + 交互元素 + 内容）。

        这是 LLM 了解页面状态的主要方式。
        """
        url = page.url
        title = await page.title()

        lines: List[str] = []
        lines.append(f"[Page] URL: {url} | Title: {title}")

        # 交互元素
        interactive = await PageExtractor._extract_interactive(page)
        if interactive:
            lines.append("")
            lines.extend(interactive)

        # 页面文本内容（含 iframe）
        content = await PageExtractor._extract_content(page)
        if content:
            lines.append("")
            lines.append("[Content]")
            lines.append(content)

        return "\n".join(lines)

    # ---- 分类提取 ----

    @staticmethod
    async def extract_links(page: Any) -> str:
        """提取页面所有链接（含 iframe 内）。"""
        links = await PageExtractor._extract_links(page)
        if not links:
            return "[Links] (none)"
        lines = ["[Links]"]
        lines.extend(links)
        return "\n".join(lines)

    @staticmethod
    async def extract_inputs(page: Any) -> str:
        """提取页面所有输入控件（含 iframe 内）。"""
        inputs = await PageExtractor._extract_inputs(page)
        if not inputs:
            return "[Inputs] (none)"
        lines = ["[Inputs]"]
        lines.extend(inputs)
        return "\n".join(lines)

    @staticmethod
    async def extract_buttons(page: Any) -> str:
        """提取页面所有按钮（含 iframe 内）。"""
        buttons = await PageExtractor._extract_buttons(page)
        if not buttons:
            return "[Buttons] (none)"
        lines = ["[Buttons]"]
        lines.extend(buttons)
        return "\n".join(lines)

    @staticmethod
    async def extract_full(page: Any) -> str:
        """完整提取：标题 + 所有交互元素 + 文本。"""
        return await PageExtractor.extract_snapshot(page)

    # ---- 内部实现 ----

    @staticmethod
    async def _all_frames(root: Any) -> List[Any]:
        """返回主框架 + 所有可访问的 iframe 框架列表。

        Playwright 的 page.frames 返回 [主框架, iframe1, iframe2, ...]。
        跨域 iframe 在访问内容时会抛异常，调用方需自行 try/except。
        """
        frames = [root]
        try:
            if hasattr(root, "frames"):
                # root 是 page；frames[0] 是主框架（即 root 本身），跳过避免重复
                for f in root.frames[1:]:
                    frames.append(f)
        except Exception:
            pass
        return frames

    @staticmethod
    async def _extract_interactive(page: Any) -> List[str]:
        """提取所有可交互元素（含 iframe 内）。"""
        lines: List[str] = []

        links = await PageExtractor._extract_links(page)
        if links:
            lines.extend(links)
            lines.append("")

        inputs = await PageExtractor._extract_inputs(page)
        if inputs:
            lines.extend(inputs)
            lines.append("")

        buttons = await PageExtractor._extract_buttons(page)
        if buttons:
            lines.extend(buttons)
            lines.append("")

        selects = await PageExtractor._extract_selects(page)
        if selects:
            lines.extend(selects)

        # 去除尾部多余空行
        while lines and lines[-1] == "":
            lines.pop()
        return lines

    @staticmethod
    async def _extract_links(page: Any) -> List[str]:
        """提取链接列表：序号 + 文本 + href + CSS 选择器（遍历所有框架）。"""
        lines: List[str] = []
        idx = 0
        for frame in await PageExtractor._all_frames(page):
            try:
                elements = await frame.query_selector_all("a[href]")
            except Exception:
                continue  # 跨域 iframe 不可访问
            for el in elements:
                if idx >= _MAX_LINKS:
                    return lines
                try:
                    text = (await el.inner_text()).strip()
                    href = await el.get_attribute("href") or ""
                    if not text:
                        text = href
                    # 构建稳定的选择器
                    selector = await PageExtractor._build_selector(el, "a", href, text)
                    display_text = text[:60] + "..." if len(text) > 60 else text
                    display_href = href[:80] + "..." if len(href) > 80 else href
                    idx += 1
                    lines.append(f"  {idx}. \"{display_text}\" → {display_href} [{selector}]")
                except Exception:
                    continue
        return lines

    @staticmethod
    async def _extract_inputs(page: Any) -> List[str]:
        """提取输入控件列表：类型 + name + placeholder + CSS 选择器（遍历所有框架）。"""
        lines: List[str] = []
        idx = 0
        for frame in await PageExtractor._all_frames(page):
            try:
                elements = await frame.query_selector_all(
                    "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, "
                    'input[type="search"], input[type="email"], input[type="password"], '
                    'input[type="number"], input[type="tel"], input[type="url"]'
                )
            except Exception:
                continue
            for el in elements:
                if idx >= _MAX_INPUTS:
                    return lines
                try:
                    tag = await el.evaluate("e => e.tagName.toLowerCase()")
                    input_type = await el.get_attribute("type") or "text"
                    name = await el.get_attribute("name") or ""
                    placeholder = await el.get_attribute("placeholder") or ""
                    selector = await PageExtractor._build_selector(el, tag, name, placeholder)
                    parts = [f"  {idx + 1}. [{input_type}]"]
                    if name:
                        parts.append(f"name=\"{name}\"")
                    if placeholder:
                        parts.append(f"placeholder=\"{placeholder}\"")
                    parts.append(f"[{selector}]")
                    idx += 1
                    lines.append(" ".join(parts))
                except Exception:
                    continue
        return lines

    @staticmethod
    async def _extract_buttons(page: Any) -> List[str]:
        """提取按钮列表：文本 + CSS 选择器（遍历所有框架）。"""
        lines: List[str] = []
        idx = 0
        for frame in await PageExtractor._all_frames(page):
            try:
                elements = await frame.query_selector_all(
                    "button, input[type='submit'], input[type='button'], "
                    "[role='button']"
                )
            except Exception:
                continue
            for el in elements:
                if idx >= _MAX_BUTTONS:
                    return lines
                try:
                    text = (await el.inner_text()).strip()
                    tag = await el.evaluate("e => e.tagName.toLowerCase()")
                    selector = await PageExtractor._build_selector(el, tag, text=text)
                    display_text = text[:40] + "..." if len(text) > 40 else text
                    idx += 1
                    if display_text:
                        lines.append(f"  {idx}. \"{display_text}\" [{selector}]")
                    else:
                        lines.append(f"  {idx}. [unnamed {tag}] [{selector}]")
                except Exception:
                    continue
        return lines

    @staticmethod
    async def _extract_selects(page: Any) -> List[str]:
        """提取下拉菜单列表：name + CSS 选择器（遍历所有框架）。"""
        lines: List[str] = []
        idx = 0
        for frame in await PageExtractor._all_frames(page):
            try:
                elements = await frame.query_selector_all("select")
            except Exception:
                continue
            for el in elements:
                if idx >= _MAX_SELECTS:
                    return lines
                try:
                    name = await el.get_attribute("name") or ""
                    selector = await PageExtractor._build_selector(el, "select", name=name)
                    parts = [f"  {idx + 1}. [select]"]
                    if name:
                        parts.append(f"name=\"{name}\"")
                    # 获取选项
                    options = await el.query_selector_all("option")
                    option_texts = []
                    for opt in options[:5]:
                        opt_text = (await opt.inner_text()).strip()
                        opt_value = await opt.get_attribute("value") or ""
                        if opt_text:
                            option_texts.append(f"{opt_text}={opt_value}")
                    if option_texts:
                        parts.append(f"options: {', '.join(option_texts)}")
                    parts.append(f"[{selector}]")
                    idx += 1
                    lines.append(" ".join(parts))
                except Exception:
                    continue
        return lines

    @staticmethod
    async def _extract_content(page: Any) -> str:
        """提取页面主要文本内容（含 iframe 内的内容）。

        对每个框架优先取语义化内容区域（main/article/#content），
        过滤导航/页脚噪声；回退到 body 全文。
        """
        texts: List[str] = []
        # 主框架内容
        main_text = await PageExtractor._extract_frame_text(page)
        if main_text:
            texts.append(main_text)
        # 遍历所有 iframe（同源可访问的）
        try:
            frames = page.frames  # Playwright: page.frames 包含主框架 + 所有 iframe
            for frame in frames[1:]:  # frames[0] 是主框架，跳过
                try:
                    frame_text = await PageExtractor._extract_frame_text(frame)
                    if frame_text and frame_text not in main_text:  # 去重
                        texts.append(f"\n[iframe content]\n{frame_text}")
                except Exception:
                    continue  # 跨域 iframe 会抛异常，跳过
        except Exception:
            pass
        return "\n".join(texts) if texts else ""

    @staticmethod
    async def _extract_frame_text(frame: Any) -> str:
        """从单个 frame（page 或 iframe）提取智能内容文本。

        优先级：
        1. 语义化内容区域（main/article/#content 等）—— 过滤导航噪声
        2. body 全文 —— 兜底
        """
        # 优先尝试语义化内容区域
        for selector in _CONTENT_SELECTORS:
            try:
                el = await frame.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if len(text.strip()) > 100:  # 区域有实质内容才采用
                        return PageExtractor._clean_text(text)
            except Exception:
                continue
        # 回退到 body
        try:
            text = await frame.inner_text("body")
            return PageExtractor._clean_text(text)
        except Exception:
            try:
                # 部分对象（如 DetachedFrame）没有 inner_text，用 evaluate 兜底
                text = await frame.evaluate(
                    "() => document.body ? document.body.innerText : ''"
                )
                return PageExtractor._clean_text(text)
            except Exception:
                return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理文本：折叠多余空白、截断。"""
        # 折叠 3+ 换行为 2 个
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 折叠连续空格
        text = re.sub(r" {2,}", " ", text)
        text = text.strip()
        # 截断
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS] + "\n...(truncated)"
        return text

    @staticmethod
    async def _build_selector(el: Any, tag: str, id_or_name: str = "", text: str = "") -> str:
        """构建一个稳定的 CSS 选择器用于 LLM 操作。

        优先级：id > name > text has-text > tag + nth。
        """
        # 优先使用 id
        el_id = await el.get_attribute("id")
        if el_id and _is_valid_selector_id(el_id):
            return f"#{el_id}"

        # 其次使用 name（适用于 input/select 等）
        if id_or_name and _is_valid_selector_id(id_or_name):
            return f"{tag}[name=\"{id_or_name}\"]"

        # 使用 data-testid
        test_id = await el.get_attribute("data-testid")
        if test_id and _is_valid_selector_id(test_id):
            return f"[data-testid=\"{test_id}\"]"

        # 使用 has-text（适用于按钮/链接）
        if text:
            clean = text[:30].strip()
            # 转义引号
            clean = clean.replace('"', '\\"')
            return f'{tag}:has-text("{clean}")'

        return tag

    # ---- 纯文本版本（不依赖 Playwright Page，用于 Mock 测试）----

    @staticmethod
    def extract_from_html(html: str, url: str = "", title: str = "") -> str:
        """从静态 HTML 提取结构化文本（不依赖 Playwright，用于测试）。

        使用简易 HTML 解析，不要求 Playwright 环境。
        """
        lines: List[str] = []
        lines.append(f"[Page] URL: {url} | Title: {title}")

        # 提取链接
        links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
        if links:
            lines.append("")
            lines.append("[Links]")
            for i, (href, text) in enumerate(links[:_MAX_LINKS]):
                text_clean = re.sub(r"<[^>]+>", "", text).strip()[:60]
                if not text_clean:
                    text_clean = href[:60]
                lines.append(f'  {i + 1}. "{text_clean}" → {href[:80]}')

        # 提取输入
        inputs = re.findall(
            r'<input[^>]*type=["\']?([^"\'>\s]*)[^>]*name=["\']?([^"\'>\s]*)[^>]*placeholder=["\']?([^"\'>]*)[^>]*>',
            html,
        )
        textareas = re.findall(r'<textarea[^>]*name=["\']?([^"\'>\s]*)[^>]*>', html)
        if inputs or textareas:
            lines.append("")
            lines.append("[Inputs]")
            for i, (itype, name, placeholder) in enumerate(inputs[:_MAX_INPUTS]):
                itype = itype or "text"
                parts = [f"  {i + 1}. [{itype}]"]
                if name:
                    parts.append(f'name="{name}"')
                if placeholder:
                    parts.append(f'placeholder="{placeholder}"')
                if name:
                    parts.append(f'[input[name="{name}"]]')
                lines.append(" ".join(parts))
            for i, name in enumerate(textareas[:5]):
                parts = [f"  {len(inputs) + i + 1}. [textarea]"]
                if name:
                    parts.append(f'name="{name}"')
                if name:
                    parts.append(f'[textarea[name="{name}"]]')
                lines.append(" ".join(parts))

        # 提取按钮
        buttons = re.findall(r'<button[^>]*>(.*?)</button>', html, re.DOTALL)
        submit_inputs = re.findall(r'<input[^>]*type=["\']submit["\'][^>]*value=["\']?([^"\'>\s]*)[^>]*>', html)
        if buttons or submit_inputs:
            lines.append("")
            lines.append("[Buttons]")
            for i, text in enumerate(buttons[:_MAX_BUTTONS]):
                text_clean = re.sub(r"<[^>]+>", "", text).strip()[:40]
                lines.append(f'  {i + 1}. "{text_clean}" [button]')
            for i, value in enumerate(submit_inputs[:5]):
                lines.append(f'  {len(buttons) + i + 1}. "{value}" [input[type="submit"]]')

        # 提取 select
        selects = re.findall(r'<select[^>]*name=["\']?([^"\'>\s]*)[^>]*>(.*?)</select>', html, re.DOTALL)
        if selects:
            lines.append("")
            lines.append("[Selects]")
            for i, (name, options_html) in enumerate(selects[:_MAX_SELECTS]):
                options = re.findall(r'<option[^>]*value=["\']?([^"\'>\s]*)[^>]*>(.*?)</option>', options_html, re.DOTALL)
                option_texts = []
                for val, opt_text in options[:5]:
                    opt_clean = re.sub(r"<[^>]+>", "", opt_text).strip()
                    option_texts.append(f"{opt_clean}={val}")
                parts = [f"  {i + 1}. [select]"]
                if name:
                    parts.append(f'name="{name}"')
                if option_texts:
                    parts.append(f"options: {', '.join(option_texts)}")
                lines.append(" ".join(parts))

        # 提取文本内容（先去 script/style，再去标签）
        # 修复 bug：第二个 re.sub 必须操作前一步的结果 text，而非原始 html
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append("")
            lines.append("[Content]")
            truncated = text[:_MAX_CONTENT_CHARS] + "..." if len(text) > _MAX_CONTENT_CHARS else text
            lines.append(truncated)

        return "\n".join(lines)


def _is_valid_selector_id(s: str) -> bool:
    """检查字符串是否可作为 CSS 选择器的 id/name 值。"""
    if not s:
        return False
    # CSS id/name 中不允许某些字符
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_\-.]*$', s))
