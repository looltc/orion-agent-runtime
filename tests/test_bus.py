"""P0: 事件总线测试。

核心断言（设计文档第 8 节验收点）：
- EventBus 可 emit / subscribe / replay
- handler 异常被隔离，不阻塞总线
- "*" 通配订阅
- 持久化按 run_id 分文件，支持回放

设计文档 P0 输出物：bus/event.py、bus/event_bus.py，验收"可 emit / subscribe / replay"。
"""

import asyncio
from pathlib import Path

import pytest

from orion_agent_runtime.bus import (
    Event,
    EventBus,
    EventType,
    make_event,
    reset_event_bus,
)


# ---------- Event 数据模型 ----------

def test_event_auto_fills_id_and_timestamp():
    e = make_event(type=EventType.TASK_CREATED, source="test", payload={"k": "v"})
    assert e.id  # uuid 自动填充
    assert e.source == "test"
    assert e.type == EventType.TASK_CREATED
    assert e.payload == {"k": "v"}
    assert e.target is None
    assert e.task_id is None and e.run_id is None


def test_event_json_roundtrip():
    e = make_event(
        type=EventType.ACTION_COMPLETED,
        source="executor",
        payload={"tool": "add", "result": 3},
        run_id="r1",
        task_id="t1",
    )
    raw = e.model_dump_json()
    restored = Event.model_validate_json(raw)
    assert restored.type == EventType.ACTION_COMPLETED
    assert restored.run_id == "r1"
    assert restored.payload["result"] == 3


# ---------- EventBus emit / subscribe ----------

def test_emit_dispatches_to_matching_handler(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    received = []

    async def handler(ev: Event):
        received.append(ev)

    bus.on(EventType.TASK_CREATED, handler)
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="r1")))
    assert len(received) == 1
    assert received[0].type == EventType.TASK_CREATED


def test_emit_does_not_dispatch_to_unrelated_handler(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    received = []

    async def handler(ev: Event):
        received.append(ev)

    bus.on(EventType.TASK_CREATED, handler)
    asyncio.run(
        bus.emit(make_event(EventType.ACTION_COMPLETED, source="k", run_id="r1"))
    )
    assert received == []


def test_wildcard_handler_receives_all_events(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    all_events = []

    async def wildcard(ev: Event):
        all_events.append(ev.type)

    bus.on("*", wildcard)
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="r1")))
    asyncio.run(
        bus.emit(make_event(EventType.ACTION_COMPLETED, source="k", run_id="r1"))
    )
    assert EventType.TASK_CREATED in all_events
    assert EventType.ACTION_COMPLETED in all_events


def test_emit_persists_event_and_returns_id(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    e = make_event(EventType.TASK_CREATED, source="k", run_id="r1")
    returned_id = asyncio.run(bus.emit(e))
    assert returned_id == e.id
    # 持久化文件应存在
    assert (tmp_path / "r1.jsonl").exists()


# ---------- handler 异常隔离 ----------

def test_handler_exception_does_not_block_bus(tmp_path):
    """关键约束：单个 handler 崩溃不能阻塞总线或其他 handler。"""
    bus = EventBus(event_store_dir=tmp_path)
    healthy_received = []

    async def bad_handler(ev: Event):
        raise RuntimeError("boom")

    async def good_handler(ev: Event):
        healthy_received.append(ev)

    bus.on(EventType.TASK_CREATED, bad_handler)
    bus.on(EventType.TASK_CREATED, good_handler)

    # 不应抛异常
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="r1")))
    # good handler 仍被调用
    assert len(healthy_received) == 1


# ---------- replay ----------

def test_replay_returns_events_in_order(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)

    # 同一 run 发多个事件
    for i in range(3):
        asyncio.run(
            bus.emit(
                make_event(
                    EventType.TASK_UPDATED,
                    source="k",
                    payload={"i": i},
                    run_id="r2",
                )
            )
        )
    events = asyncio.run(bus.replay("r2"))
    assert len(events) == 3
    # payload 顺序应保留
    assert [e.payload["i"] for e in events] == [0, 1, 2]


def test_replay_empty_when_no_run(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    events = asyncio.run(bus.replay("nonexistent"))
    assert events == []


def test_replay_isolates_runs(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="a")))
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="b")))
    assert len(asyncio.run(bus.replay("a"))) == 1
    assert len(asyncio.run(bus.replay("b"))) == 1


# ---------- 同步非协程 handler 拒绝 ----------

def test_sync_handler_rejected():
    bus = EventBus()

    def not_async(ev: Event):
        pass

    with pytest.raises(TypeError):
        bus.on(EventType.TASK_CREATED, not_async)


# ---------- off / clear ----------

def test_off_removes_handler(tmp_path):
    bus = EventBus(event_store_dir=tmp_path)
    received = []

    async def handler(ev: Event):
        received.append(ev)

    bus.on(EventType.TASK_CREATED, handler)
    bus.off(EventType.TASK_CREATED, handler)
    asyncio.run(bus.emit(make_event(EventType.TASK_CREATED, source="k", run_id="r1")))
    assert received == []


def test_clear_resets_all_subscriptions():
    bus = EventBus()
    bus.on("*", _noop)
    bus.on(EventType.TASK_CREATED, _noop)
    bus.clear()
    assert bus._handlers == {}
    assert bus._wildcard_handlers == []


async def _noop(ev: Event):
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
