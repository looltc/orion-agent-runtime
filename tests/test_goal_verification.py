"""P1: 目标收敛验证（Maker-Checker）测试。

核心断言：系统现在能识别"步骤跑完但答案错误/未达标"，而非错误地标记完成。
所有 LLM 调用通过 monkeypatch mock，测试纯逻辑不依赖真实模型。
"""

import json

import pytest

from orion_agent_runtime.core import workflow
from orion_agent_runtime.core.models import (
    AgentState,
    Observation,
    Plan,
    PlanStep,
    VerificationResult,
)


# ---------- 测试夹具 ----------

class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.reasoning_content = None


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _make_state_with_final_output(final_output, goal="计算 2+3", criteria=None):
    """构造一个"步骤已跑完"的 state，绕过 planner/executor，直接进入验证环节。"""
    return AgentState(
        run_id="verify-test",
        user_input="算一下 2+3",
        plan=[PlanStep(tool="add", arguments={"a": 2, "b": 3})],
        current_step=1,
        observations=[Observation(step=1, tool="add", result=final_output)],
        previous_result=final_output,
        final_output=final_output,
        status="done",
        goal=goal,
        success_criteria=criteria if criteria is not None else ["输出应为 5"],
    )


# ---------- goal_evaluator 单元测试 ----------

def test_evaluate_goal_achieved(monkeypatch):
    """checker 返回 achieved=True 时，VerificationResult 正确解析。"""
    from orion_agent_runtime.core import goal_evaluator

    def fake_call(prompt):
        return VerificationResult(
            achieved=True, reason="输出5满足验收", evidence="result=5", next_action="finish"
        )

    monkeypatch.setattr(goal_evaluator, "_call_checker_llm", fake_call)
    state = _make_state_with_final_output(5)
    result = goal_evaluator.evaluate_goal(state, state.success_criteria, "5")
    assert result.achieved is True
    assert result.next_action == "finish"


def test_evaluate_goal_not_achieved(monkeypatch):
    """checker 返回 achieved=False 时能正确反映未达标。"""
    from orion_agent_runtime.core import goal_evaluator

    def fake_call(prompt):
        return VerificationResult(
            achieved=False,
            reason="输出错误",
            evidence="期望5实际得到6",
            next_action="continue",
        )

    monkeypatch.setattr(goal_evaluator, "_call_checker_llm", fake_call)
    state = _make_state_with_final_output(6)
    result = goal_evaluator.evaluate_goal(state, state.success_criteria, "6")
    assert result.achieved is False
    assert result.next_action == "continue"


def test_call_checker_llm_parses_json(monkeypatch):
    """_call_checker_llm 能从 LLM 文本响应解析出结构化结果。"""
    from orion_agent_runtime.core import goal_evaluator

    payload = json.dumps(
        {"achieved": True, "reason": "ok", "evidence": "x", "next_action": "finish"}
    )
    monkeypatch.setattr(
        goal_evaluator,
        "get_llm_client",
        lambda role: (type("C", (), {"chat": type("Chat", (), {
            "completions": type("Comp", (), {
                "create": staticmethod(lambda **kw: _FakeResp(payload))
            })
        })()})(), "fake-model"),
    )
    result = goal_evaluator._call_checker_llm("prompt")
    assert result.achieved is True


def test_call_checker_llm_falls_back_to_json_extraction(monkeypatch):
    """LLM 夹带 markdown 时能截取最外层 JSON。"""
    from orion_agent_runtime.core import goal_evaluator

    payload = "```json\n" + json.dumps(
        {"achieved": False, "reason": "bad", "evidence": "y", "next_action": "refine"}
    ) + "\n```"
    monkeypatch.setattr(
        goal_evaluator,
        "get_llm_client",
        lambda role: (type("C", (), {"chat": type("Chat", (), {
            "completions": type("Comp", (), {
                "create": staticmethod(lambda **kw: _FakeResp(payload))
            })
        })()})(), "fake-model"),
    )
    result = goal_evaluator._call_checker_llm("prompt")
    assert result.achieved is False
    assert result.next_action == "refine"


# ---------- _convergence_check 状态流转测试 ----------

def test_convergence_check_marks_goal_achieved(monkeypatch):
    """checker 通过 → status=goal_achieved，iterations 自增。"""
    from orion_agent_runtime.core import goal_evaluator

    monkeypatch.setattr(
        goal_evaluator,
        "_call_checker_llm",
        lambda p: VerificationResult(achieved=True, reason="ok", next_action="finish"),
    )
    # memory 用空实现，避免真实写库
    monkeypatch.setattr(workflow, "memory", type("M", (), {
        "remember_task_summary": staticmethod(lambda **kw: None)
    })())

    state = _make_state_with_final_output(5)
    result_state = workflow._convergence_check(state, user_id="u")
    assert result_state.status == "goal_achieved"
    assert result_state.iterations == 1
    assert result_state.verification.achieved is True


def test_convergence_check_handles_checker_failure_gracefully(monkeypatch):
    """checker 自身抛异常时，应退化为 done 而非崩溃（checker 故障不阻塞任务）。"""
    from orion_agent_runtime.core import goal_evaluator

    def boom(prompt):
        raise RuntimeError("checker LLM down")

    monkeypatch.setattr(goal_evaluator, "_call_checker_llm", boom)
    monkeypatch.setattr(workflow, "memory", type("M", (), {
        "remember_task_summary": staticmethod(lambda **kw: None)
    })())

    state = _make_state_with_final_output(5)
    result_state = workflow._convergence_check(state, user_id="u")
    assert result_state.status == "done"
    assert "goal evaluator failed" in (result_state.error or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])