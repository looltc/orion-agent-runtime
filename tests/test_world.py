"""P0: 世界模型测试。

核心断言（设计文档第 8 节验收点）：
- World Model 能在任务执行前后保持一致更新
- 动作（事件）能驱动 world 更新
- snapshot / restore / diff 正确

设计文档 P0 输出物：world/state.py、world/world_manager.py，
验收"可由任一动作驱动 world 更新"。
"""

import asyncio

from orion_agent_runtime.bus import EventBus, Event, EventType, make_event
from orion_agent_runtime.world import WorldManager, WorldState


# ---------- WorldState 基础 ----------

def test_world_state_default_empty():
    s = WorldState()
    assert s.current_url is None
    assert s.active_window is None
    assert s.tabs == []
    assert s.recent_actions == []
    assert s.recent_observations == []
    assert s.variables == {}


def test_world_state_snapshot_roundtrip():
    s = WorldState().with_browser(url="https://example.com", title="Example")
    snap = s.snapshot()
    restored = WorldState.model_validate(snap)
    assert restored.current_url == "https://example.com"
    assert restored.current_title == "Example"


def test_world_state_with_browser_tracks_tabs():
    s = WorldState().with_browser(url="https://a.com")
    s = s.with_browser(url="https://b.com")
    assert s.current_url == "https://b.com"
    assert s.tabs == ["https://a.com", "https://b.com"]


def test_world_state_with_action_appends():
    s = WorldState()
    s = s.with_action({"type": "click", "selector": "#btn"})
    s = s.with_action({"type": "type", "text": "hello"})
    assert len(s.recent_actions) == 2
    assert s.recent_actions[0]["type"] == "click"


def test_world_state_recent_actions_fifo_limit():
    s = WorldState()
    for i in range(30):
        s = s.with_action({"i": i})
    assert len(s.recent_actions) == WorldState.RECENT_LIMIT
    # 保留最后 N 个
    assert s.recent_actions[-1]["i"] == 29


def test_world_state_diff_detects_changes():
    a = WorldState()
    b = a.with_browser(url="https://x.com")
    changed = b.diff(a)
    assert "current_url" in changed
    assert changed["current_url"]["from"] is None
    assert changed["current_url"]["to"] == "https://x.com"


def test_world_state_diff_empty_when_unchanged():
    a = WorldState()
    b = WorldState()
    # 比较时 updated_at 被忽略
    changed = b.diff(a)
    assert changed == {}


def test_world_state_with_variable():
    s = WorldState().with_variable("result", 42)
    assert s.variables["result"] == 42


# ---------- WorldManager 事件驱动更新 ----------

def test_world_manager_browser_navigate_updates_state(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.BROWSER_NAVIGATE,
                source="browser",
                payload={"url": "https://example.com", "title": "Example"},
                run_id="r1",
            )
        )
    )
    assert world.state().current_url == "https://example.com"
    assert world.state().current_title == "Example"
    assert "https://example.com" in world.state().tabs


def test_world_manager_action_completed_records_observation(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.ACTION_COMPLETED,
                source="executor",
                payload={"tool": "add", "result": 3},
                run_id="r1",
            )
        )
    )
    assert len(world.state().recent_observations) == 1
    assert world.state().recent_observations[0]["tool"] == "add"


def test_world_manager_action_completed_with_variable(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.ACTION_COMPLETED,
                source="executor",
                payload={"tool": "compute", "result": 42, "variable": "answer"},
                run_id="r1",
            )
        )
    )
    assert world.state().variables["answer"] == 42


def test_world_manager_desktop_focus_updates_active_window(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.DESKTOP_FOCUS,
                source="desktop",
                payload={"window": "Notepad"},
                run_id="r1",
            )
        )
    )
    assert world.state().active_window == "Notepad"


def test_world_manager_task_created_updates_context(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.TASK_CREATED,
                source="kernel",
                payload={
                    "goal": "find answer",
                    "success_criteria": ["answer is 42"],
                },
                task_id="t1",
                run_id="r1",
            )
        )
    )
    ctx = world.state().task_context
    assert ctx["goal"] == "find answer"
    assert ctx["success_criteria"] == ["answer is 42"]
    assert ctx["status"] == "running"


def test_world_manager_emits_world_updated(tmp_path):
    """状态变更应自动 emit world.updated，形成事件驱动闭环。"""
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    received = []

    async def listener(ev: Event):
        if ev.type == EventType.WORLD_UPDATED:
            received.append(ev)

    bus.on(EventType.WORLD_UPDATED, listener)

    asyncio.run(
        bus.emit(
            make_event(
                EventType.BROWSER_NAVIGATE,
                source="browser",
                payload={"url": "https://x.com"},
                run_id="r1",
            )
        )
    )
    assert len(received) == 1
    assert "current_url" in received[0].payload["changed"]


def test_world_manager_snapshot_and_restore(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.BROWSER_NAVIGATE,
                source="browser",
                payload={"url": "https://a.com"},
                run_id="r1",
            )
        )
    )
    snap = world.snapshot()
    assert snap["current_url"] == "https://a.com"

    # 清空后恢复
    world._state = WorldState()
    assert world.state().current_url is None
    world.restore(snap)
    assert world.state().current_url == "https://a.com"


def test_world_manager_no_update_for_unrelated_event(tmp_path):
    """与 world 无关的事件不应改变状态。"""
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)
    world.start()
    before = world.snapshot()

    asyncio.run(
        bus.emit(
            make_event(
                EventType.MEMORY_WRITE,
                source="memory",
                payload={"key": "k", "value": "v"},
                run_id="r1",
            )
        )
    )
    after = world.snapshot()
    # 除 updated_at 外应无业务字段变化
    diff = WorldState.model_validate(after).diff(WorldState.model_validate(before))
    assert diff == {}


def test_world_manager_apply_returns_diff(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    world = WorldManager(bus)

    changed = asyncio.run(
        world.apply(
            make_event(
                EventType.BROWSER_NAVIGATE,
                source="browser",
                payload={"url": "https://new.com"},
                run_id="r1",
            )
        )
    )
    assert changed is not None
    assert "current_url" in changed


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
