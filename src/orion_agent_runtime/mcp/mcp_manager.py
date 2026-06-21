import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# MCP 连接管理器。
#
# P3 改造：从"每次调用重新 spawn 子进程"升级为"长连接复用"。
#   - connect_all 时为每个 server 建立并保持 stdio 会话
#   - call_tool_async 复用已建立的会话，避免每次调用的子进程启动开销
#   - 连接失效时自动重连；重连仍失败则降级为短连接（原行为）作兜底
#
# 连接生命周期：
#   connect_all() 建立长连接 → call_tool_async() 复用 → close_all() 优雅关闭


@dataclass
class MCPToolSpec:
    name: str
    description: str
    input_schema: dict
    server_name: str
    remote_name: str


@dataclass
class _LiveConnection:
    """一个保持活跃的 MCP 长连接（session + 其底层上下文）。"""

    server_name: str
    # stdio_client 的上下文管理器与进入后产生的 session
    _cm_ctx: Any = None
    session: Optional[ClientSession] = None

    async def open(self, cfg) -> None:
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env
        )
        # 不立即退出 stdio_client 上下文，以保持子进程与流存活
        self._cm_ctx = stdio_client(params)
        read_stream, write_stream = await self._cm_ctx.__aenter__()
        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()
        await self.session.initialize()

    async def close(self) -> None:
        for closer in (self.session, self._cm_ctx):
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer.__aexit__(None, None, None)
        self.session = None
        self._cm_ctx = None

    @property
    def alive(self) -> bool:
        return self.session is not None


class MCPManager:
    def __init__(self, servers):
        self.servers = servers
        self._tools: Dict[str, MCPToolSpec] = {}
        # server_name → 长连接
        self._connections: Dict[str, _LiveConnection] = {}

    async def _build_params(self, cfg) -> StdioServerParameters:
        return StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env)

    async def _connect_one_and_list_tools(self, cfg) -> None:
        """建立长连接并列出工具（失败则跳过该 server，不阻塞其他 server）。"""
        conn = _LiveConnection(server_name=cfg.name)
        try:
            await conn.open(cfg)
            self._connections[cfg.name] = conn

            tool_resp = await conn.session.list_tools()
            for tool in tool_resp.tools:
                tool_key = f"{cfg.name}.{tool.name}"
                self._tools[tool_key] = MCPToolSpec(
                    name=tool_key,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                    server_name=cfg.name,
                    remote_name=tool.name,
                )
        except Exception as e:
            # 连接失败不应让整个 bootstrap 崩溃；记录后继续
            print(f"[MCP] failed to connect server '{cfg.name}': {e}")
            with contextlib.suppress(Exception):
                await conn.close()

    async def connect_all(self) -> None:
        for cfg in self.servers:
            await self._connect_one_and_list_tools(cfg)

    async def close_all(self) -> None:
        """优雅关闭所有长连接。进程退出前应调用。"""
        for conn in self._connections.values():
            with contextlib.suppress(Exception):
                await conn.close()
        self._connections.clear()

    def list_tools(self):
        return list(self._tools.values())

    def build_tool_catalog_text(self) -> str:
        lines = []
        for tool in self.list_tools():
            lines.append(f"- name: {tool.name}")
            lines.append(f"  description: {tool.description}")
            lines.append(f"  input_schema: {tool.input_schema}")
        return "\n".join(lines)

    async def _reconnect(self, server_name: str) -> Optional[_LiveConnection]:
        """重连指定 server；成功返回新连接，失败返回 None。"""
        cfg = next((s for s in self.servers if s.name == server_name), None)
        if cfg is None:
            return None
        old = self._connections.pop(server_name, None)
        if old is not None:
            with contextlib.suppress(Exception):
                await old.close()
        conn = _LiveConnection(server_name=server_name)
        try:
            await conn.open(cfg)
            self._connections[server_name] = conn
            return conn
        except Exception as e:
            print(f"[MCP] reconnect failed for '{server_name}': {e}")
            with contextlib.suppress(Exception):
                await conn.close()
            return None

    async def _call_via_short_connection(self, spec, cfg, arguments):
        """降级路径：用一次性短连接调用（原 P3 前的行为），作为长连接失败兜底。"""
        params = await self._build_params(cfg)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(spec.remote_name, arguments)

    async def call_tool_async(self, namespaced_tool_name: str, arguments: dict):
        spec = self._tools[namespaced_tool_name]
        cfg = next(s for s in self.servers if s.name == spec.server_name)

        conn = self._connections.get(spec.server_name)
        if conn is None or not conn.alive:
            conn = await self._reconnect(spec.server_name)

        # 优先用长连接
        if conn is not None and conn.alive:
            try:
                return await conn.session.call_tool(spec.remote_name, arguments)
            except Exception as e:
                # 长连接调用失败：尝试一次重连后重试
                print(f"[MCP] long-conn call failed ('{spec.server_name}'): {e}; reconnecting")
                conn = await self._reconnect(spec.server_name)
                if conn is not None and conn.alive:
                    return await conn.session.call_tool(spec.remote_name, arguments)

        # 兜底：短连接
        return await self._call_via_short_connection(spec, cfg, arguments)
