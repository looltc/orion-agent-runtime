from orion_agent_runtime.core.answer_synthesizer import synthesize_answer
from orion_agent_runtime.core.executor import execute_step
from orion_agent_runtime.core.models import AgentState
from orion_agent_runtime.core.planner import planner, replan_from_failure
from orion_agent_runtime.core.reviewer import review_trace
from orion_agent_runtime.core.skill_executor import execute_skill
from orion_agent_runtime.core.storage import load_state, save_state
from orion_agent_runtime.mcp.mcp_manager import MCPManager
from orion_agent_runtime.memory.memory import MemoryManager
from orion_agent_runtime.memory.memory_summarizer import build_task_summary

# 只做状态流转。

MAX_STEP_RETRIES = 2
MAX_REPLANS = 2

memory = MemoryManager()


def run_agent(user_input: str, run_id: str, user_id: str, mcp_manager: MCPManager) -> AgentState:
    state = load_state(run_id)

    if state is None:
        state = AgentState(
            run_id=run_id,
            user_input=user_input,
        )
        plan = planner(user_input, user_id)
        state.plan = plan.steps
        save_state(state, run_id)

        # 普通问答，直接结束
        if not plan.need_tools and not plan.need_knowledge and not plan.need_skill:
            state.status = "done"
            state.final_output = plan.direct_answer
            save_state(state, run_id)

            summary = build_task_summary(state)
            memory.remember_task_summary(
                user_id=user_id,
                summary=summary,
                metadata={"run_id": run_id, "user_input": user_input},
            )
            return state
        
        # 高层复合任务，直接调用技能执行器
        if plan.need_skill:
            skill_result = execute_skill(
                skill_name=plan.skill_name,
                payload={
                    "user_input": state.user_input,
                    "memory": state.knowledge_context,
                    "observations": [o.model_dump() for o in state.observations],
                },
            )
            state.final_output = skill_result
            state.status = "done"
            save_state(state, run_id)
            return state

    try:
        while state.current_step < len(state.plan):
            step = state.plan[state.current_step]

            while True:
                obs, trace = execute_step(
                    step=step,
                    previous_result=state.previous_result,
                    step_index=state.current_step + 1,
                    mcp_manager=mcp_manager,
                )

                state.observations.append(obs)
                state.traces.append(trace)

                if trace.success:
                    state.previous_result = obs.result
                    state.current_step += 1
                    state.step_retry_count = 0
                    state.last_decision = "continue"
                    save_state(state, run_id)
                    break

                decision = review_trace(state, trace)
                state.last_decision = decision.action
                save_state(state, run_id)

                if decision.action == "retry_step":
                    state.step_retry_count += 1
                    if state.step_retry_count > MAX_STEP_RETRIES:
                        state.status = "failed"
                        state.error = f"step retry exceeded: {trace.error}"
                        save_state(state, run_id)
                        return state
                    continue

                if decision.action == "replan":
                    state.replan_count += 1
                    if state.replan_count > MAX_REPLANS:
                        state.status = "failed"
                        state.error = f"replan exceeded: {trace.error}"
                        save_state(state, run_id)
                        return state

                    new_plan = replan_from_failure(state, trace)

                    # 保留已完成部分，替换后半段
                    state.plan = state.plan[: state.current_step] + new_plan.steps
                    state.step_retry_count = 0
                    save_state(state, run_id)
                    break

                if decision.action == "abort":
                    state.status = "failed"
                    state.error = trace.error or "aborted by reviewer"
                    save_state(state, run_id)
                    return state

                break

        # 知识问题：检索结果二次综合
        if state.plan and any(step.tool == "knowledge_search" for step in state.plan):
            knowledge_parts = []
            for obs in state.observations:
                if obs.tool == "knowledge_search":
                    knowledge_parts.append(str(obs.result))

            knowledge_context = "\n\n".join(knowledge_parts).strip()
            state.knowledge_context = knowledge_context

            if knowledge_context:
                final_answer = synthesize_answer(
                    user_input=state.user_input,
                    knowledge_text=knowledge_context,
                )
                state.final_output = final_answer
            else:
                state.final_output = "没有找到相关知识"

        else:
            state.final_output = state.previous_result

        state.status = "done"
        save_state(state, run_id)

        # 成功后写回长期记忆
        summary = build_task_summary(state)
        memory.remember_task_summary(
            user_id=user_id,
            summary=summary,
            metadata={"run_id": run_id, "user_input": user_input},
        )

        return state

    except Exception as e:
        state.status = "failed"
        state.error = str(e)
        save_state(state, run_id)
        return state
