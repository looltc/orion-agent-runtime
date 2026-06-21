"""ReAct 内循环（Reasoning + Acting）—— Loop Engineering 的 Agent 核心引擎。

与旧的"planner 一次出全量步骤、executor 顺序执行"不同，ReAct 循环：
  每轮 = LLM 见 {goal, 工具目录, 已观察历史} → 输出 {thought, action} → 执行 → 观察回灌 → 下一轮

这是真正的工具调用循环：下一步该用什么工具、什么参数，由上一步的观察结果动态决定，
而非一次性固定。对应 Loop Engineering 的"内循环"。

终止条件（任一满足）：
  1. LLM 输出 action.type == "finish"（任务完成）
  2. 达到 MAX_ITERATIONS 上限（红线：每个循环都有明确上限）
  3. goal_checker 验证通过（P1 已建，P2 内嵌为隔轮检查）

历史压缩：观察序列超过 HISTORY_COMPRESS_THRESHOLD 时，触发摘要压缩写入 state，
避免上下文窗口爆炸——遵循"不信任上下文窗口作为持久化存储"。
"""

from typing import Optional

from orion_agent_runtime.core.executor import execute_step
from orion_agent_runtime.core.models import (
    AgentState,
    Observation,
    PlanStep,
    ReactAction,
    ReactTrace,
)
from orion_agent_runtime.core.storage import save_state
from orion_agent_runtime.llm_provider import get_llm_client
from orion_agent_runtime.tools.registry import build_tool_catalog
from orion_agent_runtime.audit.audit_log import log_event

# 红线：每个循环都有明确的最大迭代上限，永不省略。
MAX_ITERATIONS = 12
# 观察序列超过此阈值时触发历史压缩
HISTORY_COMPRESS_THRESHOLD = 8


def _get_text(message) -> str:
    text = message.content or getattr(message, "reasoning_content", None)
    if not text:
        raise ValueError("empty LLM output from react loop")
    return text


