import asyncio
import uuid

from orion_agent_runtime.core.workflow import run_agent
from orion_agent_runtime.mcp.mcp_config import MCP_SERVERS
from orion_agent_runtime.mcp.mcp_manager import MCPManager
from orion_agent_runtime.tools.registry import register_mcp_tool
from orion_agent_runtime.trace.trace_inspector import format_report, inspect_trace

# 入口只负责交互。


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


def main():
    user_id = "orion"
    mcp_manager = bootstrap_mcp()

    while True:
        user_input = input("> ").strip()
        if not user_input:
            continue
        if user_input in {"exit", "quit"}:
            break

        run_id = str(uuid.uuid4())[:8]
        state = run_agent(user_input, run_id, user_id, mcp_manager)

        print(f"run_id: {run_id}")
        print(f"status: {state.status}")

        if state.status == "done":
            print(f"result: {state.final_output}")
        else:
            print(f"error: {state.error}")
            report = inspect_trace(state)
            print("=== trace_report: ===")
            print(format_report(report))
            print("=" * 20)


if __name__ == "__main__":
    main()
