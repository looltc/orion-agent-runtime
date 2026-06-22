import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from orion_agent_runtime.config import get_config
from orion_agent_runtime.memory.memory_schema import MemoryItem, MemoryHit

# 持久化存储与检索记忆项（episodic/semantic 层共用此存储，按 layer 列区分）。
#
# V2 改造：
# - DB 路径默认走 config.runtime_state_dir（原硬编码 ./runtime_state/memory.db）
# - 新增 layer 列；自动迁移旧表（ALTER TABLE ADD COLUMN）
# - add() 回填 item.id（原 bug：写入后 id 仍为 None）
# - search_related 支持 layer 过滤


def _default_db_path() -> Path:
    """从 config 取 DB 路径（不再硬编码）。"""
    return Path(get_config().runtime_state_dir) / "memory.db"


# 保留旧常量名供外部潜在引用，但指向动态计算（V2 应优先用 config）
DB_PATH = _default_db_path()


def _tokenize(text: str) -> set[str]:
    """
    混合分词：
    - 英文/数字按词切
    - 中文按单字 + 2-gram
    """
    text = (text or "").lower()
    tokens: set[str] = set()

    # 英文/数字词
    tokens.update(re.findall(r"[a-z0-9_]+", text))

    # 中文块
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        if not chunk:
            continue
        for ch in chunk:
            tokens.add(ch)
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i : i + 2])

    return {t for t in tokens if t}


def _parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
        # 统一为带时区的 naive 比较：若 dt 带时区则转为 UTC 后去掉 tzinfo
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _kind_weight(kind: str) -> float:
    return {
        "preference": 3.0,
        "fact": 2.5,
        "task_summary": 2.0,
        "tool_result": 1.0,
    }.get(kind, 1.0)


def _layer_weight(layer: str) -> float:
    """层权重：semantic（稳定知识）> episodic（经历）> working（即时上下文）。"""
    return {
        "semantic": 2.0,
        "episodic": 1.5,
        "working": 0.5,
    }.get(layer, 1.0)


class MemoryStore:
    def __init__(self, db_path: Optional[Path] = None):
        # None 时走 config（运行时动态）；测试可注入临时路径
        self.db_path = db_path if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_add_layer_column()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    layer TEXT NOT NULL DEFAULT 'episodic'
                )
            """)

    def _migrate_add_layer_column(self) -> None:
        """旧表（V1）没有 layer 列；存在时补列，默认 episodic。"""
        with sqlite3.connect(self.db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
            if "layer" not in cols:
                conn.execute(
                    "ALTER TABLE memory_items ADD COLUMN layer TEXT NOT NULL DEFAULT 'episodic'"
                )

    def add(self, item: MemoryItem) -> int:
        """写入记忆项，返回新行 id（并回填到 item.id）。

        V2 修复：原实现写入后 item.id 仍为 None，导致无法按 id 引用/删除。
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO memory_items (user_id, kind, content, metadata, created_at, layer)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.user_id,
                    item.kind,
                    item.content,
                    json.dumps(item.metadata, ensure_ascii=False),
                    item.created_at,
                    item.layer,
                ),
            )
            new_id = cur.lastrowid
        # 回填 id（pydantic v2 默认允许赋值，此处显式回填）
        item.id = new_id
        return new_id

    def search_by_user(
        self,
        user_id: str,
        limit: int = 20,
        layer: Optional[str] = None,
    ) -> List[MemoryItem]:
        sql = """
            SELECT user_id, kind, content, metadata, created_at, layer
            FROM memory_items
            WHERE user_id = ?
        """
        params: list = [user_id]
        if layer is not None:
            sql += " AND layer = ?"
            params.append(layer)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        items = []
        for user_id, kind, content, metadata, created_at, layer in rows:
            items.append(
                MemoryItem(
                    user_id=user_id,
                    kind=kind,
                    content=content,
                    metadata=json.loads(metadata),
                    created_at=created_at,
                    layer=layer,
                )
            )
        return items

    def search_related(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        kinds: Optional[Sequence[str]] = None,
        layers: Optional[Sequence[str]] = None,
    ) -> List[MemoryHit]:
        """
        轻量相关性检索：
        score = 关键词重叠 + kind权重 + layer权重 + 近期加分

        V2：新增 layers 过滤参数（按记忆层筛选）。
        """
        candidates = self.search_by_user(user_id=user_id, limit=200)

        if kinds:
            kinds_set = set(kinds)
            candidates = [x for x in candidates if x.kind in kinds_set]

        if layers:
            layers_set = set(layers)
            candidates = [x for x in candidates if x.layer in layers_set]

        q_terms = _tokenize(query)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        scored: List[MemoryHit] = []
        for item in candidates:
            doc_text = (
                item.content + " " + json.dumps(item.metadata, ensure_ascii=False)
            )
            d_terms = _tokenize(doc_text)

            overlap = len(q_terms & d_terms)

            # 近期记忆稍微加分
            age_days = max((now - _parse_dt(item.created_at)).days, 0)
            recency_bonus = 1.0 / (1.0 + age_days)

            score = (
                (overlap * 2.0)
                + _kind_weight(item.kind)
                + _layer_weight(item.layer)
                + recency_bonus
            )

            # 没有任何相关词时，也允许按 kind + recency 给一个很弱的兜底分
            if overlap == 0 and item.kind not in {"preference", "fact", "task_summary"}:
                continue

            scored.append(
                MemoryHit(
                    item=item,
                    score=score,
                    reason=(
                        f"overlap={overlap}, kind={item.kind}, "
                        f"layer={item.layer}, recency_bonus={recency_bonus:.3f}"
                    ),
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def count(self, user_id: Optional[str] = None, layer: Optional[str] = None) -> int:
        """统计条数（forget 策略评估与测试用）。"""
        sql = "SELECT COUNT(*) FROM memory_items WHERE 1=1"
        params: list = []
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        if layer is not None:
            sql += " AND layer = ?"
            params.append(layer)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def forget(self, *, user_id: Optional[str] = None, layer: Optional[str] = None,
               older_than_days: Optional[int] = None) -> int:
        """按条件删除记忆，返回删除条数（forget policy）。"""
        sql = "DELETE FROM memory_items WHERE 1=1"
        params: list = []
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        if layer is not None:
            sql += " AND layer = ?"
            params.append(layer)
        if older_than_days is not None:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=older_than_days)
            sql += " AND created_at < ?"
            params.append(cutoff.isoformat())
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount
