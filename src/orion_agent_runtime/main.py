import asyncio
import os
import uuid

from orion_agent_runtime.config import get_config
from orion_agent_runtime.core.workflow import run_agent
from orion_agent_runtime.mcp.mcp_config import MCP_SERVERS
from orion_agent_runtime.mcp.mcp_manager import MCPManager
from orion_agent_runtime.reporter import CliReporter, set_reporter
from orion_agent_runtime.tools.registry import register_mcp_tool
from orion_agent_runtime.trace.trace_inspector import format_report, inspect_trace

# 入口只负责交互。
#
# V2 架构演进：支持 ORION_RUNTIME=v1|v2 开关
#   v1（默认）：原有同步 workflow（core/workflow.run_agent），零改动保留
#   v2       ：事件驱动 Runtime（runtime.AgentRuntime）


def bootstrap_mcp() -> MCPManager:
    mcp_manager = MCPManager(MCP_SERVERS)
    asyncio.run(mcp_manager.connect_all())

    for tool in mcp_manager.list_tools():
        register_mcp_tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            server_name=tool.server_name,
            remote_name=tool.remote_name,
        )

    return mcp_manager


def bootstrap_browser() -> None:
    """注册浏览器能力到全局 CapabilityRegistry（V1 模式用）。

    V2 模式由 Kernel.start() 自动注册，无需手动调用。
    """
    from orion_agent_runtime.capabilities.base import get_registry
    from orion_agent_runtime.capabilities.browser.capability import (
        create_browser_capability,
    )

    registry = get_registry()
    if not registry.has("browser"):
        cap = create_browser_capability()
        registry.register(cap)


def main():
    runtime_mode = get_config().runtime_mode
    if runtime_mode == "v2":
        _main_v2()
    else:
        _main_v1()


def _main_v1() -> None:
    """V1：原有同步 workflow 入口（完全保留，零改动）。"""
    set_reporter(CliReporter())  # CLI 进度可视化
    user_id = "orion"
    mcp_manager = bootstrap_mcp()
    bootstrap_browser()  # 注册浏览器能力到全局 CapabilityRegistry

    try:
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input in {"exit", "quit"}:
                break

            run_id = str(uuid.uuid4())[:8]
            state = run_agent(user_input, run_id, user_id, mcp_manager)

            if state.status in {"done", "goal_achieved"}:
                print(f"result: {state.final_output}")
            else:
                print(f"error: {state.error}")
                report = inspect_trace(state)
                print("=== trace_report: ===")
                print(format_report(report))
                print("=" * 20)
    finally:
        # P3：优雅关闭 MCP 长连接，避免子进程残留
        asyncio.run(mcp_manager.close_all())


def _main_v2() -> None:
    """V2：事件驱动 Runtime 入口（ORION_RUNTIME=v2 时启用）。

    复用 MCP bootstrap，通过 AgentRuntime 跑事件驱动闭环。
    循环内每个 goal 独立 Kernel 生命周期（start → run → shutdown）。
    """
    from orion_agent_runtime.kernel import Kernel
    from orion_agent_runtime.runtime import AgentRuntime

    user_id = "orion"
    mcp_manager = bootstrap_mcp()

    try:
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input in {"exit", "quit"}:
                break

            kernel = Kernel()
            asyncio.run(kernel.start())
            try:
                runtime = AgentRuntime(kernel)
                result = asyncio.run(runtime.run(
                    goal=user_input,
                    user_id=user_id,
                    mcp_manager=mcp_manager,
                ))
                print(f"run_id: {result.run_id}")
                print(f"task_id: {result.task_id}")
                print(f"status: {result.status}")
                if result.status in {"done", "goal_achieved"}:
                    print(f"result: {result.final_output}")
                else:
                    print(f"error: {result.error}")
            finally:
                asyncio.run(kernel.shutdown())
    finally:
        asyncio.run(mcp_manager.close_all())


if __name__ == "__main__":
    main()
