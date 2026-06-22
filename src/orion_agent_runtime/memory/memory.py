"""MemoryManager —— 三层记忆门面（V2 架构）。

设计文档第 4 节 memory 模块：
  Working / Episodic / Semantic 三层记忆。

接口（设计文档第 4 节）：
- put(key, value)
- search(query)
- summarize(task_id)
- forget(policy)

V2 改造：
- MemoryManager 聚合 WorkingStore + EpisodicStore + SemanticStore
- 保留旧接口（recall / recall_related / remember_task_summary / remember_fact / remember_text）
  以保证 V1 的 core/workflow.py、core/planner.py 零改动
- 新增三层门面接口 put / search / summarize / forget
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from orion_agent_runtime.memory.episodic.episodic_store import EpisodicStore
from orion_agent_runtime.memory.memory_schema import MemoryItem
from orion_agent_runtime.memory.memory_store import MemoryStore
from orion_agent_runtime.memory.semantic.semantic_store import SemanticStore
from orion_agent_runtime.memory.working.working_store import WorkingStore

# 记忆层职责：
# - 运行前取记忆（recall / search）
# - 运行中维护 working 上下文（put working）
# - 运行后写记忆（remember_task_summary / put episodic）


class MemoryManager:
    """三层记忆门面：working（即时）+ episodic（经历）+ semantic（知识）。

    三层共享底层 MemoryStore（episodic + semantic 同一 SQLite DB，working 进程内）。
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        # 共享底层存储（episodic + semantic 同库不同 layer）
        self.store = MemoryStore(db_path=db_path)
        self.working = WorkingStore()
        self.episodic = EpisodicStore(store=self.store)
        self.semantic = SemanticStore(store=self.store)

    # ====================================================================
    # V2 三层门面接口（设计文档第 4 节 put/search/summarize/forget）
    # ====================================================================

    def put(
        self,
        key: str,
        value: Any,
        *,
        layer: str = "working",
        user_id: str = "default",
        kind: str = "tool_result",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """写入一条记忆到指定层。

        - layer="working"：写入进程内 working（key=run_id/task_id，value 任意 dict）
        - layer="episodic"：写入结构化 episode（key 当作 summary）
        - layer="semantic"：写入事实/偏好（key 当作 content）

        返回：working 层返回 None；持久化层返回新 item id。
        """
        if layer == "working":
            # working 的 value 必须可序列化；强制 dict 包装
            item = value if isinstance(value, dict) else {"content": value, "kind": kind}
            self.working.put(key, str(item.get("content", id(value))), item)
            return None
        if layer == "episodic":
            content = key if isinstance(value, str) else str(value)
            return self.episodic.remember_episode(
                user_id=user_id,
                run_id=metadata.get("run_id", key) if metadata else key,
                summary=content,
                steps=metadata.get("steps") if metadata else None,
                status=metadata.get("status", "done") if metadata else "done",
                iterations=metadata.get("iterations", 0) if metadata else 0,
                extra_metadata=metadata,
            )
        if layer == "semantic":
            return self.semantic.remember_fact(
                user_id=user_id, fact=key, metadata=metadata or {}
            )
        raise ValueError(f"unknown memory layer: {layer}")

    def search(
        self,
        query: str,
        *,
        user_id: str = "default",
        layers: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """跨层检索记忆（默认搜 episodic + semantic；working 不参与文本检索）。"""
        if layers is None:
            layers = ["episodic", "semantic"]
        hits = self.store.search_related(
            user_id=user_id,
            query=query,
            limit=limit,
            layers=layers,
        )
        return [h.item for h in hits]

    def summarize(self, task_id: Optional[str] = None, *, user_id: str = "default") -> str:
        """汇总记忆为文本摘要（供 planner 上下文）。

        task_id 给定时优先返回该 run 的 working 上下文 + episodic；
        否则返回最近 episodic + 全部 semantic。
        """
        parts: List[str] = []
        if task_id:
            w = self.working.summarize(task_id)
            if w:
                parts.append(f"[Working]\n{w}")
            e = self.episodic.summarize(user_id, run_id=task_id)
            if e:
                parts.append(f"[Episodic]\n{e}")
        else:
            e = self.episodic.summarize(user_id)
            if e:
                parts.append(f"[Episodic]\n{e}")
        s = self.semantic.summarize(user_id)
        if s:
            parts.append(f"[Semantic]\n{s}")
        return "\n\n".join(parts)

    def forget(
        self,
        *,
        layer: str,
        user_id: Optional[str] = None,
        older_than_days: Optional[int] = None,
    ) -> int:
        """按策略遗忘记忆（清理）。working 层清内存，持久化层删行。"""
        if layer == "working":
            self.working.clear(user_id)
            return self.working.size()
        if layer == "episodic":
            return self.episodic.forget(user_id=user_id, older_than_days=older_than_days)
        if layer == "semantic":
            return self.semantic.forget(user_id=user_id, older_than_days=older_than_days)
        raise ValueError(f"unknown memory layer: {layer}")

    # ====================================================================
    # V1 兼容接口（core/workflow.py / core/planner.py 继续使用，零改动）
    # ====================================================================

    def recall(self, user_id: str):
        """V1 兼容：返回该 user 最近记忆项。"""
        return self.store.search_by_user(user_id)

    def recall_related(self, user_id: str, query: str, limit: int = 5):
        """V1 兼容：相关性检索（planner 调用）。"""
        return self.store.search_related(user_id=user_id, query=query, limit=limit)

    def remember_task_summary(
        self, user_id: str, summary: str, metadata: dict | None = None
    ):
        """V1 兼容：记录任务摘要（写入 episodic 层）。"""
        item = MemoryItem(
            user_id=user_id,
            kind="task_summary",
            content=summary,
            metadata=metadata or {},
            layer="episodic",
        )
        return self.store.add(item)

    def remember_fact(self, user_id: str, fact: str, metadata: dict | None = None):
        """V1 兼容：记录事实（写入 semantic 层）。"""
        item = MemoryItem(
            user_id=user_id,
            kind="fact",
            content=fact,
            metadata=metadata or {},
            layer="semantic",
        )
        return self.store.add(item)

    def remember_text(
        self,
        user_id: str,
        kind: str,
        content: str,
        metadata: dict | None = None,
    ):
        """V1 兼容：通用写入（默认 episodic 层）。"""
        item = MemoryItem(
            user_id=user_id,
            kind=kind,
            content=content,
            metadata=metadata or {},
            layer="episodic",
        )
        return self.store.add(item)
