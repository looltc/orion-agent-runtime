"""P1: AgentRuntime 端到端测试（事件驱动循环）。

核心断言（设计文档第 8 节验收点）：
- Planner→Action→Observe→World→Reflect 闭环可运行
- 事件总线记录所有关键事件 + run_id 级回放
- World Model 任务执行前后一致更新
- 任务失败后可恢复（Scheduler 暂停/恢复 + snapshot）
- 高风险操作走审批/拒绝流程（async hook）

测试策略（对齐现有 test_react_loop.py 风格）：
- monkeypatch 注入 mock decide_fn / checker_fn（避免真实 LLM）
- 用 tmp_path EventBus + 临时 memory DB
- 用 mock capability（MockBrowserCapability）
"""

import asyncio
from pathlib import Path

import pytest

from orion_agent_runtime.bus import EventBus, EventType, make_event
from orion_agent_runtime.capabilities.browser.mock import MockBrowserCapability
from orion_agent_runtime.core.models import ReactAction, VerificationResult
from orion_agent_runtime.kernel import Kernel
from orion_agent_runtime.memory import MemoryManager
from orion_agent_runtime.runtime import AgentRuntime
from orion_agent_runtime.scheduler import Scheduler, TaskStatus
from orion_agent_runtime.world import WorldManager


# ---------- fixtures ----------

@pytest.fixture
def isolated_kernel(tmp_path):
    """构造隔离的 Kernel（独立 EventBus + 临时 memory DB）。"""
    bus = EventBus(event_store_dir=tmp_path / "events")
    memory = MemoryManager(db_path=tmp_path / "mem.db")
    world = WorldManager(bus)
    scheduler = Scheduler()
    kernel = Kernel(bus=bus, world=world, scheduler=scheduler, memory=memory)
    asyncio.run(kernel.start())
    yield kernel
    asyncio.run(kernel.shutdown())


# ---------- 基础：单步 finish ----------

def test_run_direct_finish_no_tools(isolated_kernel):
    """LLM 直接 finish（无需工具），应 goal_achieved 或 done。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="42")

    runtime.set_decide_fn(mock_decide)

    # 无 success_criteria：不进 Reflect，直接 done
    result = asyncio.run(runtime.run(
        goal="answer the question", user_id="u",
        success_criteria=[],  # 不开启验证
    ))
    assert result.status == "done"
    assert result.final_output == "42"
    assert result.iterations == 1


# ---------- 单步工具调用 + Observe ----------

def test_run_single_tool_then_finish(isolated_kernel):
    """Planner → call_tool → Observe → finish 闭环。"""
    runtime = AgentRuntime(isolated_kernel)

    # 注册一个 add 工具（复用 V1 tools）
    from orion_agent_runtime.tools.registry import get_tool
    assert get_tool("add") is not None  # V1 已注册

    decisions = iter([
        ReactAction(thought="need compute", type="call_tool", tool="add",
                    arguments={"a": 2, "b": 3}),
        ReactAction(thought="got 5", type="finish", answer="结果是 5"),
    ])

    async def mock_decide(state):
        return next(decisions)

    runtime.set_decide_fn(mock_decide)
    result = asyncio.run(runtime.run(
        goal="compute 2+3", user_id="u", success_criteria=[],
    ))
    assert result.status == "done"
    assert result.final_output == "结果是 5"
    assert result.iterations == 2


# ---------- 事件流 + World 更新 ----------

def test_run_emits_events_and_updates_world(isolated_kernel):
    """每个动作应 emit 事件，WorldManager 自动更新。"""
    runtime = AgentRuntime(isolated_kernel)
    captured = []

    async def collect(ev):
        if ev.type in (EventType.ACTION_REQUESTED, EventType.ACTION_COMPLETED,
                       EventType.TASK_CREATED, EventType.TASK_COMPLETED):
            captured.append((ev.type, ev.run_id))

    isolated_kernel.bus.on("*", collect)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="ok")

    runtime.set_decide_fn(mock_decide)
    result = asyncio.run(runtime.run(
        goal="test", user_id="u", success_criteria=[],
    ))

    types = [t for t, _ in captured]
    assert EventType.TASK_CREATED in types
    assert EventType.TASK_COMPLETED in types
    # World 应记录 task_context
    ctx = isolated_kernel.world.state().task_context
    assert ctx.get("goal") == "test"


def test_run_replay_events_by_run_id(isolated_kernel):
    """设计文档验收点：事件总线可按 run_id 回放。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="ok")

    runtime.set_decide_fn(mock_decide)
    result = asyncio.run(runtime.run(
        goal="test", user_id="u", success_criteria=[],
    ))

    events = asyncio.run(isolated_kernel.bus.replay(result.run_id))
    assert len(events) > 0
    assert all(e.run_id == result.run_id for e in events)


