"""P4: 收敛控制测试 —— 停滞检测 + 成本护栏 + Maker-Checker 模型分离。

核心断言（P4 价值）：
- 连续 K 轮验证签名重复 → 触发 paused 状态（停滞检测）
- token 超 MAX_TOKENS_PER_RUN → 终止循环（成本护栏）
- checker 使用与 maker 不同的模型配置（Maker-Checker 分离已就绪）
"""

import pytest

from orion_agent_runtime.core import workflow
from orion_agent_runtime.core.cost_guardrail import (
    MAX_TOKENS_PER_RUN,
    budget_exceeded,
    estimate_tokens,
)
from orion_agent_runtime.core.models import AgentState, VerificationResult
from orion_agent_runtime.core.stagnation_detector import (
    STAGNATION_THRESHOLD,
    _verification_signature,
    detect_stagnation,
    mark_stagnation,
)


# ---------- 停滞检测 ----------

def test_verification_signature_stable():
    v1 = VerificationResult(achieved=False, reason="bad", evidence="x", next_action="continue")
    v2 = VerificationResult(achieved=False, reason="bad", evidence="x", next_action="refine")
    assert _verification_signature(v1) == _verification_signature(v2)  # next_action 不入签名


def test_detect_stagnation_on_repeated_failures():
    """连续 K 轮相同验证签名 → 停滞。"""
    sig = "False|same reason|same evidence"
    state = AgentState(run_id="t", user_input="x")
    state.verification = VerificationResult(
        achieved=False, reason="same reason", evidence="same evidence"
    )
    # 需要 THRESHOLD 个匹配的历史签名才触发（检测统计的是历史尾部匹配数）
    history = [sig] * STAGNATION_THRESHOLD
    assert detect_stagnation(state, history) is True


def test_detect_stagnation_just_below_threshold():
    """历史匹配数 = THRESHOLD-1 时不触发（边界正确）。"""
    sig = "False|same reason|same evidence"
    state = AgentState(run_id="t", user_input="x")
    state.verification = VerificationResult(
        achieved=False, reason="same reason", evidence="same evidence"
    )
    history = [sig] * (STAGNATION_THRESHOLD - 1)
    assert detect_stagnation(state, history) is False


def test_detect_stagnation_not_triggered_when_progressing():
    """验证签名变化（有进展）→ 不停滞。"""
    state = AgentState(run_id="t", user_input="x")
    state.verification = VerificationResult(
        achieved=False, reason="new reason", evidence="y"
    )
    history = ["False|old reason|x", "False|older reason|z"]
    assert detect_stagnation(state, history) is False


def test_mark_stagnation_sets_paused():
    state = AgentState(run_id="t", user_input="x")
    state.verification = VerificationResult(achieved=False, reason="stuck", evidence="e")
    before = state.stagnation_count
    result = mark_stagnation(state)
    assert result.status == "paused"
    assert result.stagnation_count == before + 1
    assert "stagnation" in (result.error or "")


# ---------- 成本护栏 ----------

def test_budget_not_exceeded_under_limit():
    state = AgentState(run_id="t", user_input="x")
    state.total_tokens = 100
    # 默认无上限（MAX_TOKENS_PER_RUN=0）→ 永不超
    assert budget_exceeded(state) is False


def test_budget_exceeded_when_over_limit(monkeypatch):
    state = AgentState(run_id="t", user_input="x")
    state.total_tokens = 5000
    monkeypatch.setattr(
        "orion_agent_runtime.core.cost_guardrail.MAX_TOKENS_PER_RUN", 1000
    )
    assert budget_exceeded(state) is True


def test_estimate_tokens_positive():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") >= 1


# ---------- Maker-Checker 模型分离（配置层面） ----------

def test_maker_checker_can_use_different_models(monkeypatch):
    """checker 可独立配置模型，未配置时回落 maker（P0 已验证回落，此处验证可分离）。"""
    monkeypatch.setenv("ORION_LLM_MODEL", "maker-gpt")
    monkeypatch.setenv("ORION_CHECKER_LLM_MODEL", "checker-cheap")
    from orion_agent_runtime import config, llm_provider

    cfg = config.get_config(reload=True)
    assert cfg.llm.model == "maker-gpt"
    assert cfg.checker_llm.model == "checker-cheap"

    _, maker_model = llm_provider.get_llm_client(role="maker")
    _, checker_model = llm_provider.get_llm_client(role="checker")
    assert maker_model == "maker-gpt"
    assert checker_model == "checker-cheap"


def test_goal_evaluator_uses_checker_role(monkeypatch):
    """goal_evaluator 显式通过 checker 角色 LLM 调用（职责分离）。"""
    from orion_agent_runtime.core import goal_evaluator

    captured = {}

    class _Msg:
        content = '{"achieved":true}'
        reasoning_content = None

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    def fake_get_client(role="maker"):
        captured["role"] = role
        fake_client = type("C", (), {})()
        fake_client.chat = type("Chat", (), {})()
        fake_client.chat.completions = type("Comp", (), {})()
        fake_client.chat.completions.create = lambda **kw: _Resp()
        return fake_client, "checker-model"

    monkeypatch.setattr(goal_evaluator, "get_llm_client", fake_get_client)
    monkeypatch.setenv("ORION_CHECKER_LLM_MODEL", "checker-model")

    state = AgentState(run_id="t", user_input="x", goal="g", success_criteria=["c"])
    result = goal_evaluator.evaluate_goal(state, ["c"], "answer")
    assert captured["role"] == "checker", "goal_evaluator 必须用 checker 角色"
    assert result.achieved is True


# ---------- 停滞端到端（workflow 层） ----------

def test_stagnation_pauses_loop(monkeypatch):
    """构造"永远过不了 checker 且 reason 重复"的任务，确认触发 paused 而非死循环。"""
    from orion_agent_runtime.core import react_loop
    from orion_agent_runtime.core.models import ReactAction

    # 每轮 ReAct 都 finish 同样的错误答案
    def fake_decide(s):
        return ReactAction(thought="stuck", type="finish", answer="wrong")

    monkeypatch.setattr(react_loop, "_react_decide", fake_decide)

    # checker 永远返回相同未通过签名 → 触发停滞
    from orion_agent_runtime.core import goal_evaluator

    monkeypatch.setattr(
        goal_evaluator,
        "_call_checker_llm",
        lambda p: VerificationResult(
            achieved=False, reason="always wrong", evidence="same", next_action="continue"
        ),
    )
    monkeypatch.setattr(
        workflow,
        "memory",
        type("M", (), {"remember_task_summary": staticmethod(lambda **kw: None)})(),
    )
    # 压低阈值以加速测试
    monkeypatch.setattr(
        "orion_agent_runtime.core.stagnation_detector.STAGNATION_THRESHOLD", 3
    )

    import os
    if os.path.exists("./runtime_state/stagdemo.json"):
        os.remove("./runtime_state/stagdemo.json")

    from orion_agent_runtime.core.models import AgentState
    from orion_agent_runtime.core.storage import save_state
    state = AgentState(
        run_id="stagdemo",
        user_input="impossible",
        goal="impossible",
        success_criteria=["never satisfiable"],
    )
    save_state(state, "stagdemo")

    result = workflow.run_agent("impossible", "stagdemo", "u", mcp_manager=None)
    assert result.status == "paused", f"应触发暂停，实际 {result.status}: {result.error}"
    assert result.stagnation_count >= 1
    assert "stagnation" in (result.error or "")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])