def _extract_json_text(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no valid JSON found in react decision")
    return raw[start : end + 1]


def _format_observation_history(state: AgentState) -> str:
    """格式化已观察序列供 LLM 参考；过长时使用压缩摘要。"""
    if state.history_summary:
        return f"[历史摘要]\n{state.history_summary}\n\n[本轮新观察]\n" + _recent_observations(
            state
        )

    if not state.observations:
        return "(尚未执行任何工具)"
    lines = []
    for i, obs in enumerate(state.observations, 1):
        result_str = str(obs.result)
        # 截断超长观察，避免单条吃掉上下文
        if len(result_str) > 500:
            result_str = result_str[:500] + "...(截断)"
        lines.append(f"  第{i}轮 [{obs.tool}]: {result_str}")
    return "\n".join(lines)


def _recent_observations(state: AgentState, n: int = 3) -> str:
    recent = state.observations[-n:]
    if not recent:
        return "(无)"
    return "\n".join(
        f"  [{o.tool}]: {str(o.result)[:300]}" for o in recent
    )


def _call_react_llm(prompt: str) -> ReactAction:
    """调用 maker LLM 产出单步 ReactAction（结构化输出）。"""
    client, model_name = get_llm_client(role="maker")
    response = client.chat.completions.create(
        model=model_name,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "react_action",
                "schema": ReactAction.model_json_schema(),
                "strict": True,
            },
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个 ReAct 推理-行动代理。基于当前目标和已观察的历史，"
                    "决定下一步动作：调用一个工具（call_tool）或宣告完成（finish）。"
                    "每一步都要先在 thought 中简述推理，再给出动作。"
                    "必须从可用工具列表中选择工具，参数需符合工具 schema。"
                    "当已收集到足够信息可以回答目标时，输出 finish 并给出 answer。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    raw = _get_text(response.choices[0].message)
    try:
        return ReactAction.model_validate_json(raw)
    except Exception:
        return ReactAction.model_validate_json(_extract_json_text(raw))


def _compress_history(state: AgentState) -> None:
    """当观察序列过长时，把早期观察压缩成摘要写入 state.history_summary。

    策略：保留最近若干轮原始观察，更早的合并进摘要。
    为避免额外 LLM 开销，这里用确定性文本压缩（取结果摘要），
    后续可升级为 LLM 摘要（复用 memory_summarizer 思路）。
    """
    if len(state.observations) <= HISTORY_COMPRESS_THRESHOLD:
        return

    keep_n = HISTORY_COMPRESS_THRESHOLD // 2
    to_compress = state.observations[:-keep_n]
    existing = state.history_summary or ""

    compressed_parts = []
    for obs in to_compress:
        result_str = str(obs.result)[:200]
        compressed_parts.append(f"[{obs.tool}]:{result_str}")

    state.history_summary = (
        (existing + "\n" if existing else "") + "\n".join(compressed_parts)
    )
    state.observations = state.observations[-keep_n:]


def _react_decide(state: AgentState) -> ReactAction:
    """根据当前状态让 LLM 决策下一步。"""
    tool_catalog = build_tool_catalog()

    prompt = f"""
        【目标】
        {state.goal or state.user_input}

        【验收标准】
        {chr(10).join('- ' + c for c in state.success_criteria) or '(未指定)'}

        【可用工具】
        {tool_catalog}

        【已观察历史】
        {_format_observation_history(state)}

        请决定下一步动作：
        - 若需要更多信息/计算，输出 call_tool（指定 tool 与 arguments）；
        - 若已能回答目标，输出 finish（在 answer 中给出最终答案）。

        只输出 JSON，格式：{{"thought":"...", "type":"call_tool"|"finish", "tool":"...", "arguments":{{...}}, "answer":"..."}}
        """.strip()

    return _call_react_llm(prompt)


def run_react_loop(state: AgentState, mcp_manager=None) -> AgentState:
    """执行 ReAct 内循环，直到 finish / 达到上限 / goal 达成。

    复用现有 executor.execute_step 执行工具调用（保持强校验+强容错+可追踪）。
    每轮落盘 state（外部状态即真相源，进程崩溃可恢复）。
    """
    # ---- P5: 审计日志 - ReAct 循环开始 ----
    log_event(
        run_id=state.run_id,
        event_type="react_loop_start",
        data={
            "goal": state.goal,
            "success_criteria": state.success_criteria,
            "max_iterations": MAX_ITERATIONS,
        },
    )

    iteration = 0
    while iteration < MAX_ITERATIONS:
        state.iterations = iteration + 1

        try:
            action = _react_decide(state)
        except Exception as e:
            # LLM 决策故障：以现有结果收尾并标记，不崩溃
            state.status = "failed"
            state.error = f"react decision failed at iteration {iteration}: {e}"
            save_state(state, state.run_id)

            # ---- P5: 审计日志 - LLM 决策失败 ----
            log_event(
                run_id=state.run_id,
                event_type="react_decision_failed",
                data={
                    "iteration": iteration,
                    "error": str(e),
                },
            )

            return state

        # 记录 thought→action 轨迹
        trace = ReactTrace(
            iteration=iteration + 1,
            thought=action.thought,
            action_type=action.type,
            tool=action.tool,
            arguments=action.arguments,
        )
        state.react_traces.append(trace)

        # ---- P5: 审计日志 - ReAct 决策 ----
        log_event(
            run_id=state.run_id,
            event_type="react_decision",
            data={
                "iteration": iteration,
                "thought": action.thought,
                "action_type": action.type,
                "tool": action.tool,
                "arguments": action.arguments,
            },
        )

        if action.type == "finish":
            state.final_output = action.answer
            state.previous_result = action.answer
            state.status = "done"
            save_state(state, state.run_id)

            # ---- P5: 审计日志 - ReAct 完成 ----
            log_event(
                run_id=state.run_id,
                event_type="react_loop_completed",
                data={
                    "iterations": iteration + 1,
                    "answer": action.answer,
                },
            )

            return state

        # call_tool：复用 executor 执行单步
        if not action.tool:
            # 无效决策：记入 trace 让 LLM 下一轮自行纠正
            trace.observation = "INVALID: call_tool without tool name"
            save_state(state, state.run_id)
            iteration += 1
            continue

        step = PlanStep(tool=action.tool, arguments=action.arguments)
        obs, exec_trace = execute_step(
            step=step,
            previous_result=state.previous_result,
            step_index=iteration + 1,
            mcp_manager=mcp_manager,
            run_id=state.run_id,
        )

        state.observations.append(obs)
        state.traces.append(exec_trace)
        trace.observation = obs.result
        trace.arguments = exec_trace.normalized_arguments

        # 工具失败：把错误作为观察回灌给 LLM，让它自行纠错（ReAct 的自我修正）
        if not exec_trace.success:
            trace.observation = f"TOOL_ERROR: {exec_trace.error}"
        else:
            state.previous_result = obs.result

        # 历史压缩（防上下文爆炸）
        _compress_history(state)

        save_state(state, state.run_id)
        iteration += 1

    # 达到 MAX_ITERATIONS 仍未 finish：以最后一个结果收尾
    state.final_output = state.previous_result
    state.status = "done"
    state.error = (
        f"react loop reached MAX_ITERATIONS={MAX_ITERATIONS} without explicit finish"
    )
    save_state(state, state.run_id)

    # ---- P5: 审计日志 - ReAct 达到上限 ----
    log_event(
        run_id=state.run_id,
        event_type="react_loop_max_iterations",
        data={
            "max_iterations": MAX_ITERATIONS,
            "final_output": str(state.previous_result),
        },
    )

    return state
