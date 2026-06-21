"""Goal Evaluator（Checker）—— Loop Engineering 的收敛验证核心。

职责：在步骤执行完毕后，独立判断"最终输出是否真正达成了用户目标"，
而非仅凭"步骤都跑完了"就判定 done。这是 Maker-Checker 中 Checker 的角色。

Loop Engineering 核心原则之一：让模型评估自己的输出"就像让学生给自己考试打分一样不可靠"。
因此 checker 使用独立 prompt；P4 起会进一步切换到独立模型实例。
"""

from typing import List

from orion_agent_runtime.core.models import AgentState, VerificationResult
from orion_agent_runtime.llm_provider import get_llm_client


def _get_text(message) -> str:
    text = message.content or getattr(message, "reasoning_content", None)
    if not text:
        raise ValueError("empty LLM output from checker")
    return text


def _extract_json_text(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no valid JSON found in checker output")
    return raw[start : end + 1]


def _format_observations(state: AgentState) -> str:
    if not state.observations:
        return "(无)"
    lines = []
    for i, obs in enumerate(state.observations, 1):
        lines.append(f"  步骤{i} [{obs.tool}]: {obs.result}")
    return "\n".join(lines)


def _call_checker_llm(prompt: str) -> VerificationResult:
    """调用 checker 角色 LLM，结构化输出 VerificationResult。"""
    client, model_name = get_llm_client(role="checker")
    response = client.chat.completions.create(
        model=model_name,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "verification_result",
                "schema": VerificationResult.model_json_schema(),
                "strict": True,
            },
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个严格的目标验收器（Checker）。你的唯一职责是判断任务输出是否真正达成既定目标。"
                    "要保持怀疑、严格对照验收标准逐条核查。宁可判定未达标也不要放行错误结果。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = _get_text(response.choices[0].message)
    try:
        return VerificationResult.model_validate_json(raw)
    except Exception:
        return VerificationResult.model_validate_json(_extract_json_text(raw))


def evaluate_goal(
    state: AgentState,
    success_criteria: List[str],
    final_output: str,
) -> VerificationResult:
    """判断 state 的最终输出是否达成了 success_criteria。

    参数:
        state: 当前 AgentState（提供 goal、observations 等）
        success_criteria: 可验证的验收标准列表
        final_output: 待验证的最终输出

    返回:
        VerificationResult，achieved=True 才算真正完成
    """
    criteria_text = "\n".join(f"  - {c}" for c in success_criteria) or "  (未提供)"

    prompt = f"""
        请判断任务输出是否真正达成了目标。

        【用户原始任务】
        {state.user_input}

        【目标定义】
        {state.goal or state.user_input}

        【验收标准（必须全部满足才算达成）】
        {criteria_text}

        【执行过程中产生的观察结果】
        {_format_observations(state)}

        【待验证的最终输出】
        {final_output}

        请严格按以下规则判断：
        1. achieved=true 当且仅当"每一条"验收标准都被输出满足；
        2. reason 给出判断理由；
        3. evidence 指出支撑判断的具体证据（引用输出中的内容或缺失点）；
        4. next_action：
           - finish：验收通过
           - continue：未通过，但通过重规划/重执行有可能达成（当前轮可继续）
           - refine：根本性缺陷，需要完全换策略（触发上层停滞处理）

        只输出 JSON，不要解释，不要 markdown。
        """.strip()

    return _call_checker_llm(prompt)
