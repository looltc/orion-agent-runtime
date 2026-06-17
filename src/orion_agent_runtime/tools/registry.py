from typing import Any, Callable, Dict, List
from pydantic import BaseModel
from orion_agent_runtime.core.models import ToolSpec

# 工具注册中心，负责工具的注册和查询。

_TOOL_REGISTRY: Dict[str, ToolSpec] = {}


def register_tool(name: str, description: str, args_model: type[BaseModel]):
    def decorator(func: Callable[..., Any]):
        spec = ToolSpec(
            name=name,
            description=description,
            origin="local",
            args_model=args_model,
            handler=func,
        )
        _TOOL_REGISTRY[name] = spec
        return func

    return decorator


def register_mcp_tool(
    name: str,
    description: str,
    input_schema: dict,
    server_name: str,
    remote_name: str,
):
    spec = ToolSpec(
        name=name,
        description=description,
        origin="mcp",
        input_schema=input_schema,
        server_name=server_name,
        remote_name=remote_name,
    )
    _TOOL_REGISTRY[name] = spec


def get_tool(name: str) -> ToolSpec:
    if name not in _TOOL_REGISTRY:
        raise KeyError(f"unknown tool: {name}")
    return _TOOL_REGISTRY[name]


def list_tools() -> List[ToolSpec]:
    return list(_TOOL_REGISTRY.values())


def build_tool_catalog() -> dict:
    """
    给 LLM / structured output / tool calling 用的统一工具描述。
    """
    catalog = []
    for spec in list_tools():
        if spec.origin == "local":
            parameters = spec.args_model.model_json_schema() if spec.args_model else {}
        else:
            parameters = spec.input_schema or {}

        catalog.append(
            {
                "name": spec.name,
                "description": spec.description,
                "origin": spec.origin,
                "parameters": parameters,
                "server_name": spec.server_name,
                "remote_name": spec.remote_name,
            }
        )
    return {"tools": catalog}
