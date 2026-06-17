from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: list[str]
    env: Optional[dict[str, str]] = None


MCP_SERVERS = [
    MCPServerConfig(
        name="filesystem",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "C:\\Users\\22963\\Desktop",
            "C:\\Users\\22963\\Downloads",
        ],
        env=None,
    ),
]
