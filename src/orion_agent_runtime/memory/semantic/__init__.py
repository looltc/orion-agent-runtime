"""Semantic memory 子包（事实/偏好知识，去语境化，持久化）。

设计文档第 4 节 memory 模块：Semantic 记录"去语境化的事实/偏好"。
对应 V1 kind="fact"/"preference" 的预留槽位（remember_fact 零调用），
V2 提供真正的写入/检索/抽取 hook。
"""

from orion_agent_runtime.memory.semantic.semantic_store import SemanticStore

__all__ = ["SemanticStore"]
