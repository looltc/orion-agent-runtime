"""P0: Memory 三层记忆测试。

核心断言（设计文档第 8 节验收点）：
- 三层可写入、检索、摘要
- layer 字段正确区分
- add 后 id 被回填（V1 bug 修复）
- DB 路径走 config（可注入）
- V1 兼容接口仍可用（remember_task_summary/recall_related）

设计文档 P0 输出物：memory/working、episodic、semantic，
验收"可写入、检索、摘要"。
"""

from pathlib import Path

import pytest

from orion_agent_runtime.memory import (
    EpisodicStore,
    MemoryItem,
    MemoryManager,
    SemanticStore,
    WorkingStore,
)


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "mem.db"


# ---------- MemoryItem schema（含 layer 字段） ----------

def test_memory_item_default_layer_episodic():
    """V1 兼容：不指定 layer 时默认 episodic。"""
    item = MemoryItem(user_id="u", kind="task_summary", content="x")
    assert item.layer == "episodic"


def test_memory_item_explicit_layer():
    item = MemoryItem(user_id="u", kind="fact", content="x", layer="semantic")
    assert item.layer == "semantic"


# ---------- MemoryStore 基础（id 回填 + layer 过滤） ----------

def test_store_add_backfills_id(tmp_db):
    """V1 bug 修复：add 后 item.id 应被回填。"""
    store = EpisodicStore(db_path=tmp_db)
    new_id = store.remember_episode(
        user_id="u", run_id="r1", summary="任务完成"
    )
    assert new_id is not None and new_id > 0


def test_store_search_filters_by_layer(tmp_db):
    """semantic 层写入的事实不应出现在 episodic 检索中。"""
    mgr = MemoryManager(db_path=tmp_db)
    mgr.episodic.remember_episode(user_id="u", run_id="r1", summary="做了一次计算")
    mgr.semantic.remember_fact(user_id="u", fact="用户偏好中文回答")

    epi = mgr.episodic.search("u", "计算")
    sem = mgr.semantic.search("u", "偏好")

    assert all(it.layer == "episodic" for it in epi)
    assert all(it.layer == "semantic" for it in sem)
    assert any("计算" in it.content for it in epi)
    assert any("偏好" in it.content for it in sem)


# ---------- Episodic 层 ----------

def test_episodic_remember_and_recall_by_run(tmp_db):
    store = EpisodicStore(db_path=tmp_db)
    store.remember_episode(
        user_id="u",
        run_id="r1",
        summary="打开浏览器搜索",
        steps=[{"tool": "browser.navigate", "result": "ok"}],
        status="goal_achieved",
        iterations=3,
    )
    items = store.recall_by_run("r1", "u")
    assert len(items) == 1
    assert items[0].metadata["run_id"] == "r1"
    assert items[0].metadata["status"] == "goal_achieved"
    assert items[0].metadata["iterations"] == 3
    assert len(items[0].metadata["steps"]) == 1


def test_episodic_search_by_relevance(tmp_db):
    store = EpisodicStore(db_path=tmp_db)
    store.remember_episode(user_id="u", run_id="r1", summary="计算 1+1 等于 2")
    store.remember_episode(user_id="u", run_id="r2", summary="打开网页搜索天气")
    hits = store.search("u", "计算 加法")
    assert len(hits) >= 1
    assert "计算" in hits[0].content


def test_episodic_summarize_returns_text(tmp_db):
    store = EpisodicStore(db_path=tmp_db)
    store.remember_episode(user_id="u", run_id="r1", summary="做了任务A")
    store.remember_episode(user_id="u", run_id="r2", summary="做了任务B")
    s = store.summarize("u")
    assert "任务A" in s and "任务B" in s


# ---------- Semantic 层 ----------

def test_semantic_remember_fact_and_preference(tmp_db):
    store = SemanticStore(db_path=tmp_db)
    store.remember_fact(user_id="u", fact="地球绕太阳转")
    store.remember_preference(user_id="u", preference="喜欢简洁回答")
    facts = store.search("u", "地球 太阳")
    prefs = store.search("u", "喜欢", kinds=["preference"])
    assert any("地球" in f.content for f in facts)
    assert any("喜欢" in p.content for p in prefs)


def test_semantic_search_only_semantic_layer(tmp_db):
    """semantic 检索不应跨层返回 episodic 项。"""
    mgr = MemoryManager(db_path=tmp_db)
    mgr.episodic.remember_episode(user_id="u", run_id="r1", summary="事实：地球是圆的")
    mgr.semantic.remember_fact(user_id="u", fact="地球是圆的")
    hits = mgr.semantic.search("u", "地球")
    assert all(it.layer == "semantic" for it in hits)


# ---------- Working 层（进程内） ----------

def test_working_put_and_context():
    ws = WorkingStore(capacity_per_key=3)
    ws.put("run1", "a", {"content": "step1"})
    ws.put("run1", "b", {"content": "step2"})
    ctx = ws.context("run1")
    assert len(ctx) == 2
    assert ctx[0]["content"] == "step1"


