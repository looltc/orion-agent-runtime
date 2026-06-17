from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# MemoryItem 模型表示一个记忆项。
# MemoryHit 模型表示一个记忆命中结果。


class MemoryItem(BaseModel):
    id: Optional[int] = None
    user_id: str
    kind: Literal["preference", "fact", "task_summary", "tool_result"]
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class MemoryHit(BaseModel):
    item: MemoryItem
    score: float
    reason: str = ""
