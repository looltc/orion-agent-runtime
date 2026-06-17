# reviewer.py
from typing import Literal
from pydantic import BaseModel

from orion_agent_runtime.core.models import AgentState, ExecutionTrace

# 审查执行轨迹并决定下一步操作


class ReviewDecision(BaseModel):
    action: Literal["continue", "retry_step", "replan", "abort"]
    reason: str = ""


def review_trace(state: AgentState, trace: ExecutionTrace) -> ReviewDecision:
    if trace.success:
        return ReviewDecision(action="continue", reason="step succeeded")

    err = (trace.error or "").lower()
    print(f"Reviewing failed step: {err}")

    # 参数/工具名/schema 问题：更适合重规划
    if any(
        k in err
        for k in ["validation failed", "unknown tool", "unsupported tool", "missing"]
    ):
        return ReviewDecision(action="replan", reason=trace.error or "")

    # 常见临时性错误：先重试
    if any(k in err for k in ["timeout", "connection", "tempor", "rate limit"]):
        return ReviewDecision(action="retry_step", reason=trace.error or "")

    # 默认保守一点：先重规划
    return ReviewDecision(action="replan", reason=trace.error or "")
