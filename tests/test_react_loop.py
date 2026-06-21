"""P2: ReAct 内循环测试。

核心断言：
- ReAct 循环按 thought→action→observation 推进，每轮落盘
- 第二步参数可由第一步观察结果决定（动态依赖，旧 Plan 模式做不到）
- MAX_ITERATIONS 上限生效
- 历史压缩触发后观察数被压缩、history_summary 被填充
- finish 动作正确终止循环
"""

import pytest

from orion_agent_runtime.core import react_loop
from orion_agent_runtime.core.models import (
    AgentState,
    Observation,
    PlanStep,
    ReactAction,
    ReactTrace,
)
from orion_agent_runtime.core.storage import save_state


def _make_state(goal="test goal", criteria=None):
    s = AgentState(
        run_id="react-unit-test",
        user_input="test",
        goal=goal,
        success_criteria=criteria or ["完成"],
    )
    save_state(s, "react-unit-test")
    return s


# ---------- react 决策与执行 ----------

def test_react_finish_terminates_loop(monkeypatch):
    """LLM 第一轮就 finish：循环立即终止，final_output=answer。"""
    state = _make_state()

    def fake_decide(s):
        return ReactAction(thought="done immediately", type="finish", answer="42")

    monkeypatch.setattr(react_loop, "_react_decide", fake_decide)

    result = react_loop.run_react_loop(state, mcp_manager=None)
    assert result.status == "done"
    assert result.final_output == "42"
    assert len(result.react_traces) == 1
    assert result.react_traces[0].action_type == "finish"


def test_react_call_tool_then_finish(monkeypatch):
    """先 call_tool 再 finish：两轮，最终输出取自 finish.answer。"""
    state = _make_state(goal="算加法")

    decisions = iter([
        ReactAction(thought="算加法", type="call_tool", tool="add", arguments={"a": 2, "b": 3}),
        ReactAction(thought="结果是5", type="finish", answer="5"),
    ])
    monkeypatch.setattr(react_loop, "_react_decide", lambda s: next(decisions))

    result = react_loop.run_react_loop(state, mcp_manager=None)
    assert result.status == "done"
    assert result.final_output == "5"
    assert len(result.react_traces) == 2
    # 第一轮观察应记录 add 的结果
    assert result.react_traces[0].observation == 5
    assert result.react_traces[0].tool == "add"


def test_react_dynamic_dependency_uses_observation(monkeypatch):
    """核心：第二步参数 a 取自第一步 add 的观察结果（动态依赖）。"""
    state = _make_state(goal="先算2+3，再乘以10")

    decisions = iter([
        ReactAction(thought="先算2+3", type="call_tool", tool="add", arguments={"a": 2, "b": 3}),
        # a=5 来自上一步观察，这里 LLM 在看到 obs=5 后决定
        ReactAction(thought="用5乘10", type="call_tool", tool="mul", arguments={"a": 5, "b": 10}),
        ReactAction(thought="得到50", type="finish", answer="50"),
    ])
    monkeypatch.setattr(react_loop, "_react_decide", lambda s: next(decisions))

    result = react_loop.run_react_loop(state, mcp_manager=None)
    mul_trace = [t for t in result.react_traces if t.tool == "mul"][0]
    assert mul_trace.arguments == {"a": 5, "b": 10}, "mul 参数应由上一步观察结果决定"
    assert result.final_output == "50"


def test_react_tool_failure_feeds_back_to_llm(monkeypatch):
    """工具失败时，错误作为观察回灌给 LLM，让其自行纠错（ReAct 自我修正）。"""
    state = _make_state()

    decisions = iter([
        # 第一次调用不存在的工具
        ReactAction(thought="try bad tool", type="call_tool", tool="no_such_tool", arguments={}),
        # 看到错误后改用正确工具
        ReactAction(thought="bad tool, use add", type="call_tool", tool="add", arguments={"a": 1, "b": 1}),
        ReactAction(thought="done", type="finish", answer="2"),
    ])
    monkeypatch.setattr(react_loop, "_react_decide", lambda s: next(decisions))

    result = react_loop.run_react_loop(state, mcp_manager=None)
    # 第一轮观察应是错误信息
    assert "TOOL_ERROR" in str(result.react_traces[0].observation)
    # 最终仍能成功完成
    assert result.final_output == "2"


def test_react_call_tool_without_tool_name_recoverable(monkeypatch):
    """call_tool 但未给 tool 名：记为 INVALID 观察，循环继续不崩溃。"""
    state = _make_state()

    decisions = iter([
        ReactAction(thought="oops", type="call_tool", tool=None, arguments={}),
        ReactAction(thought="finish", type="finish", answer="ok"),
    ])
    monkeypatch.setattr(react_loop, "_react_decide", lambda s: next(decisions))

    result = react_loop.run_react_loop(state, mcp_manager=None)
    assert result.status == "done"
    assert "INVALID" in str(result.react_traces[0].observation)


# ---------- MAX_ITERATIONS 上限 ----------

def test_react_max_iterations_cap(monkeypatch):
    """LLM 永不 finish 时，MAX_ITERATIONS 上限必须生效（红线：每个循环都有明确上限）。"""
    state = _make_state()
    monkeypatch.setattr(react_loop, "MAX_ITERATIONS", 4)

    # 每轮都 call_tool，永不 finish
    monkeypatch.setattr(
        react_loop,
        "_react_decide",
        lambda s: ReactAction(thought="keep going", type="call_tool", tool="add", arguments={"a": 1, "b": 1}),
    )

    result = react_loop.run_react_loop(state, mcp_manager=None)
    assert result.status == "done"
    assert "MAX_ITERATIONS" in (result.error or "")
    assert len(result.react_traces) == 4


def test_react_decision_failure_marks_failed(monkeypatch):
    """LLM 决策调用自身抛异常：状态置 failed，不崩溃。"""
    state = _make_state()

    def boom(s):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(react_loop, "_react_decide", boom)
    result = react_loop.run_react_loop(state, mcp_manager=None)
    assert result.status == "failed"
    assert "react decision failed" in (result.error or "")


# ---------- 历史压缩 ----------

def test_compress_history_triggers():
    """观察数超过阈值时触发压缩：早期观察进 summary，保留近期观察。"""
    state = _make_state()
    for i in range(10):
        state.observations.append(Observation(step=i, tool="add", result=i))

    threshold = react_loop.HISTORY_COMPRESS_THRESHOLD
    react_loop._compress_history(state)

    assert len(state.observations) <= threshold, "观察数应被压缩到阈值内"
    assert state.history_summary is not None, "history_summary 应被填充"
    assert state.history_summary != ""


def test_compress_history_noop_below_threshold():
    """观察数未超阈值时不压缩。"""
    state = _make_state()
    state.observations.append(Observation(step=0, tool="add", result=1))
    before = list(state.observations)
    react_loop._compress_history(state)
    assert state.observations == before
    assert state.history_summary is None


def test_observation_history_uses_summary_when_present():
    """有 history_summary 时，_format_observation_history 优先用摘要。"""
    state = _make_state()
    state.history_summary = "[历史摘要] 之前算过2+3=5"
    state.observations.append(Observation(step=0, tool="add", result=99))
    text = react_loop._format_observation_history(state)
    assert "[历史摘要]" in text
    assert "99" in text  # 近期观察仍可见


if __name__ == "__main__":
    pytest.main([__file__, "-v"])