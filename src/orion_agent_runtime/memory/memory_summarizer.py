from orion_agent_runtime.core.models import AgentState


# 记忆总结器，负责把一个执行流程总结成一段文本，写入长期记忆。

def build_task_summary(state: AgentState) -> str:
    parts = [
        f"用户任务: {state.user_input}",
        f"执行状态: {state.status}",
        f"最终结果: {state.final_output}",
    ]

    if state.observations:
        # 只取关键步骤摘要，每条截断，避免记忆膨胀
        key_steps = [o for o in state.observations
                     if o.tool not in ("browser_snapshot", "browser_get_page_text")]
        if not key_steps:
            key_steps = state.observations[:5]
        obs_text = "; ".join(
            f"step{obs.step}:{obs.tool}={str(obs.result)[:100]}"
            for obs in key_steps[:10]
        )
        parts.append(f"关键步骤: {obs_text}")

    return " | ".join(parts)
