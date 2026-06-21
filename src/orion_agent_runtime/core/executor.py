from typing import Any, Dict
import asyncio

from pydantic import ValidationError

from orion_agent_runtime.core.idempotency import get_cache
from orion_agent_runtime.core.models import PlanStep, Observation, ExecutionTrace
from orion_agent_runtime.utils.normalize import normalize_arguments, normalize_tool_name
from orion_agent_runtime.tools.registry import get_tool
from orion_agent_runtime.audit.audit_log import log_event
from orion_agent_runtime.safety.guardrails import (
    ApprovalAction,
    ApprovalResult,
    GuardrailConfig,
    get_guardrails,
)

# 强校验 + 强容错 + 可追踪 + 幂等(P3) executor + 审计(P5)


class ToolExecutionError(Exception):
    pass


def _build_trace(
    step_index: int,
    raw_tool: str,
    raw_arguments: Dict[str, Any],
) -> ExecutionTrace:
    return ExecutionTrace(
        step_index=step_index,
        raw_tool=raw_tool,
        raw_arguments=raw_arguments,
    )


def _call_mcp_tool_sync(mcp_manager, tool_name: str, arguments: dict[str, Any]):
    return asyncio.run(mcp_manager.call_tool_async(tool_name, arguments))


def execute_step(
    step: PlanStep,
    previous_result: Any = None,
    step_index: int = 0,
    mcp_manager=None,
    run_id: str = "default",
) -> tuple[Observation, ExecutionTrace]:
    """执行单步工具调用。

    P3 改造：加入幂等缓存。同一 (run_id, step_index, tool, arguments) 的重试
    命中缓存直接返回，真实副作用只发生一次。
    """
    raw_tool = step.tool
    if not raw_tool or not isinstance(raw_tool, str):
        raise ToolExecutionError("step.tool is missing or invalid")

    raw_arguments = step.arguments
    if raw_arguments is None:
        raw_arguments = {}

    if not isinstance(raw_arguments, dict):
        raise ToolExecutionError("step.arguments must be a dict")

    trace = _build_trace(
        step_index=step_index,
        raw_tool=raw_tool,
        raw_arguments=raw_arguments,
    )

    # ---- P5: 审计日志 - 工具调用前记录 ----
    log_event(
        run_id=run_id,
        event_type="tool_call_start",
        data={
            "tool": raw_tool,
            "arguments": raw_arguments,
            "step_index": step_index,
        },
    )

    try:
        tool_name = normalize_tool_name(raw_tool)
        trace.normalized_tool = tool_name

        normalized_args = normalize_arguments(raw_arguments)
        for k, v in list(normalized_args.items()):
            if v is None:
                normalized_args[k] = previous_result

        trace.normalized_arguments = dict(normalized_args)

        # ---- P3: 幂等检查（用注入 previous_result 后的真实参数算 key）----
        cache = get_cache()
        call_id = cache.make_call_id(run_id, tool_name, normalized_args, step_index)
        cached = cache.get(call_id)
        if cached is not None:
            success, result, error = cached
            trace.result = result
            trace.success = success
            trace.error = error
            obs = Observation(step=step_index, tool=tool_name, result=result)

            # ---- P5: 审计日志 - 缓存命中 ----
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

        if spec.origin == "local":
            try:
                validated_args = spec.args_model.model_validate(normalized_args)
            except ValidationError as e:
                err = f"argument validation failed for tool '{tool_name}': {e}"
                trace.success = False
                trace.error = err
                # 参数错误不入缓存（重试时参数可能被修正）

                # ---- P5: 审计日志 - 参数校验失败 ----
                log_event(
                    run_id=run_id,
                    event_type="tool_call_validation_failed",
                    data={
                        "tool": tool_name,
                        "error": err,
                        "step_index": step_index,
                    },
                )

                obs = Observation(step=step_index, tool=raw_tool, result=None)
                return obs, trace

            # ---- P5: 安全护栏 - 高风险工具需要人工批准 ----
            approval_result: ApprovalResult = ApprovalResult(
                action=ApprovalAction.APPROVE,
                reason="Low risk",
                approved_by="system",
            )
            if GuardrailConfig.requires_approval(tool_name):
                try:
                    guardrails = get_guardrails()
                    context = f"run_id={run_id}, step={step_index}"
                    approval_result = guardrails.check_before_execution(
                        tool_name=tool_name,
                        arguments=normalized_args,
                        context=context,
                    )
                    # 记录批准
                    log_event(
                        run_id=run_id,
                        event_type="tool_call_approved",
                        data={
                            "tool": tool_name,
                            "approved_by": approval_result.approved_by,
                            "step_index": step_index,
                        },
                    )
                except Exception as approval_error:
                    # 批准失败，记录并返回错误
                    err = f"approval required but denied for tool '{tool_name}': {approval_error}"
                    trace.success = False
                    trace.error = err
                    log_event(
                        run_id=run_id,
                        event_type="tool_call_rejected",
                        data={
                            "tool": tool_name,
                            "error": err,
                            "step_index": step_index,
                        },
                    )
                    obs = Observation(step=step_index, tool=raw_tool, result=None)
                    return obs, trace

            result = spec.handler(**validated_args.model_dump())

        elif spec.origin == "mcp":
            if mcp_manager is None:
                err = f"mcp_manager is required for MCP tool '{tool_name}'"
                trace.success = False
                trace.error = err

                # ---- P5: 审计日志 - MCP 管理器缺失 ----
                log_event(
                    run_id=run_id,
                    event_type="tool_call_mcp_manager_missing",
                    data={
                        "tool": tool_name,
                        "error": err,
                        "step_index": step_index,
                    },
                )

                obs = Observation(step=step_index, tool=raw_tool, result=None)
                return obs, trace

            # ---- P5: 安全护栏 - MCP 工具也需要批准 ----
            if GuardrailConfig.requires_approval(tool_name):
                try:
                    guardrails = get_guardrails()
                    context = f"run_id={run_id}, step={step_index}, origin=mcp"
                    approval_result = guardrails.check_before_execution(
                        tool_name=tool_name,
                        arguments=normalized_args,
                        context=context,
                    )
                    log_event(
                        run_id=run_id,
                        event_type="tool_call_approved",
                        data={
                            "tool": tool_name,
                            "approved_by": approval_result.approved_by,
                            "step_index": step_index,
                            "origin": "mcp",
                        },
                    )
                except Exception as approval_error:
                    err = f"approval required but denied for MCP tool '{tool_name}': {approval_error}"
                    trace.success = False
                    trace.error = err
                    log_event(
                        run_id=run_id,
                        event_type="tool_call_rejected",
                        data={
                            "tool": tool_name,
                            "error": err,
                            "step_index": step_index,
                            "origin": "mcp",
                        },
                    )
                    obs = Observation(step=step_index, tool=raw_tool, result=None)
                    return obs, trace

            result = _call_mcp_tool_sync(mcp_manager, tool_name, normalized_args)

        else:
            raise ToolExecutionError(f"unknown tool origin: {spec.origin}")

        trace.result = result
        trace.success = True
        # 成功结果入缓存：重试时直接命中，副作用不重复
        cache.put(call_id, True, result, None)

        # ---- P5: 审计日志 - 工具调用成功 ----
        log_event(
            run_id=run_id,
            event_type="tool_call_success",
            data={
                "tool": tool_name,
                "step_index": step_index,
                "call_id": call_id,
            },
        )

        obs = Observation(step=step_index, tool=tool_name, result=result)
        return obs, trace

    except Exception as e:
        trace.success = False
        trace.error = str(e)

        # ---- P5: 审计日志 - 工具调用失败 ----
        log_event(
            run_id=run_id,
            event_type="tool_call_failed",
            data={
                "tool": raw_tool,
                "error": str(e),
                "step_index": step_index,
            },
        )

        obs = Observation(step=step_index, tool=raw_tool, result=None)
        return obs, trace
