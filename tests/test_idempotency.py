"""P3: 幂等缓存 + MCP 长连接测试。

核心断言（P3 价值）：
- 同一 (run_id, step_index, tool, arguments) 的重试，真实工具只执行一次
- 不同 run_id / 不同 step_index 不命中缓存（不会错误去重）
- LRU 淘汰、缓存统计正确
- MCPManager 长连接 API（open/close/alive/reconnect）行为正确
"""

import asyncio

import pytest
from pydantic import BaseModel, Field

import orion_agent_runtime.tools  # noqa: F401  注册 add/mul
from orion_agent_runtime.core.executor import execute_step
from orion_agent_runtime.core.idempotency import IdempotencyCache, get_cache, reset_cache
from orion_agent_runtime.core.models import PlanStep, ToolSpec
from orion_agent_runtime.tools.registry import _TOOL_REGISTRY


# ---------- 幂等缓存单元测试 ----------

def test_make_call_id_stable_and_unique():
    a = IdempotencyCache.make_call_id("r1", "add", {"a": 1, "b": 2}, step_index=1)
    b = IdempotencyCache.make_call_id("r1", "add", {"a": 1, "b": 2}, step_index=1)
    c = IdempotencyCache.make_call_id("r2", "add", {"a": 1, "b": 2}, step_index=1)  # 不同 run
    d = IdempotencyCache.make_call_id("r1", "add", {"b": 2, "a": 1}, step_index=1)  # 参数顺序无关
    assert a == b, "相同输入应产生相同 key"
    assert a != c, "不同 run_id 不应命中"
    assert a == d, "参数 dict 顺序无关（sort_keys）"


def test_cache_hit_miss_stats():
    cache = IdempotencyCache()
    cid = IdempotencyCache.make_call_id("r", "add", {"a": 1}, 0)
    assert cache.get(cid) is None
    assert cache.stats()["misses"] == 1
    cache.put(cid, True, 42, None)
    got = cache.get(cid)
    assert got == (True, 42, None)
    assert cache.stats()["hits"] == 1


def test_cache_lru_eviction():
    cache = IdempotencyCache(max_entries=2)
    cache.put("k1", True, 1)
    cache.put("k2", True, 2)
    cache.get("k1")  # k1 最近使用
    cache.put("k3", True, 3)  # 应淘汰 k2（最久未用）
    assert cache.get("k1") is not None
    assert cache.get("k2") is None
    assert cache.get("k3") is not None


# ---------- executor 幂等集成测试 ----------
# 用一个独立的可计数工具，避免改动 frozen 的 ToolSpec（无法 setattr）。
# 直接往 registry 字典塞入可计数的 ToolSpec（dict 可写），handler 内部累加全局计数器。

_COUNTER = {"n": 0}


class _CountArgs(BaseModel):
    a: int = Field(...)


def _counting_handler(a: int) -> int:
    _COUNTER["n"] += 1
    return a


_TOOL_REGISTRY["_count_probe"] = ToolSpec(
    name="_count_probe",
    description="test probe for idempotency counting",
    origin="local",
    args_model=_CountArgs,
    handler=_counting_handler,
)


def test_executor_idempotent_on_retry():
    """核心断言：同一 step 重试，真实 handler 只执行一次。"""
    reset_cache()
    _COUNTER["n"] = 0

    step = PlanStep(tool="_count_probe", arguments={"a": 7})
    # 第一次执行：真实调用
    obs1, trace1 = execute_step(step=step, step_index=1, run_id="run-idem")
    assert trace1.success is True
    assert obs1.result == 7
    assert _COUNTER["n"] == 1, "首次应真实执行"

    # 第二次执行（模拟重试）：应命中缓存，handler 不再被调用
    obs2, trace2 = execute_step(step=step, step_index=1, run_id="run-idem")
    assert trace2.success is True
    assert obs2.result == 7
    assert _COUNTER["n"] == 1, "重试应命中缓存，真实 handler 不再执行"

    assert get_cache().stats()["hits"] >= 1


def test_executor_different_run_not_cached():
    """不同 run_id 的相同调用不应互相去重（跨 run 隔离）。"""
    reset_cache()
    _COUNTER["n"] = 0

    step = PlanStep(tool="_count_probe", arguments={"a": 1})
    execute_step(step=step, step_index=1, run_id="run-A")
    execute_step(step=step, step_index=1, run_id="run-B")
    assert _COUNTER["n"] == 2, "不同 run 应各自真实执行"


def test_executor_different_step_not_cached():
    """同 run 但不同 step_index 的相同调用不应去重（ReAct 轮询场景）。"""
    reset_cache()
    _COUNTER["n"] = 0

    step = PlanStep(tool="_count_probe", arguments={"a": 1})
    execute_step(step=step, step_index=1, run_id="run-C")
    execute_step(step=step, step_index=2, run_id="run-C")
    assert _COUNTER["n"] == 2


def test_executor_different_args_not_cached():
    """不同参数应各自真实执行（缓存 key 含参数）。"""
    reset_cache()
    _COUNTER["n"] = 0

    execute_step(
        step=PlanStep(tool="_count_probe", arguments={"a": 1}), step_index=1, run_id="run-D"
    )
    execute_step(
        step=PlanStep(tool="_count_probe", arguments={"a": 2}), step_index=1, run_id="run-D"
    )
    assert _COUNTER["n"] == 2


# ---------- MCP 长连接测试（不依赖真实 MCP server） ----------

def test_mcp_manager_close_all_clears_connections():
    """close_all 应清空连接字典且不抛异常（无连接时也安全）。"""
    from orion_agent_runtime.mcp.mcp_manager import MCPManager

    mgr = MCPManager(servers=[])
    asyncio.run(mgr.close_all())
    assert mgr._connections == {}


def test_mcp_manager_connect_failure_does_not_crash():
    """单个 server 连接失败不应阻塞 bootstrap（应跳过并继续）。"""
    from orion_agent_runtime.mcp.mcp_manager import MCPManager
    from orion_agent_runtime.mcp.mcp_config import MCPServerConfig

    bad_cfg = MCPServerConfig(
        name="ghost", command="definitely-not-a-real-cmd-xyz", args=[]
    )
    mgr = MCPManager(servers=[bad_cfg])
    # connect_all 不应抛异常
    asyncio.run(mgr.connect_all())
    assert "ghost" not in mgr._connections, "连接失败的 server 不应保留连接"
    assert mgr.list_tools() == []
    asyncio.run(mgr.close_all())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])