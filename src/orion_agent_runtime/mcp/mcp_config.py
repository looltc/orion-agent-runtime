"""MCP 服务器配置。

改造自硬编码 Windows 路径：filesystem 允许目录改由
`ORION_MCP_FILESYSTEM_DIRS` 环境变量（逗号分隔）配置，未配置时该 server 不启用，
避免在他人机器上因路径不存在而启动失败。
"""

from dataclasses import dataclass
from typing import Optional

from orion_agent_runtime.config import get_config


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: list
    env: Optional[dict] = None


def build_mcp_servers() -> list:
    """根据 config 构造 MCP 服务器列表。"""
    servers: list = []
    cfg = get_config()
    dirs = cfg.mcp_filesystem_dirs
    if dirs:
        servers.append(
            MCPServerConfig(
                name="filesystem",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", *dirs],
                env=None,
            )
        )
    return servers


# 向后兼容：保留模块级常量，main.py 仍可 `from ... import MCP_SERVERS`。
MCP_SERVERS = build_mcp_servers()
