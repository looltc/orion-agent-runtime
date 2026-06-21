"""工具调用幂等缓存（P3）。

闭环可靠性的核心：同一工具调用（相同 tool+arguments）被重试时，真实副作用只发生一次。
Loop Engineering 原则："对每个工具调用分配稳定键，从而区分重试与重复。"

实现：以 (tool, frozenset(arguments)) 的稳定 hash 作为 call_id，
进程内 LRU 缓存结果。重试命中缓存 → 直接返回，不触发真实执行。

注意：
- 仅对"相同输入必有相同输出"的调用幂等（纯函数式工具、读操作）。
- 写操作（写文件、发请求）幂等性由工具自身保证；本缓存避免的是"同一调用被重复触发"。
- 缓存按 run 隔离（run_id 纳入 key），跨 run 不复用，避免脏数据。
"""

import hashlib
import json
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class IdempotencyCache:
    """进程内 LRU 幂等缓存。"""

    def __init__(self, max_entries: int = 256):
        self._store: "OrderedDict[str, Tuple[bool, Any, Optional[str]]]" = OrderedDict()
        self.max_entries = max_entries
        # 统计：供可观测性与测试验证
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_call_id(
        run_id: str, tool: str, arguments: Dict[str, Any], step_index: int = 0
    ) -> str:
        """生成稳定的调用键。

        step_index 纳入 key：ReAct 循环中同一工具相同参数在不同轮次可能是有意的
        （如轮询），不强制去重。真正的重试是"同一步内相同调用被重复执行"。
        """
        try:
            args_repr = json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_repr = repr(arguments)
        payload = f"{run_id}|{step_index}|{tool}|{args_repr}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, call_id: str) -> Optional[Tuple[bool, Any, Optional[str]]]:
        """返回缓存的 (success, result, error)；未命中返回 None。"""
        if call_id in self._store:
            self._store.move_to_end(call_id)
            self.hits += 1
            return self._store[call_id]
        self.misses += 1
        return None

    def put(
        self, call_id: str, success: bool, result: Any, error: Optional[str] = None
    ) -> None:
        self._store[call_id] = (success, result, error)
        self._store.move_to_end(call_id)
        # LRU 淘汰
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, int]:
        return {
            "entries": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
        }


# 模块级单例，供 executor 使用（整个进程共享）
_default_cache = IdempotencyCache()


def get_cache() -> IdempotencyCache:
    return _default_cache


def reset_cache() -> None:
    """测试用：重置默认缓存。"""
    global _default_cache
    _default_cache = IdempotencyCache()
