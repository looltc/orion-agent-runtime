from orion_agent_runtime.core.answer_synthesizer import synthesize_answer
from orion_agent_runtime.core.cost_guardrail import accumulate_usage, budget_exceeded, estimate_tokens
from orion_agent_runtime.core.executor import execute_step
from orion_agent_runtime.core.goal_evaluator import evaluate_goal
from orion_agent_runtime.core.models import AgentState, ExecutionTrace
from orion_agent_runtime.core.planner import planner, replan_from_failure
from orion_agent_runtime.core.react_loop import run_react_loop
from orion_agent_runtime.core.reviewer import review_trace
from orion_agent_runtime.core.skill_executor import execute_skill
from orion_agent_runtime.core.stagnation_detector import (
    _verification_signature,
    detect_stagnation,
    mark_stagnation,
)
from orion_agent_runtime.core.storage import load_state, save_state
from orion_agent_runtime.mcp.mcp_manager import MCPManager
from orion_agent_runtime.memory.memory import MemoryManager
from orion_agent_runtime.memory.memory_summarizer import build_task_summary
from orion_agent_runtime.audit.audit_log import log_event

# 状态流转 + Loop 收敛控制 + ReAct 内循环路由。
#
# P1 改造：在原有 Plan→Execute 外层包一个收敛闭环。
#   步骤跑完 → 目标验证(checker) → 达成则 goal_achieved；未达成则重规划再来。
#   "done" 仅表示步骤完成但未经验证；"goal_achieved" 才是真正的 Loop 终止。
#
# P2 改造：需要工具/知识的任务改走 ReAct 内循环（LLM 逐步推理-行动-观察），
#   而非 planner 一次出全量步骤。简单问答/技能保留直通路径。
#   USE_REACT_LOOP 开关可一键回退到 P1 的 Plan→Execute 模式。

MAX_STEP_RETRIES = 2
MAX_REPLANS = 2
# 收敛上限：checker 最多评估几次，防止"未达成→重规划→仍未达成"死循环。
MAX_GOAL_EVALUATIONS = 3
# 回滚开关：checker 误判率高时可关闭，退回旧的"步骤跑完即 done"行为。
VERIFY_ON_FINISH = True
# P2：是否启用 ReAct 内循环。设为 False 回退到 Plan→Execute 模式（P1 行为）。
USE_REACT_LOOP = True

memory = MemoryManager()


def _produce_final_output(state: AgentState) -> None:
    """根据 plan 类型产出 final_output（原 workflow 123-143 行逻辑，抽函数以便复用）。"""
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


def _run_plan_execute_loop(state: AgentState, mcp_manager: MCPManager) -> AgentState:
    """执行已有的 Plan→Execute→Review 单趟循环（原 workflow 63-162 行）。

    返回：最终 state（status 为 done/failed）。注意此处 done 仅表示步骤完成，
    是否真正 goal_achieved 由外层 convergence loop 判定。
    """
    try:
        while state.current_step < len(state.plan):
            step = state.plan[state.current_step]

            while True:
                obs, trace = execute_step(
                    step=step,
                    previous_result=state.previous_result,
                    step_index=state.current_step + 1,
                    mcp_manager=mcp_manager,
                    run_id=state.run_id,
                )

                state.observations.append(obs)
                state.traces.append(trace)

                if trace.success:
                    state.previous_result = obs.result
                    state.current_step += 1
                    state.step_retry_count = 0
                    state.last_decision = "continue"
                    save_state(state, state.run_id)
                    break

                decision = review_trace(state, trace)
                state.last_decision = decision.action
                save_state(state, state.run_id)

                if decision.action == "retry_step":
                    state.step_retry_count += 1
                    if state.step_retry_count > MAX_STEP_RETRIES:
                        state.status = "failed"
                        state.error = f"step retry exceeded: {trace.error}"
                        save_state(state, state.run_id)
                        return state
                    continue

                if decision.action == "replan":
                    state.replan_count += 1
                    if state.replan_count > MAX_REPLANS:
                        state.status = "failed"
                        state.error = f"replan exceeded: {trace.error}"
                        save_state(state, state.run_id)
                        return state

                    new_plan = replan_from_failure(state, trace)

                    # 保留已完成部分，替换后半段
                    state.plan = state.plan[: state.current_step] + new_plan.steps
                    state.step_retry_count = 0
                    save_state(state, state.run_id)
                    break

                if decision.action == "abort":
                    state.status = "failed"
                    state.error = trace.error or "aborted by reviewer"
                    save_state(state, state.run_id)
                    return state

                break

        _produce_final_output(state)
        state.status = "done"
        save_state(state, state.run_id)
        return state

    except Exception as e:
        state.status = "failed"
        state.error = str(e)
        save_state(state, state.run_id)
        return state


def _execute_task(state: AgentState, mcp_manager: MCPManager) -> AgentState:
    """统一执行入口：按 USE_REACT_LOOP 开关在 ReAct 内循环与 Plan→Execute 间路由。

    ReAct 路径（P2）：LLM 逐步决策工具，下一步依赖上一步观察，真正工具调用循环。
    Plan 路径（P1/原）：planner 一次出全量步骤，executor 顺序执行。
    两条路径最终都产出 final_output + status=done/failed，交给外层收敛验证。
    """
    if USE_REACT_LOOP:
        # 重置 ReAct 执行态（验证未通过重试时复用入口）
        state.observations = []
        state.traces = []
        state.react_traces = []
        state.previous_result = None
        state.history_summary = None
        state.status = "running"
        save_state(state, state.run_id)
        return run_react_loop(state, mcp_manager)
    return _run_plan_execute_loop(state, mcp_manager)


def run_agent(
    user_input: str, run_id: str, user_id: str, mcp_manager: MCPManager = None
) -> AgentState:
    # ---- P5: 审计日志 - 任务开始 ----
    log_event(
        run_id=run_id,
        event_type="task_start",
        data={
            "user_id": user_id,
            "user_input": user_input,
        },
    )

    state = load_state(run_id)

    if state is None:
        state = AgentState(run_id=run_id, user_input=user_input)
        plan = planner(user_input, user_id)
        state.plan = plan.steps
        # P1：保存可验证目标与验收标准（外部状态即真相源，不依赖上下文窗口）
        state.goal = plan.goal
        state.success_criteria = plan.success_criteria
        save_state(state, run_id)

        # ---- P5: 审计日志 - 规划完成 ----
        log_event(
            run_id=run_id,
            event_type="plan_generated",
            data={
                "goal": plan.goal,
                "success_criteria": plan.success_criteria,
                "steps_count": len(plan.steps),
                "need_tools": plan.need_tools,
                "need_knowledge": plan.need_knowledge,
                "need_skill": plan.need_skill,
            },
        )

        # 普通问答，直接结束（这类任务 success_criteria 通常即"回答了问题"，
        # 仍可走验证；但为保持旧行为，普通问答直通后由验证环节把关）
        if not plan.need_tools and not plan.need_knowledge and not plan.need_skill:
            state.final_output = plan.direct_answer
            # 落到统一的收敛验证（若开启）
            if VERIFY_ON_FINISH and state.success_criteria:
                state = _convergence_check(state, user_id)
            else:
                state.status = "done"
                save_state(state, run_id)
                _remember(state, user_id, user_input)

            # ---- P5: 审计日志 - 任务完成（直接回答） ----
            log_event(
                run_id=run_id,
                event_type="task_completed",
                data={
                    "status": state.status,
                    "path": "direct_answer",
                },
            )

            return state

        # 高层复合任务，直接调用技能执行器（保留原直通路径）
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
            if VERIFY_ON_FINISH and state.success_criteria:
                state = _convergence_check(state, user_id)
            else:
                state.status = "done"
                save_state(state, run_id)
                _remember(state, user_id, user_input)

            # ---- P5: 审计日志 - 任务完成（技能执行） ----
            log_event(
                run_id=run_id,
                event_type="task_completed",
                data={
                    "status": state.status,
                    "path": "skill_execution",
                    "skill_name": plan.skill_name,
                },
            )

            return state

    # ---- 收敛闭环：execute → verify → 未达成则重规划再 execute ----
    eval_count = 0
    # P4：验证签名历史，用于停滞检测（连续 K 轮相同签名视为无进展）
    verification_signatures: list = []
    while True:
        # ReAct 路径下状态可能已被 run_react_loop 置为 done；Plan 路径下需防御空 plan
        if (
            not USE_REACT_LOOP
            and state.status == "running"
            and state.current_step >= len(state.plan)
        ):
            break

        state = _execute_task(state, mcp_manager)

        # 执行失败直接返回
        if state.status == "failed":
            return state

        # 已 done（执行完成），进入收敛验证
        if VERIFY_ON_FINISH and state.success_criteria:
            eval_count += 1
            if eval_count > MAX_GOAL_EVALUATIONS:
                # 超过评估上限仍未达成：诚实标记为 done（步骤完成）但非 goal_achieved，
                # 并附上最后一次验证结论，避免无限循环
                state.status = "done"
                state.error = (
                    f"goal not verified after {MAX_GOAL_EVALUATIONS} evaluations: "
                    f"{state.verification.reason if state.verification else 'unknown'}"
                )
                save_state(state, run_id)
                _remember(state, user_id, user_input)
                return state

            state = _convergence_check(state, user_id)
        else:
            # 未开启验证：沿用旧行为，执行完成即结束
            state.status = "done"
            save_state(state, run_id)
            _remember(state, user_id, user_input)
            return state

        # 收敛判定后的状态处理
        if state.status == "goal_achieved":
            _remember(state, user_id, user_input)

            # ---- P5: 审计日志 - 目标达成 ----
            log_event(
                run_id=state.run_id,
                event_type="task_completed",
                data={
                    "status": "goal_achieved",
                    "iterations": state.iterations,
                    "total_tokens": state.total_tokens,
                },
            )

            return state
        if state.status == "failed":

            # ---- P5: 审计日志 - 任务失败 ----
            log_event(
                run_id=state.run_id,
                event_type="task_failed",
                data={
                    "error": state.error,
                    "iterations": state.iterations,
                },
            )

            return state

        # P4：记录本次验证签名，供停滞检测
        verification_signatures.append(_verification_signature(state.verification))

        # P4：成本护栏——超 token 预算则终止
        if budget_exceeded(state):
            state.status = "failed"
            state.error = (
                f"token budget exceeded: {state.total_tokens} >= configured limit"
            )
            save_state(state, run_id)

            # ---- P5: 审计日志 - 成本超限 ----
            log_event(
                run_id=state.run_id,
                event_type="cost_budget_exceeded",
                data={
                    "total_tokens": state.total_tokens,
                    "cost_estimate": state.cost_estimate,
                },
            )

            return state

        # P4：停滞检测——连续 K 轮验证无新进展则暂停，等待人工介入
        if detect_stagnation(state, verification_signatures):
            state = mark_stagnation(state)
            save_state(state, run_id)

            # ---- P5: 审计日志 - 检测到停滞 ----
            log_event(
                run_id=state.run_id,
                event_type="stagnation_detected",
                data={
                    "stagnation_count": state.stagnation_count,
                    "iterations": state.iterations,
                },
            )

            return state

        # verification.next_action == continue/refine：触发重规划再来一轮
        v = state.verification

        # next_action == finish 表示 checker 认为不应再重试（含 checker 自身故障的退化情形）
        # 此时收尾返回 done（步骤完成但非 goal_achieved），避免无限重试
        if v.next_action == "finish":
            state.status = "done"
            save_state(state, run_id)
            _remember(state, user_id, user_input)
            return state

        if USE_REACT_LOOP:
            # ReAct 路径重试：把验证反馈追加进 history_summary，让下一轮 ReAct 看到并修正
            feedback = (
                f"[上轮验证未通过] reason={v.reason}; evidence={v.evidence}; "
                f"hint={v.next_action}. 请换一种方式达成目标。"
            )
            state.history_summary = (
                (state.history_summary + "\n" if state.history_summary else "") + feedback
            )
            state.status = "running"
            save_state(state, run_id)
            continue

        # Plan 路径重试：基于验证反馈重规划
        state.current_step = 0
        state.previous_result = None
        state.observations = []
        state.traces = []
        state.step_retry_count = 0
        state.status = "running"
        # 基于验证反馈重规划：构造一个"伪失败 trace"复用 replan_from_failure
        # 它会读取已完成步骤/观察与"失败信息"生成剩余步骤
        feedback_trace = ExecutionTrace(
            step_index=0,
            raw_tool="(goal_verification)",
            raw_arguments={},
            success=False,
            error=(
                f"verification failed: {v.reason}. evidence: {v.evidence}. "
                f"strategy hint: {v.next_action}"
            ),
        )
        new_plan = replan_from_failure(state, feedback_trace)
        state.plan = new_plan.steps
        state.replan_count += 1
        save_state(state, run_id)


