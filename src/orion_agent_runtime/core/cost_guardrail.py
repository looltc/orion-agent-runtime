"""成本护栏（P4）。

职责：在每次迭代后累加 token 计数，并在超过预算硬上限时终止循环，
防止无人值守循环一夜烧光预算。

Loop Engineering 原则："配置每日消费提醒和硬性上限。"
上限默认从环境变量 ORION_MAX_TOKENS_PER_RUN 读取（缺省无上限，向后兼容）。
"""

import os

from orion_agent_runtime.core.models import AgentState

# 单次 run 的 token 硬上限；0/负数表示不限制
MAX_TOKENS_PER_RUN = int(os.getenv("ORION_MAX_TOKENS_PER_RUN", "0"))


def budget_exceeded(state: AgentState) -> bool:
    """判断 state 是否已超 token 预算。"""
    if MAX_TOKENS_PER_RUN <= 0:
        return False
    return state.total_tokens >= MAX_TOKENS_PER_RUN


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（4 字符 ≈ 1 token 的经验值，含中文按字符计）。

    精确计数需对接 LLM 的 usage 字段；此处提供保守上限估算，供护栏决策。
    """
    if not text:
        return 0
    # 中文按字符，英文按 ~4 字符/token 折中：取 max(字符数/3, 1)
    return max(len(text) // 3, 1)


def accumulate_usage(state: AgentState, tokens: int, cost: float = 0.0) -> None:
    """累加本轮 token 与成本到 state。"""
    state.total_tokens += tokens
    state.cost_estimate += cost
