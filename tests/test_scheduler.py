"""P1: Scheduler + Task 状态机测试。

核心断言（设计文档第 8 节验收点）：
- 支持 READY/RUNNING/BLOCKED/WAITING/DONE/PAUSED 状态
- 状态机迁移校验（非法迁移抛错）
- 优先级队列（高优先级先出）
- 暂停/恢复（支持 snapshot_data 持久化）
- next_runnable 按优先级返回
- 任务失败后可恢复

设计文档 P1 输出物：scheduler/*，验收"支持 READY/RUNNING/BLOCKED/WAITING/DONE"。
"""

import uuid

import pytest

from orion_agent_runtime.scheduler import Scheduler, Task, TaskStatus


def _uid() -> str:
    return str(uuid.uuid4())[:8]


# ---------- Task 状态模型 ----------

def test_task_default_status_ready():
    t = Task(id=_uid(), goal="test")
    assert t.status == TaskStatus.READY


def test_task_valid_transitions():
    t = Task(id=_uid(), goal="test")
    assert t.can_transition(TaskStatus.RUNNING)
    assert not t.can_transition(TaskStatus.DONE)  # READY 不能直接 DONE


def test_task_transition_returns_new_instance():
    t = Task(id=_uid(), goal="test")
    t2 = t.transition(TaskStatus.RUNNING)
    assert t2.status == TaskStatus.RUNNING
    assert t.status == TaskStatus.READY  # 原实例不变


def test_task_invalid_transition_raises():
    t = Task(id=_uid(), goal="test")
    with pytest.raises(ValueError, match="invalid transition"):
        t.transition(TaskStatus.DONE)


def test_task_terminal_cannot_transition():
    t = Task(id=_uid(), goal="test", status=TaskStatus.DONE)
    with pytest.raises(ValueError, match="terminal status"):
        t.transition(TaskStatus.RUNNING)


# ---------- Scheduler 创建 ----------

def test_scheduler_create_task():
    s = Scheduler()
    t = s.create_task(goal="search info", priority=5, task_id="t1")
    assert t.status == TaskStatus.READY
    assert t.goal == "search info"
    assert t.priority == 5


def test_scheduler_create_duplicate_raises():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    with pytest.raises(ValueError, match="already exists"):
        s.create_task(goal="y", task_id="t1")


# ---------- 状态迁移 ----------

def test_scheduler_start_task():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    t = s.start("t1")
    assert t.status == TaskStatus.RUNNING


def test_scheduler_complete_task():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    t = s.complete("t1", result="done!")
    assert t.status == TaskStatus.DONE
    assert t.result == "done!"


def test_scheduler_fail_task():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    t = s.fail("t1", error="tool not found")
    assert t.status == TaskStatus.FAILED
    assert t.error == "tool not found"


def test_scheduler_pause_and_resume():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    t = s.pause("t1", snapshot_data={"url": "https://midway.com"})
    assert t.status == TaskStatus.PAUSED
    assert t.snapshot_data["url"] == "https://midway.com"

    # 恢复
    t2 = s.resume("t1")
    assert t2.status == TaskStatus.RUNNING


def test_scheduler_block_and_unblock():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    t = s.block("t1")
    assert t.status == TaskStatus.BLOCKED
    t2 = s.unblock("t1")
    assert t2.status == TaskStatus.RUNNING


def test_scheduler_cancel():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    t = s.cancel("t1")
    assert t.status == TaskStatus.CANCELLED


def test_scheduler_cancel_terminal_raises():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.start("t1")
    s.complete("t1")
    with pytest.raises(ValueError, match="terminal status"):
        s.cancel("t1")


# ---------- next_runnable 优先级队列 ----------

def test_next_runnable_priority_order():
    s = Scheduler()
    s.create_task(goal="low", priority=1, task_id="t_low")
    s.create_task(goal="high", priority=10, task_id="t_high")
    s.create_task(goal="mid", priority=5, task_id="t_mid")

    assert s.next_runnable().id == "t_high"
    s.start("t_high")
    assert s.next_runnable().id == "t_mid"
    s.start("t_mid")
    assert s.next_runnable().id == "t_low"


def test_next_runnable_skips_non_ready():
    """RUNNING/DONE/PAUSED 等不参与 next_runnable。"""
    s = Scheduler()
    s.create_task(goal="running", priority=10, task_id="t1")
    s.create_task(goal="ready", priority=5, task_id="t2")
    s.start("t1")
    assert s.next_runnable().id == "t2"


def test_next_runnable_none_when_empty():
    s = Scheduler()
    assert s.next_runnable() is None


def test_next_runnable_none_when_all_busy():
    s = Scheduler()
    s.create_task(goal="a", task_id="t1")
    s.create_task(goal="b", task_id="t2")
    s.start("t1")
    s.start("t2")
    assert s.next_runnable() is None


# ---------- 查询 ----------

def test_scheduler_list_by_status():
    s = Scheduler()
    s.create_task(goal="a", task_id="t1")
    s.create_task(goal="b", task_id="t2")
    s.start("t1")
    ready = s.list_by_status(TaskStatus.READY)
    running = s.list_by_status(TaskStatus.RUNNING)
    assert len(ready) == 1 and ready[0].id == "t2"
    assert len(running) == 1 and running[0].id == "t1"


def test_scheduler_running_count():
    s = Scheduler()
    s.create_task(goal="a", task_id="t1")
    s.create_task(goal="b", task_id="t2")
    s.start("t1")
    assert s.running_count() == 1
    s.start("t2")
    assert s.running_count() == 2


def test_scheduler_task_not_found_raises():
    s = Scheduler()
    with pytest.raises(KeyError, match="not found"):
        s.get("nonexistent")


# ---------- 暂停恢复持久化场景 ----------

def test_pause_preserves_snapshot_for_recovery():
    """设计文档验收点：任务失败后可恢复并从最近状态继续。"""
    s = Scheduler()
    s.create_task(goal="browse and search", task_id="t1", success_criteria=["found answer"])
    s.start("t1")

    # 模拟执行中途暂停（保存世界状态快照）
    snapshot = {"url": "https://results.com", "step": 3, "history": ["step1", "step2"]}
    paused = s.pause("t1", snapshot_data=snapshot)
    assert paused.snapshot_data["url"] == "https://results.com"

    # 恢复后 snapshot_data 仍可读取
    resumed = s.resume("t1")
    assert resumed.snapshot_data["url"] == "https://results.com"
    assert resumed.status == TaskStatus.RUNNING


def test_remove_task():
    s = Scheduler()
    s.create_task(goal="x", task_id="t1")
    s.remove("t1")
    assert s.next_runnable() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
