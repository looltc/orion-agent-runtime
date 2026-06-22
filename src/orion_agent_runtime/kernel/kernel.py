"""Kernel —— Runtime 生命周期与组件装配中心。

设计文档第 4 节 kernel：
  生命周期管理、任务启动/停止、事件总线初始化、权限与资源隔离。

职责：
- 装配并持有核心子系统：EventBus / WorldManager / Scheduler / MemoryManager / CapabilityRegistry
- 提供 spawn/kill/publish/subscribe/query_state 统一接口
- 协调子系统启动顺序（bus 先就绪，再 subscribe world，再启动 capabilities）

不负责具体执行逻辑——执行由 AgentRuntime（runtime/agent_runtime.py）承担。
Kernel 是"运行时容器"，AgentRuntime 是"运行时执行器"。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from orion_agent_runtime.bus import EventBus, Event, get_event_bus, reset_event_bus
from orion_agent_runtime.capabilities import Capability, CapabilityRegistry
from orion_agent_runtime.memory import MemoryManager
from orion_agent_runtime.scheduler import Scheduler, Task, TaskStatus
from orion_agent_runtime.world import WorldManager


class Kernel:
    """运行时容器：装配并管理核心子系统生命周期。

    典型用法：
        kernel = Kernel()
        await kernel.start()       # 初始化所有子系统 + 订阅
        runtime = AgentRuntime(kernel)
        await runtime.run(goal)
        await kernel.shutdown()
    """

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        world: Optional[WorldManager] = None,
        scheduler: Optional[Scheduler] = None,
        memory: Optional[MemoryManager] = None,
        capabilities: Optional[CapabilityRegistry] = None,
    ) -> None:
        # 注入优先，否则用进程单例/默认实例（便于测试替换）
        self.bus = bus if bus is not None else get_event_bus()
        self.world = world if world is not None else WorldManager(self.bus)
        self.scheduler = scheduler if scheduler is not None else Scheduler()
        self.memory = memory if memory is not None else MemoryManager()
        self.capabilities = capabilities if capabilities is not None else CapabilityRegistry()
        self._started: bool = False

    @property
    def started(self) -> bool:
        return self._started

    # ---- 生命周期 ----
    async def start(self) -> None:
        """启动所有子系统（事件订阅 + 能力初始化）。

        启动顺序：bus 就绪 → world 订阅 → 自动注册浏览器能力（若尚未注册）。
        """
        if self._started:
            return
        self.world.start()  # WorldManager 订阅事件总线
        # 自动注册浏览器能力（若尚未注册）
        if not self.capabilities.has("browser"):
            from orion_agent_runtime.capabilities.browser.capability import (
                create_browser_capability,
            )
            browser_cap = create_browser_capability(bus=self.bus)
            self.capabilities.register(browser_cap)
        self._started = True

    async def shutdown(self) -> None:
        """优雅关闭：释放能力资源、清空订阅。"""
        if not self._started:
            return
        try:
            await self.capabilities.close_all()
        except Exception:
            pass
        try:
            self.world.stop()
        except Exception:
            pass
        self._started = False

    # ---- 设计文档第 4 节 kernel 接口 ----
    def spawn(self, task: Task) -> Task:
        """启动一个任务（加入调度器，初始 READY）。"""
        if task.id not in {t.id for t in self.scheduler.list_all()}:
            # 若 task 已构造但未入队，按字段重建入队
            self.scheduler.create_task(
                goal=task.goal,
                priority=task.priority,
                task_id=task.id,
                success_criteria=task.success_criteria,
                run_id=task.run_id,
            )
        return self.scheduler.get(task.id)

    def kill(self, task_id: str) -> Task:
        """终止任务（强制取消）。"""
        return self.scheduler.cancel(task_id)

    async def publish(self, event: Event) -> str:
        """发布事件到总线。"""
        return await self.bus.emit(event)

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> None:
        """订阅事件。"""
        self.bus.on(event_type, handler)

    def query_state(self, task_id: str) -> Optional[Task]:
        """查询任务状态。"""
        try:
            return self.scheduler.get(task_id)
        except KeyError:
            return None

    # ---- 能力管理 ----
    def register_capability(self, capability: Capability) -> None:
        """注册一个能力到 registry。"""
        self.capabilities.register(capability)

    def get_capability(self, name: str) -> Capability:
        return self.capabilities.get(name)


# ---- 进程级单例（与其它子系统保持一致）----
_default_kernel: Optional[Kernel] = None


def get_kernel() -> Kernel:
    global _default_kernel
    if _default_kernel is None:
        _default_kernel = Kernel()
    return _default_kernel


def reset_kernel() -> None:
    """重置全局 Kernel（测试用）。"""
    global _default_kernel
    _default_kernel = None
    reset_event_bus()
