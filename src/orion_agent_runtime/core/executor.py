from typing import Any, Dict
import asyncio

from pydantic import ValidationError

from orion_agent_runtime.core.models import PlanStep, Observation, ExecutionTrace
from orion_agent_runtime.utils.normalize import normalize_arguments, normalize_tool_name
from orion_agent_runtime.tools.registry import get_tool

# 强校验 + 强容错 + 可追踪 executor


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
) -> tuple[Observation, ExecutionTrace]:
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

    try:
        tool_name = normalize_tool_name(raw_tool)
        trace.normalized_tool = tool_name

        spec = get_tool(tool_name)

        normalized_args = normalize_arguments(raw_arguments)
        for k, v in list(normalized_args.items()):
            if v is None:
                normalized_args[k] = previous_result

        trace.normalized_arguments = dict(normalized_args)

        if spec.origin == "local":
            try:
                validated_args = spec.args_model.model_validate(normalized_args)
            except ValidationError as e:
                raise ToolExecutionError(
                    f"argument validation failed for tool '{tool_name}': {e}"
                ) from e

            result = spec.handler(**validated_args.model_dump())

        elif spec.origin == "mcp":
            if mcp_manager is None:
                raise ToolExecutionError(
                    f"mcp_manager is required for MCP tool '{tool_name}'"
                )

            result = _call_mcp_tool_sync(mcp_manager, tool_name, normalized_args)

        else:
            raise ToolExecutionError(f"unknown tool origin: {spec.origin}")

        trace.result = result
        trace.success = True

        obs = Observation(
            step=step_index,
            tool=tool_name,
            result=result,
        )
        return obs, trace

    except Exception as e:
        trace.success = False
        trace.error = str(e)
        obs = Observation(
            step=step_index,
            tool=raw_tool,
            result=None,
        )
        return obs, trace
