import json
from pathlib import Path
from typing import Optional
from orion_agent_runtime.core.models import AgentState

# 简单的基于文件的状态存储，持久化 AgentState。

STATE_DIR = Path("./runtime_state")
STATE_DIR.mkdir(exist_ok=True)


def get_state_path(run_id: str) -> Path:
    return STATE_DIR / f"{run_id}.json"


def save_state(state: AgentState, run_id: str) -> None:
    path = get_state_path(run_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=2, exclude_none=False))


def load_state(run_id: str) -> Optional[AgentState]:
    path = get_state_path(run_id)
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return AgentState.model_validate(data)
