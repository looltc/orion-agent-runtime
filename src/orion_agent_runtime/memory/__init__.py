"""Memory 子系统（V2 三层记忆）。

三层结构（设计文档第 4 节）：
- working：会话级即时上下文（进程内）
- episodic：事件经历（持久化，按 run/时间组织）
- semantic：事实/偏好知识（持久化，去语境化）

公共 API：
- MemoryManager：三层门面（V1 兼容 + V2 put/search/summarize/forget）
- WorkingStore / EpisodicStore / SemanticStore：分层直接访问
- MemoryItem / MemoryHit / MemoryLayer：数据模型
"""

from orion_agent_runtime.memory.episodic.episodic_store import EpisodicStore
from orion_agent_runtime.memory.memory import MemoryManager
from orion_agent_runtime.memory.memory_schema import MemoryItem, MemoryHit, MemoryLayer
from orion_agent_runtime.memory.memory_store import MemoryStore
from orion_agent_runtime.memory.semantic.semantic_store import SemanticStore
from orion_agent_runtime.memory.working.working_store import WorkingStore

__all__ = [
    "MemoryManager",
    "MemoryStore",
    "WorkingStore",
    "EpisodicStore",
    "SemanticStore",
    "MemoryItem",
    "MemoryHit",
    "MemoryLayer",
]
