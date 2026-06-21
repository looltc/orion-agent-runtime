"""指标收集器（P5）。

从 AgentState 聚合关键运行指标，供 run_inspector 展示与离线分析。
对应 Loop Engineering "可观测数据"要求：循环次数、成功率、收敛时间、资源消耗。
"""

from typing import Dict, Any

from orion_agent_runtime.core.models import AgentState


def collect_metrics(state: AgentState) -> Dict[str, Any]:
    """从一次 run 的 state 聚合关键指标。"""
    traces = state.traces
    react_traces = state.react_traces
    total_tool_calls = len(traces)
    failed_tool_calls = sum(1 for t in traces if not t.success)

    # 去重后的真实工具数（P3 幂等缓存视角下的实际执行）
    unique_tools_called = len({t.normalized_tool or t.raw_tool for t in traces})

    return {
        "run_id": state.run_id,
        "status": state.status,
        "goal": state.goal,
        "iterations": state.iterations,
        "react_iterations": len(react_traces),
        "plan_steps": len(state.plan),
        "current_step": state.current_step,
        "tool_calls_total": total_tool_calls,
        "tool_calls_failed": failed_tool_calls,
        "tool_calls_success_rate": (
            (total_tool_calls - failed_tool_calls) / total_tool_calls
            if total_tool_calls
            else 1.0
        ),
        "unique_tools_used": unique_tools_called,
        "replan_count": state.replan_count,
        "step_retry_count": state.step_retry_count,
        "stagnation_count": state.stagnation_count,
        "total_tokens": state.total_tokens,
        "cost_estimate": state.cost_estimate,
        "goal_achieved": state.status == "goal_achieved",
        "verification": state.verification.model_dump() if state.verification else None,
    }


def format_metrics(metrics: Dict[str, Any]) -> str:
    """人类可读的指标摘要，供 CLI 打印。"""
    lines = [
        f"run_id: {metrics['run_id']}",
        f"status: {metrics['status']}",
        f"goal_achieved: {metrics['goal_achieved']}",
        f"iterations: {metrics['iterations']} (react轮数: {metrics['react_iterations']})",
        f"tool_calls: {metrics['tool_calls_total']} (失败 {metrics['tool_calls_failed']}, "
        f"成功率 {metrics['tool_calls_success_rate']:.0%}, 独立工具 {metrics['unique_tools_used']})",
        f"replan_count: {metrics['replan_count']} | step_retry: {metrics['step_retry_count']} | "
        f"stagnation: {metrics['stagnation_count']}",
        f"tokens: {metrics['total_tokens']} | cost: {metrics['cost_estimate']:.4f}",
    ]
    if metrics.get("verification"):
        v = metrics["verification"]
        lines.append(
            f"verification: achieved={v.get('achieved')} reason={v.get('reason', '')[:80]}"
        )
    return "\n".join(lines)
