"""EpisodicStore —— 事件经历记忆（结构化 episode）。

V2 改造目标（设计文档第 4 节 memory.Episodic）：
- 按结构化 episode 组织，而非 V1 的纯文本 task_summary
- 每个 episode 绑定 run_id + 步骤序列 + 成败
- 支持按 run_id 回溯、按相关性检索

实现：复用 MemoryStore（layer="episodic"），在其上提供 episode 语义封装。
跨进程持久化（SQLite），与 V1 memory.db 同库。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from orion_agent_runtime.memory.memory_schema import MemoryItem
from orion_agent_runtime.memory.memory_store import MemoryStore


class EpisodicStore:
    """结构化 episode 记忆（封装 MemoryStore 的 episodic 层）。

    每条 episode 的 metadata 约定字段：
    - run_id：所属运行
    - steps：步骤摘要列表（[{"tool":..., "result":...}, ...]）
    - status：done/failed/goal_achieved/paused
    - iterations：迭代轮数
    """

    LAYER = "episodic"

    def __init__(self, store: Optional[MemoryStore] = None, db_path: Optional[Path] = None):
        # 允许注入共享 store（与 semantic 共用同一 DB 连接/路径）
        if store is not None:
            self.store = store
        else:
            self.store = MemoryStore(db_path=db_path)

    def remember_episode(
        self,
        *,
        user_id: str,
        run_id: str,
        summary: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        status: str = "done",
        iterations: int = 0,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """记录一次任务运行作为一个 episode。返回新 item id。"""
        meta = {
            "run_id": run_id,
            "steps": steps or [],
            "status": status,
            "iterations": iterations,
        }
        if extra_metadata:
            meta.update(extra_metadata)
        item = MemoryItem(
            user_id=user_id,
            kind="task_summary",
            content=summary,
            metadata=meta,
            layer=self.LAYER,
        )
        return self.store.add(item)

    def recall_by_run(self, run_id: str, user_id: str) -> List[MemoryItem]:
        """按 run_id 回溯某次运行的 episode（遍历该 user 的 episodic 项过滤）。"""
        all_items = self.store.search_by_user(user_id=user_id, limit=500, layer=self.LAYER)
        return [it for it in all_items if it.metadata.get("run_id") == run_id]

    def recall_recent(self, user_id: str, limit: int = 10) -> List[MemoryItem]:
        """最近 N 个 episode（按时间倒序）。"""
        return self.store.search_by_user(user_id=user_id, limit=limit, layer=self.LAYER)

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """按相关性检索 episodic 记忆，返回 MemoryItem 列表。"""
        hits = self.store.search_related(
            user_id=user_id,
            query=query,
            limit=limit,
            layers=[self.LAYER],
        )
        return [h.item for h in hits]

    def summarize(self, user_id: str, run_id: Optional[str] = None) -> str:
        """把 episodic 记忆压成文本摘要（供 planner 上下文）。"""
        if run_id:
            items = self.recall_by_run(run_id, user_id)
        else:
            items = self.recall_recent(user_id, limit=5)
        if not items:
            return ""
        parts = []
        for it in items:
            tail = it.content[:200]
            parts.append(f"[run={it.metadata.get('run_id','?')} status={it.metadata.get('status','?')}]:{tail}")
        return "\n".join(parts)

    def forget(self, *, user_id: Optional[str] = None, older_than_days: Optional[int] = None) -> int:
        """按条件删除 episodic 记忆。"""
        return self.store.forget(user_id=user_id, layer=self.LAYER, older_than_days=older_than_days)
