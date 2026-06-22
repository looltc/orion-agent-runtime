"""SemanticStore —— 事实/偏好知识（去语境化，持久化）。

V2 改造目标（设计文档第 4 节 memory.Semantic）：
- 存储从对话/episode 中抽取的稳定事实与用户偏好
- 去语境化（不绑定特定 run，可跨任务复用）
- 预留 extract hook，供后续 LLM 自动抽取（本次不接 LLM）

实现：复用 MemoryStore（layer="semantic"），kind 用 fact/preference 区分。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from orion_agent_runtime.memory.memory_schema import MemoryItem
from orion_agent_runtime.memory.memory_store import MemoryStore


class SemanticStore:
    """事实/偏好知识记忆（封装 MemoryStore 的 semantic 层）。"""

    LAYER = "semantic"

    def __init__(self, store: Optional[MemoryStore] = None, db_path: Optional[Path] = None):
        if store is not None:
            self.store = store
        else:
            self.store = MemoryStore(db_path=db_path)

    def remember_fact(
        self,
        *,
        user_id: str,
        fact: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        item = MemoryItem(
            user_id=user_id,
            kind="fact",
            content=fact,
            metadata=metadata or {},
            layer=self.LAYER,
        )
        return self.store.add(item)

    def remember_preference(
        self,
        *,
        user_id: str,
        preference: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        item = MemoryItem(
            user_id=user_id,
            kind="preference",
            content=preference,
            metadata=metadata or {},
            layer=self.LAYER,
        )
        return self.store.add(item)

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        kinds: Optional[List[str]] = None,
    ) -> List[MemoryItem]:
        """按相关性检索 semantic 记忆。"""
        hits = self.store.search_related(
            user_id=user_id,
            query=query,
            limit=limit,
            kinds=kinds,
            layers=[self.LAYER],
        )
        return [h.item for h in hits]

    def recall_all(self, user_id: str, limit: int = 100) -> List[MemoryItem]:
        return self.store.search_by_user(user_id=user_id, limit=limit, layer=self.LAYER)

    def summarize(self, user_id: str, limit: int = 10) -> str:
        items = self.recall_all(user_id, limit=limit)
        if not items:
            return ""
        parts = []
        for it in items:
            parts.append(f"[{it.kind}]:{it.content[:200]}")
        return "\n".join(parts)

    def forget(self, *, user_id: Optional[str] = None, older_than_days: Optional[int] = None) -> int:
        return self.store.forget(user_id=user_id, layer=self.LAYER, older_than_days=older_than_days)

    # ---- 抽取 hook（预留，本次不接 LLM）----
    def register_extractor(self, extractor: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> None:
        """注册一个事实抽取器（输入文本+上下文，输出 [{kind, content, metadata}, ...]）。

        V2 预留接口：后续可接入 LLM 从对话/episode 中自动抽取 semantic 事实。
        本次不实现自动抽取，仅保留注册机制。
        """
        self._extractor = extractor

    _extractor: Optional[Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]] = None
