"""AgentRuntime —— V2 事件驱动执行主循环。

设计文档第 7 节运行流程的事件驱动实现：
  Planner → Action → Observe → World → Reflect → 若未完成回到 Planner

最关键约束（设计文档第 7 节红线）：
  "Planner 每次只负责'下一步'，不要一次输出完整 50 步流程。"

与 V1 core/workflow.py 的区别：
- 全异步（asyncio 原生）
- 每步动作 emit 事件到 EventBus，WorldManager 自动更新世界状态
- 任务通过 Scheduler 管理状态（READY→RUNNING→DONE/FAILED/PAUSED）
- 复用 V1 的 LLM 决策逻辑（react_loop._react_decide 风格）+ checker（goal_evaluator）
- 复用 V1 的护栏：stagnation_detector + cost_guardrail（事件订阅者形态）

复用的 V1 资产（不改其源码）：
- core/react_loop._react_decide 的 prompt 构造与 LLM 调用风格
- core/goal_evaluator.evaluate_goal（Reflect 阶段的 checker）
- core/stagnation_detector / cost_guardrail（护栏）
- core/models.AgentState（作为运行态载体，与 V1 共享）
- tools.registry / mcp_manager（能力来源）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from orion_agent_runtime.audit.audit_log import log_event
from orion_agent_runtime.bus import EventBus, EventType, Event, make_event
from orion_agent_runtime.core.cost_guardrail import (
    accumulate_usage,
    budget_exceeded,
    estimate_tokens,
)
from orion_agent_runtime.core.goal_evaluator import evaluate_goal
from orion_agent_runtime.core.models import (
    AgentState,
    Observation,
    PlanStep,
    ReactAction,
    ReactTrace,
)
from orion_agent_runtime.core.stagnation_detector import (
    _verification_signature,
    detect_stagnation,
    mark_stagnation,
)
from orion_agent_runtime.kernel import Kernel
from orion_agent_runtime.llm_provider import get_llm_client
from orion_agent_runtime.runtime.executor_async import (
    AsyncApprovalHook,
    execute_step_async,
)
from orion_agent_runtime.scheduler import TaskStatus
from orion_agent_runtime.tools.registry import build_tool_catalog

logger = logging.getLogger(__name__)

# V2 循环上限（与 V1 react_loop.MAX_ITERATIONS 对齐）
MAX_ITERATIONS = 12
MAX_GOAL_EVALUATIONS = 3
HISTORY_COMPRESS_THRESHOLD = 8


class RunResult(BaseModel):
    """单次运行结果（V2 标准返回）。"""

    run_id: str
    task_id: str
    status: str  # done / goal_achieved / failed / paused
    final_output: Optional[Any] = None
    error: Optional[str] = None
    iterations: int = 0
    total_tokens: int = 0


class AgentRuntime:
    """事件驱动 Agent 运行时。

    用法：
        kernel = Kernel()
        await kernel.start()
        runtime = AgentRuntime(kernel)
        result = await runtime.run(goal="...", user_id="...", mcp_manager=mgr)
        await kernel.shutdown()
    """

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self.bus: EventBus = kernel.bus
        # 注入点：可替换 LLM 决策函数与 checker（测试用）
        self._decide_fn = None  # 默认用内置 _react_decide
        self._checker_fn = None  # 默认用 evaluate_goal
        self._approval_hook: Optional[AsyncApprovalHook] = None

    # ---- 测试注入点 ----
    def set_decide_fn(self, fn) -> None:
        """注入决策函数（mock LLM 测试用）。签名：async fn(state) -> ReactAction"""
        self._decide_fn = fn

    def set_checker_fn(self, fn) -> None:
        """注入 checker 函数（mock LLM 测试用）。签名：fn(state, criteria, output) -> VerificationResult"""
        self._checker_fn = fn

    def set_approval_hook(self, hook: AsyncApprovalHook) -> None:
        self._approval_hook = hook

    # ---- 主入口 ----
    async def run(
        self,
        goal: str,
        user_id: str,
        mcp_manager=None,
        *,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        success_criteria: Optional[List[str]] = None,
    ) -> RunResult:
        """执行一次完整运行（事件驱动闭环）。

        流程（设计文档第 7 节）：
        1. 创建 task（emit task.created）
        2. Scheduler 分配（READY → RUNNING）
        3. 循环：decide → execute_step_async → emit action → world 更新 → checker
        4. 终止：finish / 达上限 / goal_achieved / failed / paused
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        task_id = task_id or f"task-{run_id}"

        # ---- 审计：任务开始 ----
        log_event(run_id=run_id, event_type="task_start",
                  data={"user_id": user_id, "goal": goal, "task_id": task_id})

        # ---- 1. Kernel 创建 task ----
        self.kernel.scheduler.create_task(
            goal=goal,
            priority=0,
            task_id=task_id,
            success_criteria=success_criteria or [],
            run_id=run_id,
        )
        await self.bus.emit(make_event(
            EventType.TASK_CREATED, source="kernel", task_id=task_id, run_id=run_id,
            payload={"goal": goal, "success_criteria": success_criteria or []},
        ))

        # ---- 2. Scheduler 分配（READY → RUNNING）----
        self.kernel.scheduler.start(task_id)
        await self.bus.emit(make_event(
            EventType.TASK_UPDATED, source="scheduler", task_id=task_id, run_id=run_id,
            payload={"status": "running"},
        ))

        # ---- 3. 构造 AgentState（复用 V1 数据模型）----
        state = AgentState(
            run_id=run_id,
            user_input=goal,
            goal=goal,
            success_criteria=success_criteria or [],
        )

        # ---- 4. 事件驱动循环 ----
        verification_signatures: List[str] = []
        eval_count = 0
        result = await self._run_inner_loop(
            state, task_id, run_id, user_id, mcp_manager,
            verification_signatures,
        )

        # 若内层循环以 done 收尾且开启了验证，进入 Reflect
        if result.status == "done" and state.success_criteria:
            while eval_count < MAX_GOAL_EVALUATIONS:
                eval_count += 1
                verification_result = await self._reflect(
                    state, task_id, run_id, user_id
                )
                verification_signatures.append(_verification_signature(verification_result))

                if verification_result.achieved:
                    result.status = "goal_achieved"
                    break

                # 成本护栏
                if budget_exceeded(state):
                    result.status = "failed"
                    result.error = f"token budget exceeded: {state.total_tokens}"
                    break

                # 停滞检测
                if detect_stagnation(state, verification_signatures):
                    state = mark_stagnation(state)
                    result.status = "paused"
                    result.error = "stagnation detected, awaiting human intervention"
                    self.kernel.scheduler.pause(task_id)
                    break

                if verification_result.next_action == "finish":
                    # checker 认为不应再试
                    break

                # 否则继续一轮 ReAct 循环
                result = await self._run_inner_loop(
                    state, task_id, run_id, user_id, mcp_manager,
                    verification_signatures,
                )
                if result.status != "done":
                    break  # failed 或已达上限

        # ---- 5. 收尾 ----
        await self._finalize(state, task_id, run_id, user_id, result)
        return result

    # ---- 内层 ReAct 循环（Planner → Action → Observe）----
    async def _run_inner_loop(
        self,
        state: AgentState,
        task_id: str,
        run_id: str,
        user_id: str,
        mcp_manager,
        verification_signatures: List[str],
    ) -> RunResult:
        iteration = 0
        while iteration < MAX_ITERATIONS:
            state.iterations = iteration + 1

            # ---- Planner：下一步决策（设计文档红线：每次只产下一步）----
            try:
                action = await self._decide(state)
            except Exception as e:
                state.status = "failed"
                state.error = f"react decision failed at iteration {iteration}: {e}"
                log_event(run_id=run_id, event_type="react_decision_failed",
                          data={"iteration": iteration, "error": str(e)})
                return self._to_result(state, task_id, run_id, "failed")

            # 记录轨迹
            trace = ReactTrace(
                iteration=iteration + 1,
                thought=action.thought,
                action_type=action.type,
                tool=action.tool,
                arguments=action.arguments,
            )
            state.react_traces.append(trace)

            log_event(run_id=run_id, event_type="react_decision",
                      data={"iteration": iteration, "thought": action.thought,
                            "action_type": action.type, "tool": action.tool})

            # ---- finish：直接收尾 ----
            if action.type == "finish":
                state.final_output = action.answer
                state.previous_result = action.answer
                state.status = "done"
                log_event(run_id=run_id, event_type="react_loop_completed",
                          data={"iterations": iteration + 1})
                return self._to_result(state, task_id, run_id, "done")

            # ---- call_tool：执行 ----
            if not action.tool:
                trace.observation = "INVALID: call_tool without tool name"
                iteration += 1
                continue

            step = PlanStep(tool=action.tool, arguments=action.arguments)

            # emit action.requested
            await self.bus.emit(make_event(
                EventType.ACTION_REQUESTED, source="planner",
                task_id=task_id, run_id=run_id,
                payload={"tool": action.tool, "arguments": action.arguments},
            ))

            obs, exec_trace = await execute_step_async(
                step=step,
                previous_result=state.previous_result,
                step_index=iteration + 1,
                mcp_manager=mcp_manager,
                run_id=run_id,
                approval_hook=self._approval_hook,
            )
            state.observations.append(obs)
            state.traces.append(exec_trace)
            trace.observation = obs.result

            # emit action.completed/failed（world 会自动更新）
            if exec_trace.success:
                state.previous_result = obs.result
                await self.bus.emit(make_event(
                    EventType.ACTION_COMPLETED, source="executor",
                    task_id=task_id, run_id=run_id,
                    payload={"tool": action.tool, "result": obs.result,
                             "source": "tool"},
                ))
            else:
                trace.observation = f"TOOL_ERROR: {exec_trace.error}"
                await self.bus.emit(make_event(
                    EventType.ACTION_FAILED, source="executor",
                    task_id=task_id, run_id=run_id,
                    payload={"tool": action.tool, "error": exec_trace.error},
                ))

            # 历史压缩
            self._compress_history(state)

            iteration += 1

        # 达上限
        state.final_output = state.previous_result
        state.status = "done"
        state.error = f"react loop reached MAX_ITERATIONS={MAX_ITERATIONS}"
        log_event(run_id=run_id, event_type="react_loop_max_iterations",
                  data={"max_iterations": MAX_ITERATIONS})
        return self._to_result(state, task_id, run_id, "done")

    # ---- Reflect 阶段（checker）----
    async def _reflect(self, state: AgentState, task_id: str, run_id: str, user_id: str):
        final_output = str(state.final_output) if state.final_output is not None else ""
        log_event(run_id=run_id, event_type="goal_verification_start",
                  data={"goal": state.goal, "iteration": state.iterations})

        try:
            if self._checker_fn is not None:
                result = self._checker_fn(state, state.success_criteria, final_output)
            else:
                result = evaluate_goal(state, state.success_criteria, final_output)
        except Exception as e:
            from orion_agent_runtime.core.models import VerificationResult
            result = VerificationResult(
                achieved=False, reason=f"goal evaluator failed: {e}",
                next_action="finish",
            )
            log_event(run_id=run_id, event_type="goal_verification_failed",
                      data={"error": str(e)})
            state.verification = result
            return result

        accumulate_usage(state, estimate_tokens(final_output) + estimate_tokens(result.reason))
        state.verification = result
        state.iterations += 1
        log_event(run_id=run_id, event_type="goal_verification_completed",
                  data={"achieved": result.achieved, "reason": result.reason,
                        "next_action": result.next_action, "iteration": state.iterations})
        return result

    # ---- LLM 决策（默认实现，复用 react_loop 的 prompt 构造）----
    async def _decide(self, state: AgentState) -> ReactAction:
        if self._decide_fn is not None:
            return await self._decide_fn(state)
        return await self._react_decide_default(state)

    async def _react_decide_default(self, state: AgentState) -> ReactAction:
        """默认 LLM 决策（maker 角色，结构化输出）。

        复用 core/react_loop._react_decide 的 prompt 风格，但改为 async 兼容。
        OpenAI 同步客户端在 async 上下文中调用是安全的（I/O 阻塞但不死锁）；
        若需真正异步可换 AsyncOpenAI，此处保持与 V1 一致。
        """
        tool_catalog = build_tool_catalog()
        history = self._format_history(state)
        prompt = (
            f"【目标】\n{state.goal or state.user_input}\n\n"
            f"【验收标准】\n"
            + ("\n".join("- " + c for c in state.success_criteria) or "(未指定)")
            + f"\n\n【可用工具】\n{tool_catalog}\n\n"
            f"【已观察历史】\n{history}\n\n"
            "请决定下一步动作：call_tool 或 finish。只输出 JSON。"
        )
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
                {"role": "system", "content": (
                    "你是一个 ReAct 推理-行动代理。基于当前目标和历史，"
                    "决定下一步：call_tool 或 finish。"
                )},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        try:
            return ReactAction.model_validate_json(raw)
        except Exception:
            # 兜底：抽取 JSON 片段
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                return ReactAction.model_validate_json(raw[start: end + 1])
            raise ValueError(f"invalid react decision: {raw[:200]}")

    def _format_history(self, state: AgentState) -> str:
        if state.history_summary:
            recent = "\n".join(
                f"  [{o.tool}]: {str(o.result)[:300]}" for o in state.observations[-3:]
            )
            return f"[历史摘要]\n{state.history_summary}\n\n[本轮新观察]\n{recent}"
        if not state.observations:
            return "(尚未执行任何工具)"
        lines = []
        for i, obs in enumerate(state.observations, 1):
            r = str(obs.result)
            if len(r) > 500:
                r = r[:500] + "...(截断)"
            lines.append(f"  第{i}轮 [{obs.tool}]: {r}")
        return "\n".join(lines)

    def _compress_history(self, state: AgentState) -> None:
        if len(state.observations) <= HISTORY_COMPRESS_THRESHOLD:
            return
        keep_n = HISTORY_COMPRESS_THRESHOLD // 2
        to_compress = state.observations[:-keep_n]
        existing = state.history_summary or ""
        parts = [f"[{o.tool}]:{str(o.result)[:200]}" for o in to_compress]
        state.history_summary = (existing + "\n" if existing else "") + "\n".join(parts)
        state.observations = state.observations[-keep_n:]

    # ---- 收尾 ----
    def _to_result(self, state: AgentState, task_id: str, run_id: str, status: str) -> RunResult:
        return RunResult(
            run_id=run_id,
            task_id=task_id,
            status=status,
            final_output=state.final_output,
            error=state.error,
            iterations=state.iterations,
            total_tokens=state.total_tokens,
        )

    async def _finalize(self, state: AgentState, task_id: str, run_id: str,
                        user_id: str, result: RunResult) -> None:
        """更新 scheduler 状态 + emit 终态事件 + 写 episodic 记忆。"""
        try:
            if result.status == "goal_achieved" or result.status == "done":
                self.kernel.scheduler.complete(task_id, result=result.final_output)
            elif result.status == "failed":
                self.kernel.scheduler.fail(task_id, error=result.error or "unknown")
            # paused 已在调用处处理
        except (ValueError, KeyError):
            pass  # 状态机可能已终态

        # emit 终态事件
        terminal_event_type = (
            EventType.TASK_COMPLETED if result.status in {"done", "goal_achieved"}
            else EventType.TASK_FAILED if result.status == "failed"
            else EventType.TASK_PAUSED
        )
        await self.bus.emit(make_event(
            terminal_event_type, source="runtime",
            task_id=task_id, run_id=run_id,
            payload={
                "status": result.status,
                "iterations": result.iterations,
                "total_tokens": result.total_tokens,
                "final_output": str(result.final_output) if result.final_output else None,
            },
        ))

        # 写 episodic 记忆（设计文档第 4 节 memory.put）
        try:
            self.kernel.memory.put(
                key=str(result.final_output or "")[:200],
                value=str(result.final_output or ""),
                layer="episodic",
                user_id=user_id,
                metadata={
                    "run_id": run_id,
                    "task_id": task_id,
                    "status": result.status,
                    "iterations": result.iterations,
                    "goal": state.goal,
                    "steps": [{"tool": o.tool, "result": str(o.result)[:200]}
                              for o in state.observations],
                },
            )
        except Exception as e:
            logger.warning("episodic memory writeback failed: %s", e)

        log_event(run_id=run_id, event_type="task_completed",
                  data={"status": result.status, "iterations": result.iterations})
