"""PageExtractor 单元测试。

验证 extract_from_html 的结构化提取正确性（不依赖 Playwright）。
"""

import pytest

from orion_agent_runtime.capabilities.browser.extractor import PageExtractor


# ---- 测试用 HTML 样本 ----

SIMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Welcome</h1>
  <p>This is a paragraph of content.</p>
  <a href="/home">Home</a>
  <a href="/about">About Us</a>
  <input id="search" type="text" name="q" placeholder="Search...">
  <textarea name="comment"></textarea>
  <button id="submit-btn">Submit</button>
  <button>Cancel</button>
  <input type="submit" value="Save">
  <select name="lang">
    <option value="en">English</option>
    <option value="zh">中文</option>
  </select>
</body>
</html>
"""


def test_extract_from_html_basic():
    """extract_from_html 应返回结构化文本，包含 Page/Links/Inputs/Buttons/Content 段。"""
    result = PageExtractor.extract_from_html(
        SIMPLE_HTML, url="https://example.com", title="Test Page"
    )

    assert "[Page]" in result
    assert "https://example.com" in result
    assert "Test Page" in result


def test_extract_from_html_links():
    """应提取所有链接。"""
    result = PageExtractor.extract_from_html(SIMPLE_HTML, url="https://x.com")
    assert "[Links]" in result
    assert "/home" in result
    assert "/about" in result
    assert "Home" in result
    assert "About Us" in result


def test_extract_from_html_inputs():
    """应提取输入控件（input + textarea）。"""
    result = PageExtractor.extract_from_html(SIMPLE_HTML, url="https://x.com")
    assert "[Inputs]" in result
    assert "name=\"q\"" in result
    assert "placeholder=\"Search...\"" in result
    assert "textarea" in result.lower()


def test_extract_from_html_buttons():
    """应提取按钮（button + submit input）。"""
    result = PageExtractor.extract_from_html(SIMPLE_HTML, url="https://x.com")
    assert "[Buttons]" in result
    assert "Submit" in result
    assert "Cancel" in result
    assert "Save" in result


def test_extract_from_html_selects():
    """应提取下拉菜单及其选项。"""
    result = PageExtractor.extract_from_html(SIMPLE_HTML, url="https://x.com")
    assert "[Selects]" in result
    assert "name=\"lang\"" in result
    assert "English" in result
    assert "en" in result


def test_extract_from_html_content():
    """应提取页面纯文本内容，去除所有 HTML 标签。"""
    result = PageExtractor.extract_from_html(SIMPLE_HTML, url="https://x.com")
    assert "[Content]" in result
    assert "Welcome" in result
    assert "paragraph of content" in result
    # HTML 标签不应出现在内容中
    assert "<html>" not in result.split("[Content]")[1]
    assert "<body>" not in result.split("[Content]")[1]


def test_extract_from_html_empty():
    """空 HTML 应仍返回基本结构。"""
    result = PageExtractor.extract_from_html("", url="", title="")
    assert "[Page]" in result


def test_extract_from_html_content_truncation():
    """超长内容应被截断。"""
    long_html = f"<html><body>{'x' * 10000}</body></html>"
    result = PageExtractor.extract_from_html(long_html, url="https://x.com")
    content_section = result.split("[Content]")[1] if "[Content]" in result else ""
    assert "..." in content_section  # 截断标记


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
