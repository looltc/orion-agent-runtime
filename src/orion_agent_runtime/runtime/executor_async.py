"""异步 executor —— core/executor.py 的全异步重写（V2）。

V1 的 execute_step 在同步上下文里用 asyncio.run(mcp.call_tool_async) 桥接，
这是 sync/async 边界的"罪魁祸首"。V2 全异步，直接 await。

复用 V1 的核心逻辑（保持行为一致）：
- 参数归一化（normalize_tool_name / normalize_arguments）
- 幂等缓存（idempotency.IdempotencyCache）
- 安全护栏（guardrails）—— 改为 async hook
- 审计日志（audit_log.log_event）
- Pydantic 参数校验

差异：
- async def
- MCP 工具直接 await（去掉 asyncio.run）
- local 工具若 handler 是 coroutine 则 await
- 高风险审批改为可注入的 async hook（默认自动批准，避免阻塞）
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, Optional

from pydantic import ValidationError

from orion_agent_runtime.audit.audit_log import log_event
from orion_agent_runtime.core.idempotency import get_cache
from orion_agent_runtime.core.models import Observation, PlanStep, ExecutionTrace
from orion_agent_runtime.safety.guardrails import GuardrailConfig, get_guardrails
from orion_agent_runtime.tools.registry import get_tool
from orion_agent_runtime.utils.normalize import normalize_arguments, normalize_tool_name


class ToolExecutionError(Exception):
    pass


# 异步审批 hook 签名：(tool, arguments, context) -> (approved: bool, reason: str)
AsyncApprovalHook = Callable[[str, Dict[str, Any], str], Awaitable[tuple]]


async def _default_approval_hook(
    tool: str, arguments: Dict[str, Any], context: str
) -> tuple:
    """默认审批 hook：自动批准（V2 事件驱动 Runtime 不阻塞 stdin）。

    生产环境应注入真实审批服务（人工审批 UI / 策略引擎）。
    """
    return True, "auto-approved (default async hook)"


async def _check_approval_async(
    tool_name: str,
    arguments: Dict[str, Any],
    context: str,
    approval_hook: Optional[AsyncApprovalHook],
) -> tuple[bool, str, str]:
    """异步审批：若工具需要批准，调用 hook；返回 (approved, reason, approved_by)。"""
    if not GuardrailConfig.requires_approval(tool_name):
        return True, "Low risk", "system"
    hook = approval_hook or _default_approval_hook
    approved, reason = await hook(tool_name, arguments, context)
    return approved, reason, ("approver" if approved else "denied")


async def _call_tool(
    spec, normalized_args: Dict[str, Any], mcp_manager, tool_name: str
) -> Any:
    """调用 local 或 mcp 工具（local 支持 sync/async handler）。

    V1 的 _call_mcp_tool_sync 在同步上下文用 asyncio.run，V2 直接 await。
    """
    if spec.origin == "local":
        result = spec.handler(**normalized_args)
        # 若 local handler 是 coroutine（async def），await 它
        if inspect.isawaitable(result):
            result = await result
        return result
    if spec.origin == "mcp":
        if mcp_manager is None:
            raise ToolExecutionError(f"mcp_manager is required for MCP tool '{tool_name}'")
        return await mcp_manager.call_tool_async(tool_name, normalized_args)
    raise ToolExecutionError(f"unknown tool origin: {spec.origin}")


async def execute_step_async(
    step: PlanStep,
    previous_result: Any = None,
    step_index: int = 0,
    mcp_manager=None,
    run_id: str = "default",
    *,
    approval_hook: Optional[AsyncApprovalHook] = None,
) -> tuple[Observation, ExecutionTrace]:
    """异步执行单步工具调用。

    与 V1 execute_step 行为一致，但：
    - 全 async（MCP 直接 await，local async handler 也 await）
    - 审批改为 async hook（默认自动批准）
    """
    raw_tool = step.tool
    if not raw_tool or not isinstance(raw_tool, str):
        raise ToolExecutionError("step.tool is missing or invalid")

    raw_arguments = step.arguments if step.arguments is not None else {}
    if not isinstance(raw_arguments, dict):
        raise ToolExecutionError("step.arguments must be a dict")

    trace = ExecutionTrace(
        step_index=step_index,
        raw_tool=raw_tool,
        raw_arguments=raw_arguments,
    )

    log_event(
        run_id=run_id,
        event_type="tool_call_start",
        data={"tool": raw_tool, "arguments": raw_arguments, "step_index": step_index},
    )

    try:
        tool_name = normalize_tool_name(raw_tool)
        trace.normalized_tool = tool_name

        normalized_args = normalize_arguments(raw_arguments)
        for k, v in list(normalized_args.items()):
            if v is None:
                normalized_args[k] = previous_result
        trace.normalized_arguments = dict(normalized_args)

        # 幂等检查
        cache = get_cache()
        call_id = cache.make_call_id(run_id, tool_name, normalized_args, step_index)
        cached = cache.get(call_id)
        if cached is not None:
            success, result, error = cached
            trace.result = result
            trace.success = success
            trace.error = error
            obs = Observation(step=step_index, tool=tool_name, result=result)
            log_event(
                run_id=run_id,
                event_type="tool_call_cache_hit",
                data={
                    "tool": tool_name,
                    "step_index": step_index,
                    "call_id": call_id,
                    "success": success,
                },
            )
            return obs, trace

        spec = get_tool(tool_name)

        # local 工具：Pydantic 参数校验
        if spec.origin == "local":
            try:
                validated_args = spec.args_model.model_validate(normalized_args)
                normalized_args = validated_args.model_dump()
            except ValidationError as e:
                err = f"argument validation failed for tool '{tool_name}': {e}"
                trace.success = False
                trace.error = err
                log_event(
                    run_id=run_id,
                    event_type="tool_call_validation_failed",
                    data={"tool": tool_name, "error": err, "step_index": step_index},
                )
                obs = Observation(step=step_index, tool=raw_tool, result=None)
                return obs, trace

        # 审批（async hook）
        context = f"run_id={run_id}, step={step_index}, origin={spec.origin}"
        approved, reason, approved_by = await _check_approval_async(
            tool_name, normalized_args, context, approval_hook
        )
        if not approved:
            err = f"approval denied for tool '{tool_name}': {reason}"
            trace.success = False
            trace.error = err
            log_event(
                run_id=run_id,
                event_type="tool_call_rejected",
                data={"tool": tool_name, "error": err, "step_index": step_index},
            )
            obs = Observation(step=step_index, tool=raw_tool, result=None)
            return obs, trace

        log_event(
            run_id=run_id,
            event_type="tool_call_approved",
            data={
                "tool": tool_name,
                "approved_by": approved_by,
                "step_index": step_index,
                "origin": spec.origin,
            },
        )

        # 执行
        result = await _call_tool(spec, normalized_args, mcp_manager, tool_name)

        trace.result = result
        trace.success = True
        cache.put(call_id, True, result, None)

        log_event(
            run_id=run_id,
            event_type="tool_call_success",
            data={"tool": tool_name, "step_index": step_index, "call_id": call_id},
        )
        obs = Observation(step=step_index, tool=tool_name, result=result)
        return obs, trace

    except Exception as e:
        trace.success = False
        trace.error = str(e)
        log_event(
            run_id=run_id,
            event_type="tool_call_failed",
            data={"tool": raw_tool, "error": str(e), "step_index": step_index},
        )
        obs = Observation(step=step_index, tool=raw_tool, result=None)
        return obs, trace
