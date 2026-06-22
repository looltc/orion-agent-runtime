from typing import List
from orion_agent_runtime.memory.memory_schema import MemoryHit, MemoryItem

# 记忆上下文构建器，负责把长期记忆格式化成适合 prompt 的文本。


def format_memories_for_prompt(memories: List[MemoryHit]) -> str:
    if not memories:
        return "无相关历史记忆"

    lines = []
    for i, hit in enumerate(memories, start=1):
        item = hit.item
        content = str(item.content)[:200]  # 截断记忆内容
        lines.append(f"{i}. [{item.kind}] {content}")
    return "\n".join(lines)
