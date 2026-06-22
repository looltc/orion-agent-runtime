from orion_agent_runtime.tools.math_tool import add, mul
from orion_agent_runtime.tools.knowledge_tool import knowledge_search

# 导入 browser_tools 触发 @register_tool 装饰器执行（注册浏览器工具到 _TOOL_REGISTRY）。
# 浏览器能力层（BrowserCapability）由 Kernel.start() / bootstrap_browser() 注册，
# 此处仅注册 LLM 可调用的工具 wrapper。
import orion_agent_runtime.tools.browser_tools  # noqa: F401
