"""集中式配置：从环境变量读取，提供合理默认值。

设计原则：
- 无 env 时行为与旧硬编码保持一致（向后兼容）。
- 所有外部化配置（LLM 端点、MCP 目录、运行时路径）统一从此处获取。
- 后续 P4 的 maker/checker 角色 LLM 也从此处扩展。

注意：环境变量读取集中在 get_config() 中，**不**放在 dataclass 字段默认值里
（否则 os.getenv 仅在类定义时求值一次，运行时改 env 不会生效）。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class LLMConfig:
    """单个 LLM 端点配置。"""

    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Config:
    # LLM：默认沿用旧硬编码（localhost LM Studio），可通过 env 覆盖
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # checker 角色（P4 预留）：缺省回落到主 LLM，保证 P0-P3 单模型即可运行
    checker_llm_base_url: str
    checker_llm_api_key: str
    checker_llm_model: str

    # 运行时状态目录
    runtime_state_dir: Path

    # MCP filesystem 允许访问的目录；为空则不配置 filesystem server
    mcp_filesystem_dirs: Tuple[str, ...] = ()

    @property
    def llm(self) -> LLMConfig:
        return LLMConfig(
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model,
        )

    @property
    def checker_llm(self) -> LLMConfig:
        """checker 角色：未单独配置时回落到主 LLM。"""
        return LLMConfig(
            base_url=self.checker_llm_base_url or self.llm_base_url,
            api_key=self.checker_llm_api_key or self.llm_api_key,
            model=self.checker_llm_model or self.llm_model,
        )


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _load_mcp_filesystem_dirs() -> Tuple[str, ...]:
    raw = os.getenv("ORION_MCP_FILESYSTEM_DIRS", "")
    if not raw:
        return ()
    return tuple(d.strip() for d in raw.split(",") if d.strip())


_cached: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """获取全局配置（惰性加载、可重载）。

    所有 os.getenv 在此处求值，确保 reload=True 时能读到最新的环境变量。
    """
    global _cached
    if _cached is None or reload:
        _cached = Config(
            llm_base_url=_env("ORION_LLM_BASE_URL", "http://localhost:1234/v1"),
            llm_api_key=_env("ORION_LLM_API_KEY", "local-1234567890abcdef"),
            llm_model=_env("ORION_LLM_MODEL", "local-model"),
            checker_llm_base_url=_env("ORION_CHECKER_LLM_BASE_URL", ""),
            checker_llm_api_key=_env("ORION_CHECKER_LLM_API_KEY", ""),
            checker_llm_model=_env("ORION_CHECKER_LLM_MODEL", ""),
            runtime_state_dir=Path(_env("ORION_RUNTIME_STATE_DIR", "./runtime_state")),
            mcp_filesystem_dirs=_load_mcp_filesystem_dirs(),
        )
    return _cached
