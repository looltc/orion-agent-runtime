import asyncio
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
    remote_name: str


class MCPManager:
    def __init__(self, servers):
        self.servers = servers
        self._tools: dict[str, MCPToolSpec] = {}

    async def _connect_one_and_list_tools(self, cfg):
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tool_resp = await session.list_tools()

                for tool in tool_resp.tools:
                    tool_key = f"{cfg.name}.{tool.name}"
                    self._tools[tool_key] = MCPToolSpec(
                        name=tool_key,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                        server_name=cfg.name,
                        remote_name=tool.name,
                    )

    async def connect_all(self) -> None:
        for cfg in self.servers:
            await self._connect_one_and_list_tools(cfg)

    def list_tools(self):
        return list(self._tools.values())

    def build_tool_catalog_text(self) -> str:
        lines = []
        for tool in self.list_tools():
            lines.append(f"- name: {tool.name}")
            lines.append(f"  description: {tool.description}")
            lines.append(f"  input_schema: {tool.input_schema}")
        return "\n".join(lines)

    async def call_tool_async(self, namespaced_tool_name: str, arguments: dict[str, Any]):
        spec = self._tools[namespaced_tool_name]
        cfg = next(s for s in self.servers if s.name == spec.server_name)

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(spec.remote_name, arguments)