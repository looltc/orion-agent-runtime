"""WorldState 数据模型。

设计文档第 3 节：世界状态单独维护——当前 URL、活动窗口、任务状态、最近动作等
统一由 World Model 管理。

WorldState 是"外部世界的内存投影"，由 WorldManager 订阅事件后 apply 更新。
它是可快照、可恢复、可 diff 的不可变视图（model_dump 确保可序列化）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field


class WorldState(BaseModel):
    """世界状态快照。

    字段覆盖设计文档第 3/4 节要求的状态项：
    - current_url / current_title：浏览器当前页（Browser Capability）
    - tabs：浏览器标签页列表
    - active_window：桌面活动窗口（Desktop Capability）
    - windows：桌面窗口列表
    - task_context：当前任务上下文（goal、success_criteria、iterations）
    - recent_actions：最近 N 个动作（用于规划上下文）
    - recent_observations：最近 N 个观察结果
    - variables：任务运行期变量（工具产出的中间结果）
    """

    # ---- 浏览器状态 ----
    current_url: Optional[str] = None
    current_title: Optional[str] = None
    tabs: List[str] = Field(default_factory=list)  # url 列表

    # ---- 桌面状态 ----
    active_window: Optional[str] = None
    windows: List[str] = Field(default_factory=list)

    # ---- 任务上下文 ----
    task_context: Dict[str, Any] = Field(default_factory=dict)
    # 形如 {"goal": ..., "success_criteria": [...], "iterations": N, "status": ...}

    # ---- 最近动作与观察（滑动窗口，规划上下文）----
    recent_actions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_observations: List[Dict[str, Any]] = Field(default_factory=list)

    # ---- 运行期变量（工具产出可写入这里供后续步骤引用）----
    variables: Dict[str, Any] = Field(default_factory=dict)

    # ---- 元信息 ----
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 快照容量上限（超出 FIFO 淘汰，避免无限增长）
    RECENT_LIMIT: ClassVar[int] = 20

    def model_post_init(self, __context: Any) -> None:
        """初始化后裁剪滑动窗口到上限。"""
        if len(self.recent_actions) > self.RECENT_LIMIT:
            object.__setattr__(self, "recent_actions", self.recent_actions[-self.RECENT_LIMIT:])
        if len(self.recent_observations) > self.RECENT_LIMIT:
            object.__setattr__(
                self, "recent_observations", self.recent_observations[-self.RECENT_LIMIT:]
            )

    def snapshot(self) -> Dict[str, Any]:
        """导出可序列化快照（用于持久化/恢复）。"""
        return self.model_dump()

    def diff(self, previous: "WorldState") -> Dict[str, Any]:
        """与前一快照对比，返回发生变化的字段（值不同的字段）。

        用于审计与"世界状态变化"事件 payload。
        """
        prev = previous.model_dump()
        curr = self.model_dump()
        changed: Dict[str, Any] = {}
        for k, v in curr.items():
            if k == "updated_at":
                continue  # 时间戳总在变，不算业务变更
            if prev.get(k) != v:
                changed[k] = {"from": prev.get(k), "to": v}
        return changed

    # ---- 增量更新方法（供 WorldManager 调用，返回新实例，保持不可变语义）----
    def with_browser(self, *, url: Optional[str] = None, title: Optional[str] = None) -> "WorldState":
        data = self.model_dump()
        if url is not None:
            data["current_url"] = url
            if url and url not in data["tabs"]:
                data["tabs"] = data["tabs"] + [url]
        if title is not None:
            data["current_title"] = title
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)

    def with_desktop(self, *, active_window: Optional[str] = None) -> "WorldState":
        data = self.model_dump()
        if active_window is not None:
            data["active_window"] = active_window
            if active_window and active_window not in data["windows"]:
                data["windows"] = data["windows"] + [active_window]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)

    def with_task_context(self, ctx: Dict[str, Any]) -> "WorldState":
        data = self.model_dump()
        data["task_context"] = {**data["task_context"], **ctx}
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)

    def with_action(self, action: Dict[str, Any]) -> "WorldState":
        data = self.model_dump()
        actions = data["recent_actions"] + [action]
        data["recent_actions"] = actions[-self.RECENT_LIMIT :]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)

    def with_observation(self, obs: Dict[str, Any]) -> "WorldState":
        data = self.model_dump()
        obs_list = data["recent_observations"] + [obs]
        data["recent_observations"] = obs_list[-self.RECENT_LIMIT :]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)

    def with_variable(self, key: str, value: Any) -> "WorldState":
        data = self.model_dump()
        data["variables"][key] = value
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return WorldState.model_validate(data)
