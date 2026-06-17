from orion_agent_runtime.core.models import AgentState


# 记忆总结器，负责把一个执行流程总结成一段文本，写入长期记忆。

def build_task_summary(state: AgentState) -> str:
    parts = [
        f"用户任务: {state.user_input}",
        f"执行状态: {state.status}",
        f"最终结果: {state.final_output}",
    ]

    if state.observations:
        obs_text = "; ".join(
            [f"step{obs.step}:{obs.tool}={obs.result}" for obs in state.observations]
        )
        parts.append(f"执行过程: {obs_text}")

    return " | ".join(parts)
