"""Working memory —— 会话级即时上下文（进程内，不落盘）。

设计文档第 4 节 memory 模块：Working 记忆负责当前会话的即时上下文。
对应 V1 中散落在 react_loop._compress_history + AgentState.history_summary 的 working 语义，
V2 统一收编进 memory 包。

特点：
- 进程内 OrderedDict，容量上限 + FIFO 淘汰
- 不持久化（进程重启即失效，由 episodic 层负责固化）
- 提供 context() 供 planner 拼接最近上下文
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional


class WorkingStore:
    """进程内 LRU + FIFO 淘汰的会话上下文存储。

    每个 key（通常是 run_id 或 task_id）维护一个上下文 deque。
    """

    def __init__(self, capacity_per_key: int = 50, max_keys: int = 64) -> None:
        self._capacity = capacity_per_key
        self._max_keys = max_keys
        # key -> OrderedDict[item_id, item]
        self._data: "OrderedDict[str, OrderedDict[str, Dict[str, Any]]]" = OrderedDict()

    def put(self, key: str, item_id: str, item: Dict[str, Any]) -> None:
        """写入一条 working 记忆。"""
        bucket = self._data.get(key)
        if bucket is None:
            bucket = OrderedDict()
            self._data[key] = bucket
        # 已存在则先弹出再追加（移到末尾，LRU 语义）
        if item_id in bucket:
            bucket.pop(item_id)
        bucket[item_id] = item
        # 超容量 FIFO 淘汰
        while len(bucket) > self._capacity:
            bucket.popitem(last=False)
        # key 维度也 LRU 一下
        self._data.move_to_end(key)
        while len(self._data) > self._max_keys:
            self._data.popitem(last=False)

    def get(self, key: str, item_id: str) -> Optional[Dict[str, Any]]:
        bucket = self._data.get(key)
        if bucket is None:
            return None
        return bucket.get(item_id)

    def context(self, key: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """返回某 key 的全部上下文项（按写入顺序）。limit 截取最近 N 条。"""
        bucket = self._data.get(key)
        if bucket is None:
            return []
        items = list(bucket.values())
        if limit is not None:
            items = items[-limit:]
        return items

    def summarize(self, key: str) -> str:
        """把 working 上下文压成一段文本摘要（供 history_summary 复用）。

        纯文本拼接，避免额外 LLM 开销；后续可替换为 LLM 摘要。
        """
        items = self.context(key)
        if not items:
            return ""
        parts = []
        for it in items:
            content = str(it.get("content", ""))[:200]
            parts.append(f"[{it.get('kind', 'item')}]:{content}")
        return "\n".join(parts)

    def clear(self, key: Optional[str] = None) -> None:
        """清空指定 key 或全部。"""
        if key is None:
            self._data.clear()
        else:
            self._data.pop(key, None)

    def size(self, key: Optional[str] = None) -> int:
        if key is None:
            return sum(len(b) for b in self._data.values())
        bucket = self._data.get(key)
        return len(bucket) if bucket else 0
