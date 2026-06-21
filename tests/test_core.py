"""核心模块单元测试。

覆盖不依赖真实 LLM 的部分：
- config：默认值与 env 覆盖
- llm_provider：工厂函数、向后兼容全局变量
- tools/registry：本地工具注册与执行
- core/executor：单步执行、参数验证、previous_result 注入

依赖 LLM 的 planner / goal_evaluator 等在各自阶段补充（配合 mock）。
"""

import os

import pytest
from pydantic import ValidationError

from orion_agent_runtime.core.executor import execute_step, ToolExecutionError
from orion_agent_runtime.core.models import AgentState, PlanStep
from orion_agent_runtime.tools.registry import get_tool, list_tools, build_tool_catalog


# ---------- config ----------

def test_config_defaults_preserve_old_behavior(monkeypatch):
    """无 env 时，config 应回落到旧的硬编码默认值（向后兼容）。"""
    # 清掉可能存在的 env
    for k in [
        "ORION_LLM_BASE_URL",
        "ORION_LLM_API_KEY",
        "ORION_LLM_MODEL",
        "ORION_MCP_FILESYSTEM_DIRS",
    ]:
        monkeypatch.delenv(k, raising=False)

    from orion_agent_runtime import config

    cfg = config.get_config(reload=True)
    assert cfg.llm_base_url == "http://localhost:1234/v1"
    assert cfg.llm_api_key == "local-1234567890abcdef"
    assert cfg.llm_model == "local-model"
    assert cfg.mcp_filesystem_dirs == ()


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("ORION_LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("ORION_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("ORION_MCP_FILESYSTEM_DIRS", "/a, /b , /c")

    from orion_agent_runtime import config

    cfg = config.get_config(reload=True)
    assert cfg.llm_base_url == "https://api.example.com/v1"
    assert cfg.llm_model == "gpt-test"
    assert cfg.mcp_filesystem_dirs == ("/a", "/b", "/c")


def test_config_checker_falls_back_to_main(monkeypatch):
    """checker 未单独配置时应回落到主 LLM（P0-P3 单模型即可运行）。"""
    monkeypatch.delenv("ORION_CHECKER_LLM_MODEL", raising=False)
    monkeypatch.setenv("ORION_LLM_MODEL", "main-model")
    from orion_agent_runtime import config

    cfg = config.get_config(reload=True)
    assert cfg.checker_llm.model == "main-model"


# ---------- llm_provider 向后兼容 ----------

def test_llm_provider_backward_compat():
    """旧代码 `from llm_provider import client, MODEL_NAME` 仍可用。"""
    from orion_agent_runtime import llm_provider

    assert llm_provider.client is not None
    assert isinstance(llm_provider.MODEL_NAME, str)
    # 工厂函数也工作
    c, m = llm_provider.get_llm_client(role="maker")
    assert c is not None
    assert isinstance(m, str)


# ---------- registry ----------

def test_registry_has_local_tools():
    """add / mul 在 tools 包导入时自动注册。"""
    import orion_agent_runtime.tools  # noqa: F401  触发注册

    names = {t.name for t in list_tools()}
    assert "add" in names
    assert "mul" in names


def test_registry_unknown_tool_raises():
    with pytest.raises(KeyError):
        get_tool("definitely_not_a_tool_xyz")


def test_build_tool_catalog_shape():
    import orion_agent_runtime.tools  # noqa: F401

    catalog = build_tool_catalog()
    assert "tools" in catalog
    local = [t for t in catalog["tools"] if t["name"] == "add"][0]
    assert local["origin"] == "local"
    assert "parameters" in local


# ---------- executor ----------

def test_executor_local_tool_success():
    """本地工具 add 被正确执行并产出 Observation + 成功 trace。"""
    step = PlanStep(tool="add", arguments={"a": 2, "b": 3})
    obs, trace = execute_step(step=step, step_index=1)

    assert trace.success is True
    assert trace.normalized_tool == "add"
    assert obs.result == 5


def test_executor_argument_validation_failure():
    """参数类型错误应被捕获为失败 trace，而非抛异常（强容错）。"""
    step = PlanStep(tool="add", arguments={"a": "x", "b": 3})
    obs, trace = execute_step(step=step, step_index=1)

    assert trace.success is False
    assert trace.error is not None
    assert "validation failed" in trace.error.lower() or "argument validation failed" in trace.error.lower()


def test_executor_previous_result_injection():
    """参数值为 None 时应被 previous_result 注入（步骤间数据流）。"""
    # 构造：第一个 step 算出 5，第二个 step 的 b 用 None 占位，期望注入为 5
    step = PlanStep(tool="mul", arguments={"a": 10, "b": None})
    obs, trace = execute_step(step=step, previous_result=5, step_index=2)

    assert trace.success is True
    assert obs.result == 50
    # 注入应在 normalized_arguments 中可见
    assert trace.normalized_arguments["b"] == 5


def test_executor_missing_tool_rejected():
    step = PlanStep(tool="no_such_tool", arguments={})
    obs, trace = execute_step(step=step, step_index=1)

    assert trace.success is False
    assert "unknown tool" in trace.error.lower()


def test_executor_missing_tool_field_raises():
    """step.tool 缺失属于契约错误，应直接抛 ToolExecutionError（非容错范围）。"""
    step = PlanStep(tool="", arguments={})
    with pytest.raises(ToolExecutionError):
        execute_step(step=step, step_index=1)
        
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