def _convergence_check(state: AgentState, user_id: str) -> AgentState:
    """调用 checker 验证目标是否达成，并据此更新 state。"""
    final_output = str(state.final_output) if state.final_output is not None else ""

    # ---- P5: 审计日志 - 开始验证 ----
    log_event(
        run_id=state.run_id,
        event_type="goal_verification_start",
        data={
            "goal": state.goal,
            "success_criteria": state.success_criteria,
            "iteration": state.iterations,
        },
    )

    try:
        result = evaluate_goal(state, state.success_criteria, final_output)
    except Exception as e:
        # checker 自身故障不应阻塞任务：退化为"步骤完成即 done"，
        # 但仍写入一个明确的未判定 verification，保证主循环访问时不为 None。
        from orion_agent_runtime.core.models import VerificationResult

        state.verification = VerificationResult(
            achieved=False,
            reason=f"goal evaluator failed: {e}",
            evidence="",
            next_action="finish",  # checker 故障时不再重试，直接收尾
        )
        state.status = "done"
        state.error = f"goal evaluator failed: {e}"
        save_state(state, state.run_id)
        _remember(state, user_id, state.user_input)

        # ---- P5: 审计日志 - 验证失败 ----
        log_event(
            run_id=state.run_id,
            event_type="goal_verification_failed",
            data={
                "error": str(e),
                "reason": state.verification.reason,
                "next_action": state.verification.next_action,
            },
        )

        return state

    # P4：粗略累计本轮 checker 的 token 消耗（输入 prompt 长度 + 输出长度）
    accumulate_usage(state, estimate_tokens(final_output) + estimate_tokens(result.reason))

    state.verification = result
    state.iterations += 1
    save_state(state, state.run_id)

    # ---- P5: 审计日志 - 验证完成 ----
    log_event(
        run_id=state.run_id,
        event_type="goal_verification_completed",
        data={
            "achieved": result.achieved,
            "reason": result.reason,
            "evidence": result.evidence,
            "next_action": result.next_action,
            "iteration": state.iterations,
        },
    )

    if result.achieved:
        state.status = "goal_achieved"
        save_state(state, state.run_id)
    # 未达成保持 status=done（步骤已完成），由外层根据 verification 决定是否重规划
    return state


def _remember(state: AgentState, user_id: str, user_input: str) -> None:
    """任务结束后写回长期记忆（抽函数复用）。"""
    summary = build_task_summary(state)
    memory.remember_task_summary(
        user_id=user_id,
        summary=summary,
        metadata={"run_id": state.run_id, "user_input": user_input},
    )
