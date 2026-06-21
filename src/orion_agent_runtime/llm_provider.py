"""LLM 客户端工厂。

改造自原来的硬编码单例：现在由 config 驱动，支持按角色创建不同客户端。

兼容性：保留模块级 `client` / `MODEL_NAME`，沿用旧导入路径
（planner / answer_synthesizer / skill_executor 仍可 `from ... import client, MODEL_NAME`）。
P4 起 maker/checker 角色通过 `get_llm_client(role=...)` 显式区分。
"""

from openai import OpenAI

from orion_agent_runtime.config import LLMConfig, get_config


def get_llm_client(role: str = "maker"):
    """按角色创建 OpenAI 兼容客户端。

    role="maker"  → 主生成模型（planner / react 循环 / skill 执行）
    role="checker" → 验证模型（goal_evaluator），缺省与 maker 相同
    """
    cfg = get_config()
    llm_cfg: LLMConfig = cfg.checker_llm if role == "checker" else cfg.llm
    return OpenAI(base_url=llm_cfg.base_url, api_key=llm_cfg.api_key), llm_cfg.model


def get_llm_model(role: str = "maker") -> str:
    """仅取角色对应的模型名。"""
    cfg = get_config()
    return (cfg.checker_llm if role == "checker" else cfg.llm).model


# 向后兼容：旧代码 `from llm_provider import client, MODEL_NAME` 仍可用。
# 惰性初始化以保证 import 时不强制要求 env 已就绪。
client, MODEL_NAME = get_llm_client(role="maker")
