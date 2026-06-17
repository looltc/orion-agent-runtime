from typing import Optional, Literal
from pydantic import BaseModel

from orion_agent_runtime.core.models import AgentState, ExecutionTrace

# 根据 AgentState 快速定位失败层级，给出修复建议。


class TraceReport(BaseModel):
    stage: Literal["planner", "executor", "reviewer", "runtime", "unknown"]
    ok: bool
    step_index: Optional[int] = None
    failed_tool: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None


def inspect_trace(state: AgentState) -> TraceReport:
    """
    根据 state.traces / status / current_step
    快速定位失败层级。
    """
    if not state.traces:
        if state.status == "failed" and state.error:
            return TraceReport(
                stage="planner",
                ok=False,
                reason=state.error,
                suggestion="检查 planner 是否输出了合法 Plan，是否符合工具白名单。",
            )

        return TraceReport(
            stage="unknown",
            ok=True,
            suggestion="暂无 trace，可继续执行。",
        )

    last_trace = state.traces[-1]

    if last_trace.success:
        return TraceReport(
            stage="runtime",
            ok=True,
            step_index=last_trace.step_index,
            failed_tool=last_trace.normalized_tool or last_trace.raw_tool,
            suggestion="最近一步成功，runtime 正常。",
        )

    reason = last_trace.error or "unknown error"
    tool = last_trace.normalized_tool or last_trace.raw_tool

    # 1) 先看是不是 planner 问题：工具名漂移 / schema 不合法
    if any(
        k in reason.lower()
        for k in ["unknown tool", "unsupported tool", "validation failed"]
    ):
        return TraceReport(
            stage="planner",
            ok=False,
            step_index=last_trace.step_index,
            failed_tool=tool,
            reason=reason,
            suggestion="Planner 输出不在工具白名单内，或参数 schema 不匹配。先校验 tool catalog，再重规划。",
        )

    # 2) 典型 executor / tool 本身问题
    if any(
        k in reason.lower()
        for k in ["unexpected keyword argument", "typeerror", "tool execution failed"]
    ):
        return TraceReport(
            stage="executor",
            ok=False,
            step_index=last_trace.step_index,
            failed_tool=tool,
            reason=reason,
            suggestion="检查工具参数名、参数类型、None 注入、工具函数签名。",
        )

    # 3) 临时错误，通常走 retry
    if any(
        k in reason.lower() for k in ["timeout", "connection", "rate limit", "tempor"]
    ):
        return TraceReport(
            stage="runtime",
            ok=False,
            step_index=last_trace.step_index,
            failed_tool=tool,
            reason=reason,
            suggestion="这是临时性错误，优先 retry_step。",
        )

    # 4) 默认归到 reviewer / replan 决策
    return TraceReport(
        stage="reviewer",
        ok=False,
        step_index=last_trace.step_index,
        failed_tool=tool,
        reason=reason,
        suggestion="让 reviewer 决定 retry 还是 replan。",
    )


def format_report(report: TraceReport) -> str:
    lines = [
        f"stage: {report.stage}",
        f"ok: {report.ok}",
    ]

    if report.step_index is not None:
        lines.append(f"step_index: {report.step_index}")

    if report.failed_tool:
        lines.append(f"failed_tool: {report.failed_tool}")

    if report.reason:
        lines.append(f"reason: {report.reason}")

    if report.suggestion:
        lines.append(f"suggestion: {report.suggestion}")

    return "\n".join(lines)
