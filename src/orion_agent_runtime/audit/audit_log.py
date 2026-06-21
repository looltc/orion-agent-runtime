"""审计日志（P5）。

结构化记录循环中的关键事件：工具调用、验证决策、人工介入。
落盘到 runtime_state/audit.jsonl（每行一个 JSON 事件），便于事后复盘与合规审计。

Loop Engineering 原则："保持完整的执行审计日志"。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orion_agent_runtime.config import get_config


def _audit_path() -> Path:
    return Path(get_config().runtime_state_dir) / "audit.jsonl"


def log_event(
    run_id: str,
    event_type: str,
    data: Optional[dict] = None,
) -> None:
    """追加一条审计事件。

    参数:
        run_id: 所属运行 id
        event_type: 事件类型（如 "tool_call_start"、"goal_verification_completed"）
        data: 事件数据
    """
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event_type": event_type,
        "data": data or {},
    }
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def read_events(run_id: Optional[str] = None) -> list:
    """读取审计事件；指定 run_id 则只返回该 run 的事件。"""
    path = _audit_path()
    if not path.exists():
        return []
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is None or ev.get("run_id") == run_id:
                events.append(ev)
    return events


def clear_audit() -> None:
    """测试用：清空审计日志。"""
    path = _audit_path()
    if path.exists():
        path.unlink()