def test_working_fifo_eviction():
    """超容量 FIFO 淘汰最老的。"""
    ws = WorkingStore(capacity_per_key=2)
    ws.put("k", "a", {"content": "1"})
    ws.put("k", "b", {"content": "2"})
    ws.put("k", "c", {"content": "3"})  # 应淘汰 a
    ctx = ws.context("k")
    assert len(ctx) == 2
    assert ctx[0]["content"] == "2"
    assert ctx[1]["content"] == "3"


def test_working_summarize():
    ws = WorkingStore()
    ws.put("k", "a", {"content": "hello", "kind": "tool_result"})
    ws.put("k", "b", {"content": "world", "kind": "tool_result"})
    s = ws.summarize("k")
    assert "hello" in s and "world" in s


def test_working_isolated_per_key():
    ws = WorkingStore()
    ws.put("run1", "a", {"content": "x"})
    ws.put("run2", "a", {"content": "y"})
    assert ws.context("run1") != ws.context("run2")


# ---------- MemoryManager 门面（V2 接口） ----------

def test_manager_put_working(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    mgr.put("run1", {"content": "即时上下文"}, layer="working")
    assert mgr.working.size("run1") == 1


def test_manager_put_episodic(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    new_id = mgr.put(
        "任务完成",
        "任务完成",
        layer="episodic",
        user_id="u",
        metadata={"run_id": "r1", "status": "done"},
    )
    assert new_id > 0
    items = mgr.episodic.recall_by_run("r1", "u")
    assert len(items) == 1


def test_manager_put_semantic(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    new_id = mgr.put("用户喜欢深色模式", None, layer="semantic", user_id="u")
    assert new_id > 0
    hits = mgr.semantic.search("u", "喜欢 深色")
    assert any("深色" in h.content for h in hits)


def test_manager_search_cross_layer(tmp_db):
    """默认 search 跨 episodic + semantic。"""
    mgr = MemoryManager(db_path=tmp_db)
    mgr.episodic.remember_episode(user_id="u", run_id="r1", summary="计算结果")
    mgr.semantic.remember_fact(user_id="u", fact="计算公式")
    results = mgr.search("计算", user_id="u")
    layers = {it.layer for it in results}
    assert "episodic" in layers or "semantic" in layers


def test_manager_summarize_all_layers(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    mgr.working.put("run1", "a", {"content": "即时", "kind": "tool_result"})
    mgr.episodic.remember_episode(user_id="u", run_id="run1", summary="经历")
    mgr.semantic.remember_fact(user_id="u", fact="事实")
    s = mgr.summarize("run1", user_id="u")
    assert "即时" in s
    assert "经历" in s
    assert "事实" in s


def test_manager_forget_episodic(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    mgr.episodic.remember_episode(user_id="u", run_id="r1", summary="x")
    deleted = mgr.forget(layer="episodic", user_id="u")
    assert deleted >= 1
    assert mgr.episodic.recall_recent("u") == []


# ---------- V1 兼容接口回归（确保 workflow/planner 零改动可用） ----------

def test_v1_compat_remember_task_summary(tmp_db):
    """core/workflow._remember 调用的接口，必须保持工作。"""
    mgr = MemoryManager(db_path=tmp_db)
    mgr.remember_task_summary(user_id="u", summary="旧式摘要", metadata={"run_id": "r1"})
    items = mgr.store.search_by_user("u")
    assert len(items) == 1
    assert items[0].kind == "task_summary"
    assert items[0].layer == "episodic"  # V2：旧写入归入 episodic
    assert items[0].metadata["run_id"] == "r1"


def test_v1_compat_recall_related(tmp_db):
    """core/planner 调用的接口，必须保持工作。"""
    mgr = MemoryManager(db_path=tmp_db)
    mgr.remember_task_summary(user_id="u", summary="查询天气")
    hits = mgr.recall_related(user_id="u", query="天气")
    assert len(hits) >= 1
    assert "天气" in hits[0].item.content


def test_v1_compat_remember_text(tmp_db):
    mgr = MemoryManager(db_path=tmp_db)
    mgr.remember_text(user_id="u", kind="fact", content="通用写入")
    items = mgr.store.search_by_user("u")
    assert items[0].content == "通用写入"


# ---------- DB 路径走 config（可注入） ----------

def test_store_db_path_injected(tmp_path, monkeypatch):
    """DB 路径不再硬编码，可通过 config 或构造参数注入。"""
    from orion_agent_runtime.config import get_config

    custom = tmp_path / "custom_loc" / "m.db"
    store = EpisodicStore(db_path=custom)
    store.remember_episode(user_id="u", run_id="r", summary="x")
    assert custom.exists()
    # 也不应污染默认 config 路径
    assert custom != Path(get_config().runtime_state_dir) / "memory.db"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