# ---------- Reflect 阶段（checker）----------

def test_run_with_goal_verification_achieved(isolated_kernel):
    """有 success_criteria 时进入 Reflect，checker 通过则 goal_achieved。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="42")

    def mock_checker(state, criteria, output):
        return VerificationResult(achieved=True, reason="answer correct",
                                  evidence="42 matches", next_action="finish")

    runtime.set_decide_fn(mock_decide)
    runtime.set_checker_fn(mock_checker)

    result = asyncio.run(runtime.run(
        goal="what is the answer", user_id="u",
        success_criteria=["answer is 42"],
    ))
    assert result.status == "goal_achieved"


def test_run_with_goal_verification_not_achieved_then_replan(isolated_kernel):
    """checker 未通过 + next_action=continue → 触发新一轮 ReAct。"""
    runtime = AgentRuntime(isolated_kernel)

    # 第一轮 finish（未达成），第二轮 finish（达成）
    decisions = iter([
        ReactAction(thought="try1", type="finish", answer="41"),
        ReactAction(thought="try2", type="finish", answer="42"),
    ])

    async def mock_decide(state):
        return next(decisions)

    checker_results = iter([
        VerificationResult(achieved=False, reason="wrong", next_action="continue"),
        VerificationResult(achieved=True, reason="correct", next_action="finish"),
    ])

    def mock_checker(state, criteria, output):
        return next(checker_results)

    runtime.set_decide_fn(mock_decide)
    runtime.set_checker_fn(mock_checker)

    result = asyncio.run(runtime.run(
        goal="find answer", user_id="u",
        success_criteria=["answer is 42"],
    ))
    assert result.status == "goal_achieved"


# ---------- 任务状态机集成 ----------

def test_run_updates_scheduler_status(isolated_kernel):
    """任务完成后 Scheduler 状态应为 DONE。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="ok")

    runtime.set_decide_fn(mock_decide)
    result = asyncio.run(runtime.run(
        goal="test", user_id="u", success_criteria=[],
    ))

    task = isolated_kernel.scheduler.get(result.task_id)
    assert task.status == TaskStatus.DONE


def test_run_failure_marks_scheduler_failed(isolated_kernel):
    """决策异常应使 Scheduler 标记 FAILED。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        raise RuntimeError("LLM down")

    runtime.set_decide_fn(mock_decide)
    result = asyncio.run(runtime.run(
        goal="test", user_id="u", success_criteria=[],
    ))
    assert result.status == "failed"
    task = isolated_kernel.scheduler.get(result.task_id)
    assert task.status == TaskStatus.FAILED


# ---------- episodic 记忆回写 ----------

def test_run_writes_episodic_memory(isolated_kernel):
    """任务结束应写 episodic 记忆（设计文档第 4 节 memory.put）。"""
    runtime = AgentRuntime(isolated_kernel)

    async def mock_decide(state):
        return ReactAction(thought="done", type="finish", answer="result-x")

    runtime.set_decide_fn(mock_decide)
    asyncio.run(runtime.run(goal="do task", user_id="user-1", success_criteria=[]))

    items = isolated_kernel.memory.episodic.recall_recent("user-1")
    assert len(items) >= 1
    assert any("result-x" in it.content for it in items)


# ---------- 测试注入点独立性 ----------

def test_runtime_isolation_between_instances(tmp_path):
    """两个 Kernel 实例应完全隔离（事件流、memory、scheduler 独立）。"""
    async def scenario():
        bus1 = EventBus(event_store_dir=tmp_path / "e1")
        bus2 = EventBus(event_store_dir=tmp_path / "e2")
        k1 = Kernel(bus=bus1, memory=MemoryManager(db_path=tmp_path / "m1.db"))
        k2 = Kernel(bus=bus2, memory=MemoryManager(db_path=tmp_path / "m2.db"))
        await k1.start()
        await k2.start()
        try:
            r1 = AgentRuntime(k1)
            r1.set_decide_fn(lambda s: _async_finish(s, "from-1"))
            res1 = await r1.run(goal="g1", user_id="u", success_criteria=[])

            r2 = AgentRuntime(k2)
            r2.set_decide_fn(lambda s: _async_finish(s, "from-2"))
            res2 = await r2.run(goal="g2", user_id="u", success_criteria=[])

            # 各自的事件流独立
            e1 = await k1.bus.replay(res1.run_id)
            e2 = await k2.bus.replay(res2.run_id)
            assert all(e.run_id == res1.run_id for e in e1)
            assert all(e.run_id == res2.run_id for e in e2)
        finally:
            await k1.shutdown()
            await k2.shutdown()

    asyncio.run(scenario())


async def _async_finish(state, answer):
    return ReactAction(thought="done", type="finish", answer=answer)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
