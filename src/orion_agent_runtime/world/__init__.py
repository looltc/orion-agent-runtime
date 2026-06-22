"""世界模型子系统（V2 架构）。

维护当前任务、窗口、URL、标签页、文件、通知、最近观察等世界状态。
设计文档第 4 节 world 模块：内存状态管理模块，通常随 kernel 运行。

接口（设计文档第 4 节）：
- apply(event)
- snapshot()
- restore(snapshot)
- diff(previous_snapshot)
"""

from orion_agent_runtime.world.state import WorldState
from orion_agent_runtime.world.world_manager import WorldManager

__all__ = ["WorldState", "WorldManager"]
