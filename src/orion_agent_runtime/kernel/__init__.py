"""Kernel 子系统（V2 架构）。

设计文档第 4 节 kernel 模块：
  生命周期管理、任务启动/停止、事件总线初始化、权限与资源隔离。

接口（设计文档第 4 节）：
  spawn(task) / kill(task_id) / publish(event) / subscribe(event_type) / query_state(task_id)

进程边界：单例进程或主服务。装配 EventBus/World/Scheduler/Memory/Capability。
"""

from orion_agent_runtime.kernel.kernel import Kernel

__all__ = ["Kernel"]
