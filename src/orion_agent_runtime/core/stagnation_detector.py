"""停滞检测器（P4）。

职责：监控连续 K 轮验证无新进展（reason 重复 / final_output 不变），
触发暂停并通知人工介入，避免"未达成→重规划→仍未达成"的死循环烧 token。

Loop Engineering 原则："如果一个循环 5 次迭代后没有进展，应暂停并重新评估。"
本实现默认 K=3（保守），可通过 STAGNATION_THRESHOLD 调整。
"""

from typing import List, Optional

from orion_agent_runtime.core.models import AgentState, VerificationResult

# 连续无进展的最大轮数；超过则触发暂停
STAGNATION_THRESHOLD = 3


def _verification_signature(v: Optional[VerificationResult]) -> str:
    """提取验证结果的稳定签名，用于检测重复。

    签名由 achieved + reason + evidence 构成；相同签名视为"无新进展"。
    """
    if v is None:
        return ""
    return f"{v.achieved}|{v.reason}|{v.evidence}"


def detect_stagnation(state: AgentState, history_signatures: List[str]) -> bool:
    """判断当前 state 是否陷入停滞。

    参数:
        state: 当前状态（含本次 verification）
        history_signatures: 历史验证签名列表（按时间顺序，调用方维护）

    返回:
        True 表示停滞（应暂停），False 表示仍在进展。
    """
    current = _verification_signature(state.verification)

    # 统计连续相同签名（从最近往前数）
    same_streak = 0
    for sig in reversed(history_signatures):
        if sig == current:
            same_streak += 1
        else:
            break

    return same_streak >= STAGNATION_THRESHOLD


def mark_stagnation(state: AgentState) -> AgentState:
    """将 state 标记为暂停（paused），并记录原因，等待人工介入。"""
    state.stagnation_count += 1
    state.status = "paused"
    state.error = (
        f"stagnation detected after {state.stagnation_count} consecutive non-progress "
        f"verifications: {state.verification.reason if state.verification else 'unknown'}"
    )
    return state
