from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone

# MemoryItem 模型表示一个记忆项。
# MemoryHit 模型表示一个记忆命中结果。
#
# V2 改造（设计文档第 4 节 memory 模块）：
#   引入 layer 字段表示三层记忆归属，与现有 kind 正交：
#   - working：会话级即时上下文（短期，进程内）
#   - episodic：事件经历（按 run/时间组织，持久化）
#   - semantic：事实/偏好知识（去语境化，持久化）
#   旧调用方不传 layer 时默认 "episodic"（向后兼容现有 task_summary/fact 写入）。


# 三层记忆层名（Literal 复用，便于类型检查）
MemoryLayer = Literal["working", "episodic", "semantic"]


class MemoryItem(BaseModel):
    id: Optional[int] = None
    user_id: str
    kind: Literal["preference", "fact", "task_summary", "tool_result"]
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # V2：记忆层归属（默认 episodic 保持向后兼容）
    layer: MemoryLayer = "episodic"


class MemoryHit(BaseModel):
    item: MemoryItem
    score: float
    reason: str = ""
